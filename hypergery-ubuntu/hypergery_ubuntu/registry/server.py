from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..backend import HyperGeryError
from .auth import AuthRateLimiter, bearer_token, load_or_create_hub_token, token_matches
from .store import MIGRATION_STATUSES, RegistryStore

TRANSFER_CHUNK_BYTES = 1024 * 1024

# HG-BUG-0010: límite por fichero subido al staging. Configurable con
# HYPERGERY_HUB_MAX_UPLOAD_MIB (0 = sin límite explícito; la comprobación de
# espacio libre sigue aplicando).
DEFAULT_MAX_UPLOAD_MIB = 64 * 1024  # 64 GiB: discos de VM grandes caben

# Nunca aceptar una subida que dejaría el disco del staging por debajo de
# este margen.
FREE_DISK_MARGIN_BYTES = 1024 * 1024 * 1024  # 1 GiB


def default_max_upload_bytes() -> int:
    raw = os.environ.get("HYPERGERY_HUB_MAX_UPLOAD_MIB", "")
    try:
        mib = int(raw) if raw else DEFAULT_MAX_UPLOAD_MIB
    except ValueError:
        mib = DEFAULT_MAX_UPLOAD_MIB
    return max(0, mib) * 1024 * 1024

# Migrations in these states may still need their staged package; cleanup
# always skips them, regardless of age or flags.
ACTIVE_MIGRATION_STATUSES = MIGRATION_STATUSES - {"done", "failed", "rolled_back"}

# Cleanup never touches packages newer than this, even if the caller asks
# for a smaller threshold — an upload could still be in progress.
MIN_CLEANUP_AGE_HOURS = 1.0


def default_staging_dir(db_path: str | Path | None = None) -> Path:
    override = os.environ.get("HYPERGERY_HUB_STAGING", "")
    if override:
        return Path(override).expanduser()
    if db_path:
        return Path(db_path).expanduser().parent / "staging"
    from .store import default_registry_db_path

    return default_registry_db_path().parent / "staging"


def _safe_package_path(staging_dir: Path, migration_id: str, rel_path: str = "") -> Path:
    if not migration_id or "/" in migration_id or migration_id in {".", ".."}:
        raise HyperGeryError(f"Invalid migration id: {migration_id!r}")
    base = (staging_dir / migration_id).resolve()
    staging_root = staging_dir.resolve()
    if base.parent != staging_root:
        raise HyperGeryError(f"Invalid migration id: {migration_id!r}")
    if not rel_path:
        return base
    candidate = (base / rel_path).resolve()
    if base not in candidate.parents and candidate != base:
        raise HyperGeryError(f"Invalid package file path: {rel_path!r}")
    return candidate


def _mtime_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).replace(microsecond=0).isoformat()


def _package_stats(package_dir: Path) -> tuple[int, int, float]:
    """Return (size_bytes, file_count, newest_mtime) without following symlinks."""
    size_bytes = 0
    file_count = 0
    newest = package_dir.stat().st_mtime
    for item in package_dir.rglob("*"):
        if item.is_symlink():
            continue
        if item.is_file():
            stat = item.stat()
            size_bytes += stat.st_size
            file_count += 1
            newest = max(newest, stat.st_mtime)
    return size_bytes, file_count, newest


def list_staged_packages(staging_dir: str | Path, store: RegistryStore) -> dict[str, Any]:
    """List Hub staging packages with size, age, and linked migration status."""
    staging = Path(staging_dir).expanduser()
    packages: list[dict[str, Any]] = []
    total_size = 0
    orphans = 0
    if staging.is_dir():
        for entry in sorted(staging.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            size_bytes, file_count, newest_mtime = _package_stats(entry)
            age_hours = max(0.0, (time.time() - newest_mtime) / 3600)
            try:
                migration_status = str(store.get_migration(entry.name).get("status") or "")
            except HyperGeryError:
                migration_status = ""
            orphan = not migration_status
            if orphan:
                orphans += 1
            total_size += size_bytes
            packages.append(
                {
                    "migration_id": entry.name,
                    "path": entry.name,
                    "size_bytes": size_bytes,
                    "file_count": file_count,
                    "created_at": _mtime_iso(entry.stat().st_mtime),
                    "modified_at": _mtime_iso(newest_mtime),
                    "age_hours": round(age_hours, 2),
                    "migration_status": migration_status,
                    "orphan": orphan,
                }
            )
    return {
        "staging_dir": str(staging),
        "count": len(packages),
        "orphan_count": orphans,
        "total_size_bytes": total_size,
        "packages": packages,
    }


def cleanup_staged_packages(
    staging_dir: str | Path,
    store: RegistryStore,
    *,
    older_than_hours: float = 24.0,
    dry_run: bool = True,
    include_failed: bool = False,
    include_orphans: bool = True,
) -> dict[str, Any]:
    """Delete (or preview) leftover Hub staging packages.

    Only temporary staging package directories are ever removed: never VM
    definitions, never imported disks, never anything outside staging_dir.
    Packages of active migrations and packages newer than the threshold are
    always skipped.
    """
    try:
        threshold_hours = float(older_than_hours)
    except (TypeError, ValueError) as exc:
        raise HyperGeryError(f"older_than_hours must be a number, got: {older_than_hours!r}") from exc
    if threshold_hours < 0:
        raise HyperGeryError("older_than_hours cannot be negative.")
    threshold_hours = max(threshold_hours, MIN_CLEANUP_AGE_HOURS)

    staging = Path(staging_dir).expanduser()
    listing = list_staged_packages(staging, store)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def skip(package: dict[str, Any], reason: str) -> None:
        skipped.append({"migration_id": package["migration_id"], "reason": reason})

    for package in listing["packages"]:
        status = package["migration_status"]
        if status in ACTIVE_MIGRATION_STATUSES:
            skip(package, f"migration is active (status: {status})")
            continue
        if package["age_hours"] < threshold_hours:
            skip(package, f"too recent ({package['age_hours']}h < {threshold_hours}h)")
            continue
        if package["orphan"]:
            if include_orphans:
                candidates.append({**package, "reason": "no migration record on the Hub (orphan)"})
            else:
                skip(package, "orphan package (include_orphans disabled)")
        elif status == "done":
            candidates.append({**package, "reason": "migration done; leftover staging package"})
        elif status in {"failed", "rolled_back"}:
            if include_failed:
                candidates.append({**package, "reason": f"migration {status}"})
            else:
                skip(package, f"migration {status} (include_failed disabled)")
        else:
            skip(package, f"unrecognized migration status: {status}")

    deleted: list[dict[str, Any]] = []
    deleted_size = 0
    if not dry_run:
        for candidate in candidates:
            migration_id = candidate["migration_id"]
            try:
                # Re-validate against traversal even though ids come from
                # directory names we listed ourselves.
                package_dir = _safe_package_path(staging, migration_id)
                shutil.rmtree(package_dir)
                deleted.append({"migration_id": migration_id, "size_bytes": candidate["size_bytes"]})
                deleted_size += candidate["size_bytes"]
            except (HyperGeryError, OSError) as exc:
                errors.append({"migration_id": migration_id, "error": str(exc)})

    return {
        "staging_dir": str(staging),
        "dry_run": bool(dry_run),
        "older_than_hours": threshold_hours,
        "include_failed": bool(include_failed),
        "include_orphans": bool(include_orphans),
        "candidates": candidates,
        "total_size_bytes": sum(item["size_bytes"] for item in candidates),
        "deleted_count": len(deleted),
        "deleted_size_bytes": deleted_size,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
    }


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HyperGeryError(f"Invalid JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise HyperGeryError("JSON body must be an object.")
    return data


class RegistryServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        store: RegistryStore,
        *,
        staging_dir: str | Path | None = None,
        max_upload_bytes: int | None = None,
        auth_token: str | None = None,
    ) -> None:
        super().__init__(server_address, RegistryRequestHandler)
        self.store = store
        self.staging_dir = Path(staging_dir).expanduser() if staging_dir else default_staging_dir(store.db_path)
        self.max_upload_bytes = default_max_upload_bytes() if max_upload_bytes is None else max(0, int(max_upload_bytes))
        # HG-BUG-0001: token obligatorio por defecto. auth_token="" lo
        # desactiva explícitamente (solo LAN de confianza; queda registrado).
        self.auth_token = load_or_create_hub_token(store.db_path) if auth_token is None else auth_token
        if not self.auth_token:
            logging.warning("Hub auth is DISABLED (explicit empty token). Only safe on a trusted LAN.")
        self.auth_limiter = AuthRateLimiter()


class RegistryRequestHandler(BaseHTTPRequestHandler):
    server: RegistryServer

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _authenticate(self) -> bool:
        """HG-BUG-0001: Bearer token obligatorio en todo excepto GET /health.

        Los fallos se auditan en la tabla de eventos y se limitan por IP
        (anti fuerza bruta). Devuelve False si ya se envió una respuesta.
        """
        if not self.server.auth_token:
            return True
        path = [part for part in urlparse(self.path).path.split("/") if part]
        if self.command == "GET" and path == ["health"]:
            return True
        client_ip = self.client_address[0] if self.client_address else "?"
        if self.server.auth_limiter.is_blocked(client_ip):
            self._send_error(429, "Too many failed authentication attempts. Try again later.")
            return False
        presented = bearer_token(self.headers.get("Authorization"))
        if token_matches(self.server.auth_token, presented):
            self.server.auth_limiter.record_success(client_ip)
            return True
        self.server.auth_limiter.record_failure(client_ip)
        logging.warning("Hub auth failure from %s for %s %s", client_ip, self.command, self.path)
        try:
            self.server.store.create_event(
                {
                    "kind": "auth_failure",
                    "message": f"Rejected {self.command} {urlparse(self.path).path} from {client_ip}",
                    "payload": {"ip": client_ip, "method": self.command},
                }
            )
        except Exception:
            pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Bearer")
        body = json.dumps({"error": "Authentication required: send Authorization: Bearer <hub token>."}).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _package_parts(self) -> tuple[str, str] | None:
        """Return (migration_id, rel_path) for /packages/... URLs, else None."""
        parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
        if not parts or parts[0] != "packages":
            return None
        if len(parts) < 2:
            raise HyperGeryError("Package URL requires a migration id.")
        return parts[1], "/".join(parts[2:])

    def _send_package_listing(self, migration_id: str) -> None:
        package_dir = _safe_package_path(self.server.staging_dir, migration_id)
        if not package_dir.is_dir():
            self._send_error(404, f"Package not staged: {migration_id}")
            return
        files = []
        for item in sorted(package_dir.rglob("*")):
            if item.is_file():
                files.append(
                    {
                        "path": str(item.relative_to(package_dir)),
                        "size_bytes": item.stat().st_size,
                    }
                )
        self._send_json(200, {"migration_id": migration_id, "files": files})

    def _send_package_file(self, migration_id: str, rel_path: str) -> None:
        file_path = _safe_package_path(self.server.staging_dir, migration_id, rel_path)
        if not file_path.is_file():
            self._send_error(404, f"Package file not staged: {migration_id}/{rel_path}")
            return
        size = file_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with file_path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile, TRANSFER_CHUNK_BYTES)

    def _receive_package_file(self, migration_id: str, rel_path: str) -> None:
        if not rel_path:
            raise HyperGeryError("Package upload requires a file path.")
        file_path = _safe_package_path(self.server.staging_dir, migration_id, rel_path)
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError as exc:
            raise HyperGeryError("Package upload requires a numeric Content-Length.") from exc
        if length <= 0:
            raise HyperGeryError("Package upload requires a positive Content-Length.")
        # HG-BUG-0010: sin límite, un cliente podía llenar el disco del Hub.
        limit = self.server.max_upload_bytes
        if limit and length > limit:
            self._send_error(413, f"Package file exceeds the upload limit ({length} > {limit} bytes).")
            return
        self.server.staging_dir.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(self.server.staging_dir).free
        if length + FREE_DISK_MARGIN_BYTES > free_bytes:
            self._send_error(
                507,
                f"Not enough free space in staging for this upload ({length} bytes, {free_bytes} free).",
            )
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        remaining = length
        with file_path.open("wb") as handle:
            while remaining > 0:
                chunk = self.rfile.read(min(TRANSFER_CHUNK_BYTES, remaining))
                if not chunk:
                    raise HyperGeryError(f"Package upload truncated: {migration_id}/{rel_path}")
                handle.write(chunk)
                remaining -= len(chunk)
        self._send_json(201, {"migration_id": migration_id, "path": rel_path, "size_bytes": length})

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authenticate():
            return
        try:
            package = self._package_parts()
            if package is None:
                self._send_error(404, "not found")
                return
            self._receive_package_file(*package)
        except HyperGeryError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authenticate():
            return
        try:
            package = self._package_parts()
            if package is None:
                self._send_error(404, "not found")
                return
            migration_id, rel_path = package
            if rel_path:
                raise HyperGeryError("Only whole packages can be deleted.")
            package_dir = _safe_package_path(self.server.staging_dir, migration_id)
            existed = package_dir.is_dir()
            if existed:
                shutil.rmtree(package_dir)
            self._send_json(200, {"migration_id": migration_id, "deleted": existed})
        except HyperGeryError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_GET(self) -> None:  # noqa: N802
        if not self._authenticate():
            return
        try:
            if [part for part in urlparse(self.path).path.split("/") if part] == ["packages"]:
                self._send_json(200, list_staged_packages(self.server.staging_dir, self.server.store))
                return
            package = self._package_parts()
            if package is not None:
                migration_id, rel_path = package
                if rel_path:
                    self._send_package_file(migration_id, rel_path)
                else:
                    self._send_package_listing(migration_id)
                return
            path = [part for part in urlparse(self.path).path.split("/") if part]
            if path == ["health"]:
                self._send_json(200, {"ok": True})
                return
            if path == ["hosts"]:
                self._send_json(200, {"hosts": self.server.store.list_hosts()})
                return
            if len(path) == 2 and path[0] == "hosts":
                self._send_json(200, self.server.store.get_host(path[1]))
                return
            if path == ["vms"]:
                self._send_json(200, {"vms": self.server.store.list_vms()})
                return
            if len(path) == 2 and path[0] == "vms":
                self._send_json(200, {"host_id": path[1], "vms": self.server.store.list_vms(path[1])})
                return
            if path == ["commands"]:
                query = parse_qs(urlparse(self.path).query)

                def first(key: str) -> str | None:
                    values = query.get(key) or []
                    return values[0] if values else None

                self._send_json(
                    200,
                    {
                        "commands": self.server.store.list_commands(
                            target_host_id=first("target_host_id"),
                            status=first("status"),
                            command_type=first("command_type"),
                            limit=first("limit") or 100,
                        )
                    },
                )
                return
            if len(path) == 3 and path[0] == "commands" and path[1] == "id":
                self._send_json(200, self.server.store.get_command(path[2]))
                return
            if len(path) == 2 and path[0] == "commands":
                try:
                    self._send_json(200, self.server.store.get_command(path[1]))
                except HyperGeryError:
                    self._send_json(200, {"commands": self.server.store.pending_commands_for_host(path[1])})
                return
            if path == ["migrations"]:
                self._send_json(200, {"migrations": self.server.store.list_migrations()})
                return
            if len(path) == 2 and path[0] == "migrations":
                self._send_json(200, self.server.store.get_migration(path[1]))
                return
            if path == ["events"]:
                query = urlparse(self.path).query
                limit = 100
                if query.startswith("limit="):
                    try:
                        limit = int(query.partition("=")[2])
                    except ValueError:
                        limit = 100
                self._send_json(200, {"events": self.server.store.list_events(limit)})
                return
            self._send_error(404, "not found")
        except HyperGeryError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticate():
            return
        try:
            path = [part for part in urlparse(self.path).path.split("/") if part]
            body = _read_json(self)
            if path == ["hosts", "register"]:
                self._send_json(200, self.server.store.register_host(body))
                return
            if path == ["hosts", "heartbeat"]:
                self._send_json(200, self.server.store.heartbeat(body))
                return
            if path == ["vms", "report"]:
                self._send_json(200, self.server.store.report_vms(body))
                return
            if path == ["commands"]:
                self._send_json(201, self.server.store.create_command(body))
                return
            if path == ["migrations"]:
                self._send_json(201, self.server.store.create_migration(body))
                return
            if len(path) == 3 and path[0] == "commands" and path[2] == "result":
                self._send_json(200, self.server.store.set_command_result(path[1], body))
                return
            if len(path) == 3 and path[0] == "migrations" and path[2] == "status":
                self._send_json(200, self.server.store.update_migration_status(path[1], body))
                return
            if path == ["events"]:
                self._send_json(201, self.server.store.create_event(body))
                return
            if path == ["packages", "cleanup"]:
                self._send_json(
                    200,
                    cleanup_staged_packages(
                        self.server.staging_dir,
                        self.server.store,
                        older_than_hours=body.get("older_than_hours", 24.0),
                        dry_run=bool(body.get("dry_run", True)),
                        include_failed=bool(body.get("include_failed", False)),
                        include_orphans=bool(body.get("include_orphans", True)),
                    ),
                )
                return
            self._send_error(404, "not found")
        except HyperGeryError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))


def serve_registry(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    db_path: str | Path | None = None,
    offline_timeout_seconds: int = 90,
    staging_dir: str | Path | None = None,
    max_upload_bytes: int | None = None,
    auth_token: str | None = None,
) -> None:
    store = RegistryStore(db_path, offline_timeout_seconds=offline_timeout_seconds)
    server = RegistryServer(
        (host, port),
        store,
        staging_dir=staging_dir,
        max_upload_bytes=max_upload_bytes,
        auth_token=auth_token,
    )
    if server.auth_token:
        token_path = Path(store.db_path).expanduser().parent / "hub_token"
        logging.info("Hub auth enabled (token from %s)", "env" if os.environ.get("HYPERGERY_HUB_TOKEN") else token_path)
    try:
        server.serve_forever()
    finally:
        server.server_close()
