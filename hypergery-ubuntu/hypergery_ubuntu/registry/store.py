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
}

HOST_FIELDS = {
    "host_id",
    "name",
    "hostname",
    "status",
    "last_seen",
    "cpu_model",
    "ram_total_mib",
    "ram_free_mib",
    "disk_free_mib",
    "kvm_ok",
    "libvirt_ok",
    "hypergery_version",
    "active_vms",
    "notes",
}

MIGRATION_FIELDS = {
    "migration_id",
    "source_host_id",
    "target_host_id",
    "source_vm_name",
    "target_vm_name",
    "strategy",
    "status",
    "created_at",
    "updated_at",
    "result",
    "errors",
    "warnings",
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
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self.connect()) as conn:
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
                    notes TEXT NOT NULL
                )
                """
            )
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
                    updated_at TEXT NOT NULL
                )
                """
            )
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT NOT NULL,
                    errors TEXT NOT NULL,
                    warnings TEXT NOT NULL
                )
                """
            )

    def _host_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        host = dict(row)
        host["kvm_ok"] = bool(host["kvm_ok"])
        host["libvirt_ok"] = bool(host["libvirt_ok"])
        host["active_vms"] = _json_load(host.get("active_vms"), [])
        host["status"] = self.effective_host_status(host["last_seen"], host.get("status", "offline"))
        return {key: host.get(key) for key in HOST_FIELDS}

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
        }
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO hosts (
                    host_id, name, hostname, status, last_seen, cpu_model,
                    ram_total_mib, ram_free_mib, disk_free_mib, kvm_ok,
                    libvirt_ok, hypergery_version, active_vms, notes
                ) VALUES (
                    :host_id, :name, :hostname, :status, :last_seen, :cpu_model,
                    :ram_total_mib, :ram_free_mib, :disk_free_mib, :kvm_ok,
                    :libvirt_ok, :hypergery_version, :active_vms, :notes
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
                    notes=excluded.notes
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

    def create_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_type = str(payload.get("command_type") or "").strip()
        if command_type not in ALLOWED_COMMAND_TYPES:
            raise HyperGeryError(f"Unsupported command_type: {command_type}")
        target_host_id = _host_id(str(payload.get("target_host_id") or ""))
        command_id = str(payload.get("command_id") or f"cmd-{uuid.uuid4().hex}")
        timestamp = now_iso()
        command = {
            "command_id": command_id,
            "target_host_id": target_host_id,
            "command_type": command_type,
            "payload": _json_dump(payload.get("payload") or {}),
            "status": "pending",
            "result": _json_dump({}),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO commands (
                    command_id, target_host_id, command_type, payload, status,
                    result, created_at, updated_at
                ) VALUES (
                    :command_id, :target_host_id, :command_type, :payload, :status,
                    :result, :created_at, :updated_at
                )
                """,
                command,
            )
        return self.get_command(command_id)

    def _command_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        command = dict(row)
        command["payload"] = _json_load(command.get("payload"), {})
        command["result"] = _json_load(command.get("result"), {})
        return command

    def get_command(self, command_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM commands WHERE command_id = ?", (command_id,)).fetchone()
        if row is None:
            raise HyperGeryError(f"Command does not exist: {command_id}")
        return self._command_from_row(row)

    def pending_commands_for_host(self, host_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
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
            changed = conn.execute(
                "UPDATE commands SET status = ?, result = ?, updated_at = ? WHERE command_id = ?",
                (status, _json_dump(result), now_iso(), command_id),
            ).rowcount
        if not changed:
            raise HyperGeryError(f"Command does not exist: {command_id}")
        return self.get_command(command_id)

    def _migration_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        migration = dict(row)
        migration["result"] = _json_load(migration.get("result"), {})
        migration["errors"] = _json_load(migration.get("errors"), [])
        migration["warnings"] = _json_load(migration.get("warnings"), [])
        return {key: migration.get(key) for key in MIGRATION_FIELDS}

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
        if status not in {
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
        }:
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
            "created_at": str(payload.get("created_at") or timestamp),
            "updated_at": timestamp,
            "result": _json_dump(payload.get("result") or {}),
            "errors": _json_dump(payload.get("errors") or []),
            "warnings": _json_dump(payload.get("warnings") or []),
        }
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT created_at FROM migrations WHERE migration_id = ?", (clean_id,)).fetchone()
            if existing:
                migration["created_at"] = existing["created_at"]
            conn.execute(
                """
                INSERT INTO migrations (
                    migration_id, source_host_id, target_host_id, source_vm_name,
                    target_vm_name, strategy, status, created_at, updated_at,
                    result, errors, warnings
                ) VALUES (
                    :migration_id, :source_host_id, :target_host_id, :source_vm_name,
                    :target_vm_name, :strategy, :status, :created_at, :updated_at,
                    :result, :errors, :warnings
                )
                ON CONFLICT(migration_id) DO UPDATE SET
                    source_host_id=excluded.source_host_id,
                    target_host_id=excluded.target_host_id,
                    source_vm_name=excluded.source_vm_name,
                    target_vm_name=excluded.target_vm_name,
                    strategy=excluded.strategy,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    result=excluded.result,
                    errors=excluded.errors,
                    warnings=excluded.warnings
                """,
                migration,
            )
        return self.get_migration(clean_id)
