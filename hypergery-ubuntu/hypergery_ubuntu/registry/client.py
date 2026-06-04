from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..backend import HyperGeryError


class RegistryClient:
    def __init__(self, base_url: str, *, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = self.base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HyperGeryError(f"Registry request failed: {url}: HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError) as exc:
            raise HyperGeryError(f"Registry request failed: {url}: {exc}") from exc
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise HyperGeryError(f"Registry returned invalid JSON from {url}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health")

    def register_host(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/hosts/register", payload)

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/hosts/heartbeat", payload)

    def list_hosts(self) -> list[dict[str, Any]]:
        return self.request("GET", "/hosts").get("hosts", [])

    def get_host(self, host_id: str) -> dict[str, Any]:
        return self.request("GET", f"/hosts/{host_id}")

    def create_command(self, target_host_id: str, command_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            "POST",
            "/commands",
            {"target_host_id": target_host_id, "command_type": command_type, "payload": payload or {}},
        )

    def pending_commands(self, host_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/commands/{host_id}").get("commands", [])

    def command(self, command_id: str) -> dict[str, Any]:
        return self.request("GET", f"/commands/{command_id}")

    def set_command_result(self, command_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/commands/{command_id}/result", {"status": status, "result": result})

    def list_migrations(self) -> list[dict[str, Any]]:
        return self.request("GET", "/migrations").get("migrations", [])

    def migration(self, migration_id: str) -> dict[str, Any]:
        return self.request("GET", f"/migrations/{migration_id}")

    def update_migration_status(self, migration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/migrations/{migration_id}/status", payload)
