from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import HyperGeryError
from .hglog import get_logger, now_iso


@dataclass
class VmInfo:
    id: str
    name: str = ""
    os_type: str = ""
    cpu: int = 0
    ram_mb: int = 0
    disk_path: str = ""
    status: str = "unknown"
    host_id: str = ""
    lab_id: str = ""
    network_ids: list[str] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    last_seen: str = ""
    boot_order: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VMProvider(ABC):
    """Uniform VM control surface. Implementations: local libvirt, remote
    agent (Hub command queue), and an in-memory simulation for tests and
    dry-runs."""

    @abstractmethod
    def list_vms(self) -> list[VmInfo]: ...

    @abstractmethod
    def get_vm(self, vm_id: str) -> VmInfo: ...

    @abstractmethod
    def start_vm(self, vm_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def stop_vm(self, vm_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def pause_vm(self, vm_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def resume_vm(self, vm_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def snapshot_vm(self, vm_id: str, name: str) -> dict[str, Any]: ...

    @abstractmethod
    def restore_snapshot(self, vm_id: str, snapshot_id: str) -> dict[str, Any]: ...


class LocalProvider(VMProvider):
    """Real local VMs through the existing libvirt backend."""

    def __init__(self, backend: Any, *, host_id: str = "") -> None:
        self.backend = backend
        if not host_id:
            from ..config import effective_value

            host_id = effective_value("host_id")
        self.host_id = host_id

    def _to_info(self, summary: Any) -> VmInfo:
        return VmInfo(
            id=summary.name,
            name=summary.name,
            cpu=summary.vcpus or 0,
            ram_mb=summary.ram_mib or 0,
            disk_path=summary.disk_path or "",
            status=str(summary.state or "unknown").lower(),
            host_id=self.host_id,
            lab_id=summary.lab_id or "",
            network_ids=[summary.network] if getattr(summary, "network", "") else [],
            last_seen=now_iso(),
        )

    def list_vms(self) -> list[VmInfo]:
        return [self._to_info(summary) for summary in self.backend.list_vms()]

    def get_vm(self, vm_id: str) -> VmInfo:
        info = self._to_info(self.backend.get_vm(vm_id))
        try:
            info.snapshots = list(self.backend.list_snapshots(vm_id))
        except Exception:
            info.snapshots = []
        return info

    def _result(self, vm_id: str, action: str) -> dict[str, Any]:
        get_logger().info("vms", f"{action} {vm_id}", module="providers.local", vm_id=vm_id, host=self.host_id)
        return {"vm_id": vm_id, "action": action, "provider": "local", "ok": True}

    def start_vm(self, vm_id: str) -> dict[str, Any]:
        self.backend.start_vm(vm_id)
        return self._result(vm_id, "start")

    def stop_vm(self, vm_id: str) -> dict[str, Any]:
        self.backend.shutdown_vm(vm_id)
        return self._result(vm_id, "stop")

    def pause_vm(self, vm_id: str) -> dict[str, Any]:
        result = self.backend.virsh(["suspend", vm_id], check=False)
        if result.returncode != 0:
            raise HyperGeryError(f"Cannot pause {vm_id}: {result.stderr.strip() or result.stdout.strip()}")
        return self._result(vm_id, "pause")

    def resume_vm(self, vm_id: str) -> dict[str, Any]:
        result = self.backend.virsh(["resume", vm_id], check=False)
        if result.returncode != 0:
            raise HyperGeryError(f"Cannot resume {vm_id}: {result.stderr.strip() or result.stdout.strip()}")
        return self._result(vm_id, "resume")

    def snapshot_vm(self, vm_id: str, name: str) -> dict[str, Any]:
        self.backend.create_snapshot(vm_id, name, "")
        return self._result(vm_id, f"snapshot:{name}")

    def restore_snapshot(self, vm_id: str, snapshot_id: str) -> dict[str, Any]:
        self.backend.revert_snapshot(vm_id, snapshot_id)
        return self._result(vm_id, f"restore:{snapshot_id}")


class AgentProvider(VMProvider):
    """Remote VMs through the Hub command queue (App → Hub → Agent).

    Only the allowlisted remote actions exist; everything else raises clearly
    instead of pretending to work.
    """

    def __init__(self, client: Any, host_id: str) -> None:
        self.client = client
        self.host_id = host_id

    def _to_info(self, record: dict[str, Any]) -> VmInfo:
        return VmInfo(
            id=str(record.get("vm_name") or record.get("name") or ""),
            cpu=int(record.get("vcpus") or 0),
            ram_mb=int(record.get("ram_mib") or 0),
            disk_path=", ".join(record.get("disk_paths") or []),
            status=str(record.get("state") or "unknown").lower(),
            host_id=self.host_id,
            lab_id=str(record.get("lab_id") or ""),
            network_ids=list(record.get("networks") or []),
            last_seen=str(record.get("updated_at") or ""),
        )

    def list_vms(self) -> list[VmInfo]:
        return [self._to_info(record) for record in self.client.list_vms(self.host_id)]

    def get_vm(self, vm_id: str) -> VmInfo:
        for info in self.list_vms():
            if info.id == vm_id:
                return info
        raise HyperGeryError(f"VM not in Hub inventory for {self.host_id}: {vm_id}")

    def _queue(self, vm_id: str, action: str) -> dict[str, Any]:
        command = self.client.queue_vm_power_command(self.host_id, vm_id, action)
        get_logger().info(
            "vms",
            f"queued remote {action} for {vm_id} on {self.host_id}",
            module="providers.agent",
            vm_id=vm_id,
            host=self.host_id,
            details={"command_id": command.get("command_id", "")},
        )
        return {
            "vm_id": vm_id,
            "action": action,
            "provider": "agent",
            "ok": True,
            "queued": True,
            "command_id": str(command.get("command_id") or ""),
        }

    def start_vm(self, vm_id: str) -> dict[str, Any]:
        return self._queue(vm_id, "start")

    def stop_vm(self, vm_id: str) -> dict[str, Any]:
        return self._queue(vm_id, "shutdown")

    def pause_vm(self, vm_id: str) -> dict[str, Any]:
        raise HyperGeryError("Remote pause is not allowlisted — pause is local-only in v1.")

    def resume_vm(self, vm_id: str) -> dict[str, Any]:
        raise HyperGeryError("Remote resume is not allowlisted — resume is local-only in v1.")

    def snapshot_vm(self, vm_id: str, name: str) -> dict[str, Any]:
        raise HyperGeryError("Remote snapshots are not allowlisted — snapshots are local-only in v1.")

    def restore_snapshot(self, vm_id: str, snapshot_id: str) -> dict[str, Any]:
        raise HyperGeryError("Remote snapshot restore is not allowlisted in v1.")


# Allowed state transitions for the simulated provider — mirrors libvirt
# semantics so orchestrator/teleport tests behave realistically.
_SIM_TRANSITIONS = {
    "start": ({"shut off"}, "running"),
    "stop": ({"running", "paused"}, "shut off"),
    "pause": ({"running"}, "paused"),
    "resume": ({"paused"}, "running"),
}


class SimulatedProvider(VMProvider):
    """In-memory VMs with realistic state transitions, for tests/dry-runs."""

    def __init__(self, vms: list[VmInfo] | None = None, *, host_id: str = "sim-host") -> None:
        self.host_id = host_id
        self._vms: dict[str, VmInfo] = {}
        for vm in vms or []:
            vm.host_id = vm.host_id or host_id
            self._vms[vm.id] = vm
        self.actions: list[tuple[str, str]] = []

    def add_vm(self, vm: VmInfo) -> None:
        vm.host_id = vm.host_id or self.host_id
        self._vms[vm.id] = vm

    def list_vms(self) -> list[VmInfo]:
        return sorted(self._vms.values(), key=lambda vm: vm.id)

    def get_vm(self, vm_id: str) -> VmInfo:
        if vm_id not in self._vms:
            raise HyperGeryError(f"Simulated VM does not exist: {vm_id}")
        return self._vms[vm_id]

    def _transition(self, vm_id: str, action: str) -> dict[str, Any]:
        vm = self.get_vm(vm_id)
        allowed, new_state = _SIM_TRANSITIONS[action]
        if vm.status not in allowed:
            raise HyperGeryError(
                f"Cannot {action} {vm_id}: state is '{vm.status}'. Allowed: {', '.join(sorted(allowed))}."
            )
        previous = vm.status
        vm.status = new_state
        vm.last_seen = now_iso()
        self.actions.append((action, vm_id))
        return {
            "vm_id": vm_id,
            "action": action,
            "provider": "simulated",
            "ok": True,
            "previous_state": previous,
            "new_state": new_state,
        }

    def start_vm(self, vm_id: str) -> dict[str, Any]:
        return self._transition(vm_id, "start")

    def stop_vm(self, vm_id: str) -> dict[str, Any]:
        return self._transition(vm_id, "stop")

    def pause_vm(self, vm_id: str) -> dict[str, Any]:
        return self._transition(vm_id, "pause")

    def resume_vm(self, vm_id: str) -> dict[str, Any]:
        return self._transition(vm_id, "resume")

    def snapshot_vm(self, vm_id: str, name: str) -> dict[str, Any]:
        vm = self.get_vm(vm_id)
        if not name.strip():
            raise HyperGeryError("Snapshot name cannot be empty.")
        if name in vm.snapshots:
            raise HyperGeryError(f"Snapshot already exists: {name}")
        vm.snapshots.append(name)
        self.actions.append((f"snapshot:{name}", vm_id))
        return {"vm_id": vm_id, "action": "snapshot", "name": name, "provider": "simulated", "ok": True}

    def restore_snapshot(self, vm_id: str, snapshot_id: str) -> dict[str, Any]:
        vm = self.get_vm(vm_id)
        if snapshot_id not in vm.snapshots:
            raise HyperGeryError(f"Snapshot does not exist: {snapshot_id}")
        self.actions.append((f"restore:{snapshot_id}", vm_id))
        return {"vm_id": vm_id, "action": "restore", "name": snapshot_id, "provider": "simulated", "ok": True}
