from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..backend import HyperGeryError

TRANSFER_CHUNK_BYTES = 1024 * 1024
TRANSFER_TIMEOUT_SECONDS = 600

# UI/CLI-facing action names → Hub command types. Only safe power actions;
# delete/undefine/console are intentionally not remote-controllable.
VM_POWER_ACTIONS = {
    "start": "vm_start",
    "shutdown": "vm_shutdown",
    "force_off": "vm_force_off",
}


def default_hub_url() -> str:
    from ..config import effective_value

    return effective_value("hub_url")


class RegistryClient:
    def __init__(self, base_url: str | None = None, *, timeout: int = 10) -> None:
        self.base_url = (base_url or default_hub_url()).rstrip("/")
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

    def report_vms(self, host_id: str, vms: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request("POST", "/vms/report", {"host_id": host_id, "vms": vms})

    def list_vms(self, host_id: str | None = None) -> list[dict[str, Any]]:
        path = f"/vms/{host_id}" if host_id else "/vms"
        return self.request("GET", path).get("vms", [])

    def create_command(self, target_host_id: str, command_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            "POST",
            "/commands",
            {"target_host_id": target_host_id, "command_type": command_type, "payload": payload or {}},
        )

    def pending_commands(self, host_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/commands/{host_id}").get("commands", [])

    def command(self, command_id: str) -> dict[str, Any]:
        return self.request("GET", f"/commands/id/{command_id}")

    def queue_vm_power_command(self, host_id: str, vm_name: str, action: str) -> dict[str, Any]:
        command_type = VM_POWER_ACTIONS.get(action)
        if command_type is None:
            allowed = ", ".join(sorted(VM_POWER_ACTIONS))
            raise HyperGeryError(f"Unsupported remote power action: {action}. Allowed: {allowed}.")
        if not str(vm_name or "").strip():
            raise HyperGeryError("vm_name is required for remote power commands.")
        if not str(host_id or "").strip():
            raise HyperGeryError("host_id is required for remote power commands.")
        return self.create_command(host_id, command_type, {"vm_name": str(vm_name).strip()})

    def start_remote_vm(self, host_id: str, vm_name: str) -> dict[str, Any]:
        return self.queue_vm_power_command(host_id, vm_name, "start")

    def shutdown_remote_vm(self, host_id: str, vm_name: str) -> dict[str, Any]:
        return self.queue_vm_power_command(host_id, vm_name, "shutdown")

    def force_off_remote_vm(self, host_id: str, vm_name: str) -> dict[str, Any]:
        return self.queue_vm_power_command(host_id, vm_name, "force_off")

    def set_command_result(self, command_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/commands/{command_id}/result", {"status": status, "result": result})

    def list_migrations(self) -> list[dict[str, Any]]:
        return self.request("GET", "/migrations").get("migrations", [])

    def create_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/migrations", payload)

    def migration(self, migration_id: str) -> dict[str, Any]:
        return self.request("GET", f"/migrations/{migration_id}")

    def update_migration_status(self, migration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/migrations/{migration_id}/status", payload)

    def list_events(self) -> list[dict[str, Any]]:
        return self.request("GET", "/events").get("events", [])

    def create_event(self, kind: str, message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", "/events", {"kind": kind, "message": message, "payload": payload or {}})

    def _package_url(self, migration_id: str, rel_path: str = "") -> str:
        url = f"{self.base_url}/packages/{quote(migration_id, safe='')}"
        if rel_path:
            url += "/" + quote(rel_path)
        return url

    def list_package_files(self, migration_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/packages/{quote(migration_id, safe='')}").get("files", [])

    def upload_package_file(self, migration_id: str, rel_path: str, file_path: str | Path) -> dict[str, Any]:
        source = Path(file_path).expanduser()
        url = self._package_url(migration_id, rel_path)
        size = source.stat().st_size
        with source.open("rb") as handle:
            request = Request(url, data=handle, method="PUT")
            request.add_header("Content-Type", "application/octet-stream")
            request.add_header("Content-Length", str(size))
            try:
                with urlopen(request, timeout=TRANSFER_TIMEOUT_SECONDS) as response:
                    body = response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise HyperGeryError(f"Package upload failed: {url}: HTTP {exc.code}: {detail}") from exc
            except (OSError, URLError) as exc:
                raise HyperGeryError(f"Package upload failed: {url}: {exc}") from exc
        return json.loads(body) if body else {}

    def upload_package(self, migration_id: str, package_dir: str | Path) -> dict[str, Any]:
        package = Path(package_dir).expanduser().resolve()
        if not package.is_dir():
            raise HyperGeryError(f"Package directory not found: {package}")
        uploaded: list[dict[str, Any]] = []
        for item in sorted(package.rglob("*")):
            if not item.is_file():
                continue
            rel_path = str(item.relative_to(package))
            uploaded.append(self.upload_package_file(migration_id, rel_path, item))
        if not uploaded:
            raise HyperGeryError(f"Package directory is empty: {package}")
        return {"migration_id": migration_id, "files": uploaded}

    def download_package_file(self, migration_id: str, rel_path: str, destination: str | Path) -> Path:
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        url = self._package_url(migration_id, rel_path)
        try:
            with urlopen(Request(url), timeout=TRANSFER_TIMEOUT_SECONDS) as response, target.open("wb") as handle:
                shutil.copyfileobj(response, handle, TRANSFER_CHUNK_BYTES)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HyperGeryError(f"Package download failed: {url}: HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError) as exc:
            raise HyperGeryError(f"Package download failed: {url}: {exc}") from exc
        return target

    def download_package(self, migration_id: str, destination_dir: str | Path) -> Path:
        files = self.list_package_files(migration_id)
        if not files:
            raise HyperGeryError(f"Package is not staged on the Hub: {migration_id}")
        destination = Path(destination_dir).expanduser()
        for entry in files:
            rel_path = str(entry.get("path") or "")
            if not rel_path:
                continue
            self.download_package_file(migration_id, rel_path, destination / rel_path)
        return destination

    def delete_package(self, migration_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/packages/{quote(migration_id, safe='')}")
