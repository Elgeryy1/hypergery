from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..backend import HyperGeryError
from .store import RegistryStore


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
    def __init__(self, server_address: tuple[str, int], store: RegistryStore) -> None:
        super().__init__(server_address, RegistryRequestHandler)
        self.store = store


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

    def do_GET(self) -> None:  # noqa: N802
        try:
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
            if path == ["commands"]:
                self._send_json(201, self.server.store.create_command(body))
                return
            if len(path) == 3 and path[0] == "commands" and path[2] == "result":
                self._send_json(200, self.server.store.set_command_result(path[1], body))
                return
            if len(path) == 3 and path[0] == "migrations" and path[2] == "status":
                self._send_json(200, self.server.store.update_migration_status(path[1], body))
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
) -> None:
    store = RegistryStore(db_path, offline_timeout_seconds=offline_timeout_seconds)
    server = RegistryServer((host, port), store)
    try:
        server.serve_forever()
    finally:
        server.server_close()
