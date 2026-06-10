from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..backend import HyperGeryError, xdg_data_home


ALLOWED_COMMAND_TYPES = {
    "ping",
    "preflight",
    "list_vms",
    "receive_vm_package",
    "import_vm_package",
    "migration_status",
    # v0.8 remote VM power control. Deliberately excluded: delete, undefine,
    # delete-disks, XML edits, arbitrary shell — nothing destructive on disks.
    "vm_start",
    "vm_shutdown",
    "vm_force_off",
    # v1 state-preserving teleport: the target restores a VM from its saved
    # RAM+CPU state (continues, not reboot). Still no destructive ops.
    "restore_vm_state_package",
}

# HG-BUG-0005: el Hub es un ThreadingHTTPServer con varias conexiones SQLite
# concurrentes; sin busy_timeout cualquier choque de escrituras devolvía
# "database is locked" inmediatamente.
SQLITE_BUSY_TIMEOUT_MS = 5000

# HG-BUG-0006: TTL de comandos. Un comando que ningún agente recoge dentro de
# su TTL caduca y NUNCA se entrega (un vm_force_off encolado horas antes no
# debe ejecutarse cuando el host vuelva).
DEFAULT_COMMAND_TTL_SECONDS = 600
MIN_COMMAND_TTL_SECONDS = 10
MAX_COMMAND_TTL_SECONDS = 86400

MIGRATION_STATUSES = {
    "created",
    "preflight",
    "packaging",
    "uploaded",
    "waiting_target",
    "importing",
    "defining_vm",
    "done",
    "failed",
    "rolled_back",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def default_registry_db_path() -> Path:
    override = Path(str(xdg_data_home())) / "registry" / "registry.sqlite3"
    override.parent.mkdir(parents=True, exist_ok=True)
    return override


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True)


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _host_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise HyperGeryError("host_id is required.")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise HyperGeryError("host_id cannot contain path traversal characters.")
    return clean


class RegistryStore:
    def __init__(self, db_path: str | Path | None = None, *, offline_timeout_seconds: int = 90) -> None:
        self.db_path = Path(db_path).expanduser() if db_path else default_registry_db_path()
        self.offline_timeout_seconds = offline_timeout_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        with closing(self.connect()) as conn:
            # WAL es persistente en el fichero: lectores y escritores dejan de
            # bloquearse entre sí (HG-BUG-0005).
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hosts (
                    host_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    cpu_model TEXT NOT NULL,
                    ram_total_mib INTEGER NOT NULL,
                    ram_free_mib INTEGER NOT NULL,
                    disk_free_mib INTEGER NOT NULL,
                    kvm_ok INTEGER NOT NULL,
                    libvirt_ok INTEGER NOT NULL,
                    hypergery_version TEXT NOT NULL,
                    active_vms TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_column(conn, "hosts", "created_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "hosts", "updated_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "hosts", "telemetry_json", "TEXT NOT NULL DEFAULT ''")
            # Para construir la URI qemu+ssh de live migration sin que el usuario
            # la teclee: el agente reporta su usuario SSH y su IP.
            self._ensure_column(conn, "hosts", "ssh_user", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "hosts", "ssh_address", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS host_vms (
                    host_id TEXT NOT NULL,
                    vm_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    lab_id TEXT NOT NULL,
                    display TEXT NOT NULL,
                    ram_mib INTEGER NOT NULL,
                    vcpus INTEGER NOT NULL,
                    disk_paths_json TEXT NOT NULL,
                    iso_paths_json TEXT NOT NULL,
                    networks_json TEXT NOT NULL DEFAULT '',
                    macs_json TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(host_id, vm_name)
                )
                """
            )
            self._ensure_column(conn, "host_vms", "networks_json", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "host_vms", "macs_json", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    target_host_id TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_column(conn, "commands", "expires_at", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS migrations (
                    migration_id TEXT PRIMARY KEY,
                    source_host_id TEXT NOT NULL,
                    target_host_id TEXT NOT NULL,
                    source_vm_name TEXT NOT NULL,
                    target_vm_name TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    package_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT NOT NULL,
                    errors TEXT NOT NULL,
                    warnings TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "migrations", "package_path", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def effective_host_status(self, last_seen: str, status: str) -> str:
        if status == "offline":
            return "offline"
        try:
            seen = datetime.fromisoformat(last_seen)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=UTC)
        except ValueError:
            return "offline"
        if datetime.now(UTC) - seen > timedelta(seconds=self.offline_timeout_seconds):
            return "offline"
        return "online"

    def _host_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        host = dict(row)
        host["kvm_ok"] = bool(host["kvm_ok"])
        host["libvirt_ok"] = bool(host["libvirt_ok"])
        host["active_vms"] = _json_load(host.get("active_vms"), [])
        host["telemetry"] = _json_load(host.pop("telemetry_json", ""), {})
        host["status"] = self.effective_host_status(host["last_seen"], host.get("status", "offline"))
        return host

    def register_host(self, payload: dict[str, Any]) -> dict[str, Any]:
        host_id = _host_id(str(payload.get("host_id") or payload.get("hostname") or ""))
        timestamp = now_iso()
        host = {
            "host_id": host_id,
            "name": str(payload.get("name") or host_id),
            "hostname": str(payload.get("hostname") or ""),
            "status": "online",
            "last_seen": timestamp,
            "cpu_model": str(payload.get("cpu_model") or ""),
            "ram_total_mib": int(payload.get("ram_total_mib") or 0),
            "ram_free_mib": int(payload.get("ram_free_mib") or 0),
            "disk_free_mib": int(payload.get("disk_free_mib") or 0),
            "kvm_ok": 1 if payload.get("kvm_ok") else 0,
            "libvirt_ok": 1 if payload.get("libvirt_ok") else 0,
            "hypergery_version": str(payload.get("hypergery_version") or ""),
            "active_vms": _json_dump(payload.get("active_vms") or []),
            "notes": str(payload.get("notes") or ""),
            "created_at": timestamp,
            "updated_at": timestamp,
            "telemetry_json": _json_dump(payload.get("telemetry") or {}),
            "ssh_user": str(payload.get("ssh_user") or ""),
            "ssh_address": str(payload.get("ssh_address") or ""),
        }
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT created_at FROM hosts WHERE host_id = ?", (host_id,)).fetchone()
            if existing and existing["created_at"]:
                host["created_at"] = existing["created_at"]
            conn.execute(
                """
                INSERT INTO hosts (
                    host_id, name, hostname, status, last_seen, cpu_model,
                    ram_total_mib, ram_free_mib, disk_free_mib, kvm_ok,
                    libvirt_ok, hypergery_version, active_vms, notes,
                    created_at, updated_at, telemetry_json, ssh_user, ssh_address
                ) VALUES (
                    :host_id, :name, :hostname, :status, :last_seen, :cpu_model,
                    :ram_total_mib, :ram_free_mib, :disk_free_mib, :kvm_ok,
                    :libvirt_ok, :hypergery_version, :active_vms, :notes,
                    :created_at, :updated_at, :telemetry_json, :ssh_user, :ssh_address
                )
                ON CONFLICT(host_id) DO UPDATE SET
                    name=excluded.name,
                    hostname=excluded.hostname,
                    status=excluded.status,
                    last_seen=excluded.last_seen,
                    cpu_model=excluded.cpu_model,
                    ram_total_mib=excluded.ram_total_mib,
                    ram_free_mib=excluded.ram_free_mib,
                    disk_free_mib=excluded.disk_free_mib,
                    kvm_ok=excluded.kvm_ok,
                    libvirt_ok=excluded.libvirt_ok,
                    hypergery_version=excluded.hypergery_version,
                    active_vms=excluded.active_vms,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at,
                    telemetry_json=excluded.telemetry_json,
                    ssh_user=excluded.ssh_user,
                    ssh_address=excluded.ssh_address
                """,
                host,
            )
        return self.get_host(host_id)

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.register_host(payload)

    def list_hosts(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM hosts ORDER BY host_id").fetchall()
        return [self._host_from_row(row) for row in rows]

    def get_host(self, host_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM hosts WHERE host_id = ?", (_host_id(host_id),)).fetchone()
        if row is None:
            raise HyperGeryError(f"Host does not exist: {host_id}")
        return self._host_from_row(row)

    def report_vms(self, payload: dict[str, Any]) -> dict[str, Any]:
        host_id = _host_id(str(payload.get("host_id") or ""))
        vms = payload.get("vms") or []
        if not isinstance(vms, list):
            raise HyperGeryError("vms must be a list.")
        timestamp = now_iso()
        rows = []
        active_vms = []
        for item in vms:
            if not isinstance(item, dict):
                raise HyperGeryError("Each VM inventory item must be an object.")
            vm_name = str(item.get("vm_name") or item.get("name") or "").strip()
            if not vm_name:
                raise HyperGeryError("vm_name is required for each inventory item.")
            state = str(item.get("state") or "unknown")
            if state in {"running", "paused"}:
                active_vms.append(vm_name)
            rows.append(
                {
                    "host_id": host_id,
                    "vm_name": vm_name,
                    "state": state,
                    "lab_id": str(item.get("lab_id") or ""),
                    "display": str(item.get("display") or item.get("graphics") or "unknown"),
                    "ram_mib": int(item.get("ram_mib") or 0),
                    "vcpus": int(item.get("vcpus") or 0),
                    "disk_paths_json": _json_dump(item.get("disk_paths") or ([] if not item.get("disk_path") else [item.get("disk_path")])),
                    "iso_paths_json": _json_dump(item.get("iso_paths") or ([] if not item.get("iso_path") else [item.get("iso_path")])),
                    "networks_json": _json_dump(item.get("networks") or ([] if not item.get("network") else [item.get("network")])),
                    "macs_json": _json_dump(item.get("macs") or item.get("mac_addresses") or []),
                    "updated_at": timestamp,
                }
            )
        with closing(self.connect()) as conn:
            conn.execute("DELETE FROM host_vms WHERE host_id = ?", (host_id,))
            conn.executemany(
                """
                INSERT INTO host_vms (
                    host_id, vm_name, state, lab_id, display, ram_mib, vcpus,
                    disk_paths_json, iso_paths_json, networks_json, macs_json,
                    updated_at
                ) VALUES (
                    :host_id, :vm_name, :state, :lab_id, :display, :ram_mib, :vcpus,
                    :disk_paths_json, :iso_paths_json, :networks_json, :macs_json,
                    :updated_at
                )
                """,
                rows,
            )
            conn.execute(
                "UPDATE hosts SET active_vms = ?, updated_at = ? WHERE host_id = ?",
                (_json_dump(active_vms), timestamp, host_id),
            )
        return {"host_id": host_id, "count": len(rows), "vms": self.list_vms(host_id)}

    def _vm_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        vm = dict(row)
        vm["disk_paths"] = _json_load(vm.pop("disk_paths_json", ""), [])
        vm["iso_paths"] = _json_load(vm.pop("iso_paths_json", ""), [])
        vm["networks"] = _json_load(vm.pop("networks_json", ""), [])
        vm["macs"] = _json_load(vm.pop("macs_json", ""), [])
        return vm

    def list_vms(self, host_id: str | None = None) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            if host_id:
                rows = conn.execute(
                    "SELECT * FROM host_vms WHERE host_id = ? ORDER BY vm_name",
                    (_host_id(host_id),),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM host_vms ORDER BY host_id, vm_name").fetchall()
        return [self._vm_from_row(row) for row in rows]

    def create_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_type = str(payload.get("command_type") or "").strip()
        if command_type not in ALLOWED_COMMAND_TYPES:
            raise HyperGeryError(f"Unsupported command_type: {command_type}")
        target_host_id = _host_id(str(payload.get("target_host_id") or ""))
        command_id = str(payload.get("command_id") or f"cmd-{uuid.uuid4().hex}")
        try:
            ttl_seconds = int(payload.get("ttl_seconds") or DEFAULT_COMMAND_TTL_SECONDS)
        except (TypeError, ValueError) as exc:
            raise HyperGeryError(f"ttl_seconds must be a number, got: {payload.get('ttl_seconds')!r}") from exc
        ttl_seconds = max(MIN_COMMAND_TTL_SECONDS, min(ttl_seconds, MAX_COMMAND_TTL_SECONDS))
        now = datetime.now(UTC).replace(microsecond=0)
        timestamp = now.isoformat()
        command = {
            "command_id": command_id,
            "target_host_id": target_host_id,
            "command_type": command_type,
            "payload": _json_dump(payload.get("payload") or payload.get("payload_json") or {}),
            "status": "pending",
            "result": _json_dump({}),
            "created_at": timestamp,
            "updated_at": timestamp,
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO commands (
                    command_id, target_host_id, command_type, payload, status,
                    result, created_at, updated_at, expires_at
                ) VALUES (
                    :command_id, :target_host_id, :command_type, :payload, :status,
                    :result, :created_at, :updated_at, :expires_at
                )
                """,
                command,
            )
        return self.get_command(command_id)

    def _expire_pending_commands(self, conn: sqlite3.Connection) -> int:
        """Caduca (status=failed) los comandos pending cuyo TTL venció.

        HG-BUG-0006: la caducidad bloquea la ENTREGA — un comando que ya está
        running/done no se toca. Se marca con result.expired=true para que
        set_command_result no pueda resucitarlo.
        """
        return conn.execute(
            "UPDATE commands SET status = 'failed', result = ?, updated_at = ? "
            "WHERE status = 'pending' AND expires_at != '' AND expires_at <= ?",
            (
                _json_dump({"error": "Command expired before delivery (TTL).", "expired": True}),
                now_iso(),
                now_iso(),
            ),
        ).rowcount

    def _command_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        command = dict(row)
        command["payload"] = _json_load(command.get("payload"), {})
        command["result"] = _json_load(command.get("result"), {})
        return command

    def get_command(self, command_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            self._expire_pending_commands(conn)
            row = conn.execute("SELECT * FROM commands WHERE command_id = ?", (command_id,)).fetchone()
        if row is None:
            raise HyperGeryError(f"Command does not exist: {command_id}")
        return self._command_from_row(row)

    COMMAND_LIST_STATUSES = {"pending", "running", "done", "failed"}

    def list_commands(
        self,
        *,
        target_host_id: str | None = None,
        status: str | None = None,
        command_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read-only command queue listing, newest first, with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if target_host_id:
            clauses.append("target_host_id = ?")
            params.append(_host_id(target_host_id))
        if status:
            if status not in self.COMMAND_LIST_STATUSES:
                raise HyperGeryError(f"Unsupported command status filter: {status}")
            clauses.append("status = ?")
            params.append(status)
        if command_type:
            if command_type not in ALLOWED_COMMAND_TYPES:
                raise HyperGeryError(f"Unsupported command_type filter: {command_type}")
            clauses.append("command_type = ?")
            params.append(command_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            clamped_limit = max(1, min(int(limit or 100), 500))
        except (TypeError, ValueError) as exc:
            raise HyperGeryError(f"limit must be a number, got: {limit!r}") from exc
        params.append(clamped_limit)
        with closing(self.connect()) as conn:
            self._expire_pending_commands(conn)
            rows = conn.execute(
                f"SELECT * FROM commands {where} ORDER BY created_at DESC, command_id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._command_from_row(row) for row in rows]

    def pending_commands_for_host(self, host_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            self._expire_pending_commands(conn)
            rows = conn.execute(
                "SELECT * FROM commands WHERE target_host_id = ? AND status = 'pending' ORDER BY created_at",
                (_host_id(host_id),),
            ).fetchall()
        return [self._command_from_row(row) for row in rows]

    def set_command_result(self, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status") or "done")
        if status not in {"running", "done", "failed"}:
            raise HyperGeryError("Command result status must be running, done, or failed.")
        result = payload.get("result") or {}
        with closing(self.connect()) as conn:
            self._expire_pending_commands(conn)
            row = conn.execute(
                "SELECT result FROM commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            if row is None:
                raise HyperGeryError(f"Command does not exist: {command_id}")
            if _json_load(row["result"], {}).get("expired"):
                raise HyperGeryError(f"Command expired before delivery (TTL): {command_id}")
            conn.execute(
                "UPDATE commands SET status = ?, result = ?, updated_at = ? WHERE command_id = ?",
                (status, _json_dump(result), now_iso(), command_id),
            )
        return self.get_command(command_id)

    def _migration_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        migration = dict(row)
        migration["result"] = _json_load(migration.get("result"), {})
        migration["errors"] = _json_load(migration.get("errors"), [])
        migration["warnings"] = _json_load(migration.get("warnings"), [])
        return migration

    def create_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        migration_id = str(payload.get("migration_id") or f"mig-{uuid.uuid4().hex}")
        return self.update_migration_status(migration_id, {**payload, "status": payload.get("status") or "created"})

    def list_migrations(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM migrations ORDER BY created_at DESC").fetchall()
        return [self._migration_from_row(row) for row in rows]

    def get_migration(self, migration_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM migrations WHERE migration_id = ?", (migration_id,)).fetchone()
        if row is None:
            raise HyperGeryError(f"Migration does not exist: {migration_id}")
        return self._migration_from_row(row)

    def update_migration_status(self, migration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean_id = str(migration_id or "").strip()
        if not clean_id:
            raise HyperGeryError("migration_id is required.")
        status = str(payload.get("status") or "created")
        if status not in MIGRATION_STATUSES:
            raise HyperGeryError(f"Unsupported migration status: {status}")
        timestamp = now_iso()
        migration = {
            "migration_id": clean_id,
            "source_host_id": str(payload.get("source_host_id") or ""),
            "target_host_id": str(payload.get("target_host_id") or ""),
            "source_vm_name": str(payload.get("source_vm_name") or ""),
            "target_vm_name": str(payload.get("target_vm_name") or ""),
            "strategy": str(payload.get("strategy") or "nas_clone"),
            "status": status,
            "package_path": str(payload.get("package_path") or payload.get("package_dir") or ""),
            "created_at": str(payload.get("created_at") or timestamp),
            "updated_at": timestamp,
            "result": _json_dump(payload.get("result") or {}),
            "errors": _json_dump(payload.get("errors") or []),
            "warnings": _json_dump(payload.get("warnings") or []),
        }
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT created_at, package_path FROM migrations WHERE migration_id = ?", (clean_id,)).fetchone()
            if existing:
                migration["created_at"] = existing["created_at"]
                if not migration["package_path"]:
                    migration["package_path"] = existing["package_path"]
            conn.execute(
                """
                INSERT INTO migrations (
                    migration_id, source_host_id, target_host_id, source_vm_name,
                    target_vm_name, strategy, status, package_path, created_at,
                    updated_at, result, errors, warnings
                ) VALUES (
                    :migration_id, :source_host_id, :target_host_id, :source_vm_name,
                    :target_vm_name, :strategy, :status, :package_path, :created_at,
                    :updated_at, :result, :errors, :warnings
                )
                ON CONFLICT(migration_id) DO UPDATE SET
                    source_host_id=excluded.source_host_id,
                    target_host_id=excluded.target_host_id,
                    source_vm_name=excluded.source_vm_name,
                    target_vm_name=excluded.target_vm_name,
                    strategy=excluded.strategy,
                    status=excluded.status,
                    package_path=excluded.package_path,
                    updated_at=excluded.updated_at,
                    result=excluded.result,
                    errors=excluded.errors,
                    warnings=excluded.warnings
                """,
                migration,
            )
        return self.get_migration(clean_id)

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "event_id": str(payload.get("event_id") or f"evt-{uuid.uuid4().hex}"),
            "kind": str(payload.get("kind") or "info"),
            "message": str(payload.get("message") or ""),
            "payload_json": _json_dump(payload.get("payload") or payload.get("payload_json") or {}),
            "created_at": str(payload.get("created_at") or now_iso()),
        }
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO events (event_id, kind, message, payload_json, created_at)
                VALUES (:event_id, :kind, :message, :payload_json, :created_at)
                """,
                event,
            )
        return self.get_event(event["event_id"])

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        event["payload"] = _json_load(event.pop("payload_json", ""), {})
        return event

    def get_event(self, event_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None:
            raise HyperGeryError(f"Event does not exist: {event_id}")
        return self._event_from_row(row)

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit or 100), 500)),),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]
