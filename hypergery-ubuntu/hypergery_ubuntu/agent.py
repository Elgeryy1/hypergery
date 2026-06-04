from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .backend import HyperGeryBackend, HyperGeryError, xdg_data_home
from .registry import ALLOWED_COMMAND_TYPES, RegistryClient


CONFIG_PATH = Path(os.environ.get("HYPERGERY_AGENT_CONFIG", Path.home() / ".config" / "hypergery" / "agent.json"))


@dataclass
class AgentConfig:
    registry_url: str = "http://127.0.0.1:8765"
    host_id: str = socket.gethostname()
    name: str = socket.gethostname()
    nas_staging_path: str = str(Path.home() / "hypergery-nas" / "migrations")
    heartbeat_interval_seconds: int = 15

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AgentConfig":
        config_path = Path(path).expanduser() if path else CONFIG_PATH
        if not config_path.exists():
            return cls()
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Cannot read agent config {config_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise HyperGeryError(f"Agent config must be a JSON object: {config_path}")
        merged = asdict(cls())
        merged.update({key: value for key, value in data.items() if key in merged})
        return cls(**merged)

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_meminfo_mib() -> tuple[int, int]:
    total = 0
    available = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split()[0] if rest.strip() else "0"
            if key == "MemTotal":
                total = int(value) // 1024
            elif key == "MemAvailable":
                available = int(value) // 1024
    except (OSError, ValueError):
        return 0, 0
    return total, available


def read_cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return ""


def disk_free_mib(path: str) -> int:
    candidate = Path(path).expanduser()
    check_path = candidate if candidate.exists() else candidate.parent
    try:
        usage = shutil.disk_usage(check_path)
    except OSError:
        usage = shutil.disk_usage(Path.home())
    return usage.free // (1024 * 1024)


class HyperGeryAgent:
    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        backend: HyperGeryBackend | None = None,
        client: RegistryClient | None = None,
    ) -> None:
        self.config = config or AgentConfig.load()
        self.backend = backend or HyperGeryBackend()
        self.client = client or RegistryClient(self.config.registry_url)

    def staging_roots(self) -> list[Path]:
        configured = Path(self.config.nas_staging_path).expanduser().resolve()
        roots = [configured]
        if configured.name != "migrations":
            roots.append((configured / "migrations").resolve())
        return roots

    def resolve_staged_package(self, package_dir: str) -> Path:
        if not package_dir:
            raise HyperGeryError("package_dir is required.")
        candidate = Path(package_dir).expanduser().resolve()
        roots = self.staging_roots()
        if not any(candidate == root or root in candidate.parents for root in roots):
            allowed = ", ".join(str(root) for root in roots)
            raise HyperGeryError(f"Package path is outside configured NAS staging roots: {candidate}. Allowed: {allowed}")
        return candidate

    def host_payload(self) -> dict[str, Any]:
        ram_total, ram_free = read_meminfo_mib()
        active_vms: list[str] = []
        libvirt_ok = False
        try:
            vms = self.backend.list_vms()
            active_vms = [vm.name for vm in vms if str(vm.state).lower() not in {"shut off", "shutoff"}]
            libvirt_ok = True
        except Exception:
            active_vms = []
            try:
                result = self.backend.virsh(["list", "--all"], check=False, timeout=10)
                libvirt_ok = result.returncode == 0
            except Exception:
                libvirt_ok = False
        kvm = Path("/dev/kvm")
        return {
            "host_id": self.config.host_id,
            "name": self.config.name,
            "hostname": socket.gethostname(),
            "cpu_model": read_cpu_model(),
            "ram_total_mib": ram_total,
            "ram_free_mib": ram_free,
            "disk_free_mib": disk_free_mib(self.config.nas_staging_path),
            "kvm_ok": kvm.exists() and os.access(kvm, os.R_OK | os.W_OK),
            "libvirt_ok": libvirt_ok,
            "hypergery_version": __version__,
            "active_vms": active_vms,
            "notes": "",
        }

    def register(self) -> dict[str, Any]:
        return self.client.register_host(self.host_payload())

    def heartbeat(self) -> dict[str, Any]:
        return self.client.heartbeat(self.host_payload())

    def execute_command(self, command: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        command_type = str(command.get("command_type") or "")
        payload = command.get("payload") or {}
        if command_type not in ALLOWED_COMMAND_TYPES:
            raise HyperGeryError(f"Unsupported command_type: {command_type}")
        if command_type == "ping":
            return "done", {"pong": True, "host_id": self.config.host_id}
        if command_type == "preflight":
            if payload.get("vm_name"):
                from .migration import migration_preflight

                result = migration_preflight(
                    self.backend,
                    str(payload["vm_name"]),
                    target_host=str(payload.get("target_host", "")),
                    target_vm_name=str(payload.get("target_vm_name", "")),
                    nas_path=str(payload.get("nas_path") or self.config.nas_staging_path),
                    allow_paused=bool(payload.get("allow_paused", False)),
                    include_iso=not bool(payload.get("no_iso", False)),
                    include_snapshots=not bool(payload.get("no_snapshots", False)),
                )
                return ("done" if result["ok"] else "failed"), result
            items = [
                {"name": item.name, "status": item.status, "detail": item.detail, "fix": item.fix}
                for item in self.backend.preflight()
            ]
            worst = "done" if not any(item["status"] == "Error" for item in items) else "failed"
            return worst, {"items": items}
        if command_type == "list_vms":
            return "done", {
                "vms": [
                    {
                        "name": vm.name,
                        "state": vm.state,
                        "lab_id": vm.lab_id,
                        "ram_mib": vm.ram_mib,
                        "vcpus": vm.vcpus,
                        "disk_path": vm.disk_path,
                    }
                    for vm in self.backend.list_vms()
                ]
            }
        if command_type == "receive_vm_package":
            from .migration import validate_vm_package

            package = self.resolve_staged_package(str(payload.get("package_dir", "")))
            validation = validate_vm_package(package)
            return ("done" if validation["ok"] else "failed"), {
                "package_dir": str(package),
                "validation": validation,
            }
        if command_type == "import_vm_package":
            from .migration import import_vm_package

            package = self.resolve_staged_package(str(payload.get("package_dir", "")))
            result = import_vm_package(
                self.backend,
                package,
                target_vm_name=str(payload.get("target_vm_name", "")),
                target_lab_id=str(payload.get("target_lab_id", "")),
            )
            return "done", result
        if command_type == "migration_status":
            from .migration import list_migration_packages, validate_vm_package

            if payload.get("package_dir"):
                package = self.resolve_staged_package(str(payload.get("package_dir", "")))
                validation = validate_vm_package(package)
                return "done", {
                    "package_dir": str(package),
                    "status": "package-valid" if validation["ok"] else "package-invalid",
                    "validation": validation,
                }
            migration_id = str(payload.get("migration_id", ""))
            packages = list_migration_packages(self.config.nas_staging_path)
            match = next((item for item in packages if item.get("migration_id") == migration_id), None)
            return "done", {
                "migration_id": migration_id,
                "status": "staged" if match else "unknown",
                "package": match,
            }
        return "failed", {"error": f"Unhandled command_type: {command_type}"}

    def run_once(self) -> dict[str, Any]:
        host = self.heartbeat()
        processed = []
        commands = self.client.pending_commands(self.config.host_id)
        for command in commands:
            command_id = command["command_id"]
            self.client.set_command_result(command_id, "running", {"started": True})
            try:
                status, result = self.execute_command(command)
            except Exception as exc:
                status, result = "failed", {"error": str(exc)}
            processed.append(self.client.set_command_result(command_id, status, result))
        return {"host": host, "processed": processed}

    def run_forever(self) -> None:
        self.register()
        while True:
            self.run_once()
            time.sleep(max(1, int(self.config.heartbeat_interval_seconds)))


def print_json(data: object) -> int:
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypergery-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--config", default="")
    once_p = sub.add_parser("once")
    once_p.add_argument("--config", default="")
    config_p = sub.add_parser("config")
    config_sub = config_p.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show")
    config_show.add_argument("--config", default="")
    args = parser.parse_args(argv)

    try:
        if args.command == "config" and args.config_command == "show":
            path = Path(args.config).expanduser() if args.config else CONFIG_PATH
            return print_json({"path": str(path), "exists": path.exists(), "config": AgentConfig.load(path).to_public_dict()})
        config = AgentConfig.load(args.config or None)
        agent = HyperGeryAgent(config)
        if args.command == "once":
            return print_json(agent.run_once())
        if args.command == "run":
            agent.run_forever()
            return 0
    except HyperGeryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
