from __future__ import annotations

import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..backend import HyperGeryError
from .store import RegistryStore

TRANSFER_CHUNK_BYTES = 1024 * 1024


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
    ) -> None:
        super().__init__(server_address, RegistryRequestHandler)
        self.store = store
        self.staging_dir = Path(staging_dir).expanduser() if staging_dir else default_staging_dir(store.db_path)


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
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0:
            raise HyperGeryError("Package upload requires Content-Length.")
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
        try:
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
) -> None:
    store = RegistryStore(db_path, offline_timeout_seconds=offline_timeout_seconds)
    server = RegistryServer((host, port), store, staging_dir=staging_dir)
    try:
        server.serve_forever()
    finally:
        server.server_close()
