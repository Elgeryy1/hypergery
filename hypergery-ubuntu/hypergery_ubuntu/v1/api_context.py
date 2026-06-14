"""Contenedor de servicios del API v1 (extraído de api.py — HG-BUG-0030).

Solo lógica de negocio/inyección de dependencias; nada de HTTP. El servidor
(`v1/api.py`) lo importa y lo re-exporta, así que `from .api import ApiContext`
sigue funcionando igual.
"""

from __future__ import annotations

from typing import Any, Callable

from .battery import BatteryService
from .errors import HyperGeryError
from .external_nodes import ExternalNodeStore
from .hglog import get_logger
from .hosts import HostRegistry
from .nas import NasService
from .orchestrator import OrchestratorService
from .providers import VmInfo
from .rbac import UserStore
from .settings import V1Settings
from .telemetry import TelemetryService, evaluate_alerts
from .teleport import TeleportEngine


class ApiContext:
    """Service container for the Android-ready API.

    Every dependency is injectable for tests; defaults build the real
    services. Heavy/optional dependencies (libvirt backend, Hub client)
    can be None — endpoints degrade with clear errors instead of crashing.
    """

    def __init__(
        self,
        *,
        settings: V1Settings | None = None,
        telemetry: TelemetryService | None = None,
        host_registry: HostRegistry | None = None,
        battery: BatteryService | None = None,
        nas: NasService | None = None,
        lab_store: Any | None = None,
        user_store: UserStore | None = None,
        node_store: ExternalNodeStore | None = None,
        orchestrator: OrchestratorService | None = None,
        teleport_engine: TeleportEngine | None = None,
        local_vms: Callable[[], list[VmInfo]] | None = None,
        hub_client: Any | None = None,
        backend: Any | None = None,
    ) -> None:
        self.backend = backend
        self.settings = settings or V1Settings()
        self.telemetry = telemetry or TelemetryService(settings=self.settings)
        self.host_registry = host_registry or HostRegistry(
            settings=self.settings, telemetry=self.telemetry, hub_client=hub_client
        )
        self.battery = battery or BatteryService(settings=self.settings)
        self.nas = nas
        self.lab_store = lab_store
        self.user_store = user_store or UserStore()
        self.node_store = node_store or ExternalNodeStore()
        self.orchestrator = orchestrator or OrchestratorService(settings=self.settings)
        self.teleport_engine = teleport_engine
        self._local_vms = local_vms
        self.hub_client = hub_client

    # Data accessors ---------------------------------------------------------- #

    def labs(self) -> list[dict[str, Any]]:
        if self.lab_store is None:
            return []
        return self.lab_store.list_labs()

    def vms(self) -> list[VmInfo]:
        vms: list[VmInfo] = []
        if self._local_vms is not None:
            vms.extend(self._local_vms())
        if self.hub_client is not None and not self.settings.offline_mode:
            local_ids = {vm.id for vm in vms}
            try:
                for record in self.hub_client.list_vms():
                    name = str(record.get("vm_name") or "")
                    if not name or name in local_ids:
                        continue
                    vms.append(
                        VmInfo(
                            id=name,
                            ram_mb=int(record.get("ram_mib") or 0),
                            cpu=int(record.get("vcpus") or 0),
                            status=str(record.get("state") or "unknown").lower(),
                            host_id=str(record.get("host_id") or ""),
                            lab_id=str(record.get("lab_id") or ""),
                            network_ids=list(record.get("networks") or []),
                            last_seen=str(record.get("updated_at") or ""),
                        )
                    )
            except Exception as exc:
                get_logger().warning("api", f"Hub VM inventory unavailable: {exc}")
        return vms

    def find_vm(self, vm_id: str) -> VmInfo:
        for vm in self.vms():
            if vm.id == vm_id:
                return vm
        raise HyperGeryError(f"VM not found: {vm_id}")

    def vm_action(self, vm_id: str, action: str, *, snapshot_name: str = "") -> dict[str, Any]:
        """v1.4 API companion: acciones SEGURAS sobre una VM (start / ACPI
        shutdown / snapshot). Nada destructivo: force-off, delete y undefine
        no están expuestos. VMs remotas → cola de comandos del Hub."""
        vm = self.find_vm(vm_id)
        local = False
        if self.backend is not None:
            try:
                self.backend.get_vm(vm_id)
                local = True
            except Exception:
                local = False
        if local:
            if action == "start":
                self.backend.start_vm(vm_id)
            elif action == "shutdown":
                self.backend.shutdown_vm(vm_id)
            elif action == "snapshot":
                self.backend.create_snapshot(vm_id, snapshot_name, "API companion snapshot")
            else:
                raise HyperGeryError(f"Unsupported VM action: {action}")
            return {"vm_id": vm_id, "action": action, "where": "local", "queued": False}
        if action == "snapshot":
            raise HyperGeryError("Snapshots of remote VMs are not supported from the companion API yet.")
        if self.hub_client is None or not vm.host_id:
            raise HyperGeryError(f"VM {vm_id} is not local and no Hub client is configured.")
        command = self.hub_client.queue_vm_power_command(vm.host_id, vm_id, action)
        return {"vm_id": vm_id, "action": action, "where": vm.host_id, "queued": True, "command": command}

    def dashboard(self) -> dict[str, Any]:
        """v1.4 health dashboard: hosts (con telemetría), VMs por estado,
        alertas y batería en una sola respuesta."""
        hosts = [host.to_dict() for host in self.host_registry.list_hosts()]
        sample = self.telemetry.sample_local()
        alerts = evaluate_alerts(
            local_sample=sample,
            hub_hosts=[host for host in hosts if "hub" in host.get("tags", [])],
            nas_path=self.nas.nas_root if self.nas is not None else None,
            settings=self.settings,
        )
        vms = self.vms()
        by_state: dict[str, int] = {}
        for vm in vms:
            by_state[vm.status] = by_state.get(vm.status, 0) + 1
        battery = self.battery.read()
        return {
            "hosts": hosts,
            "local_telemetry": sample.to_dict(),
            "alerts": alerts,
            "vms_total": len(vms),
            "vms_by_state": by_state,
            "battery": battery.to_dict(),
        }

    def orchestrator_plan(self, *, lab_id: str | None = None, allow_remote: bool = True) -> list[dict[str, Any]]:
        hosts = self.host_registry.list_hosts()
        battery = self.battery.read()
        plans = self.orchestrator.plan(
            hosts=hosts,
            vms=self.vms(),
            battery=battery,
            local_host_id=hosts[0].id if hosts else None,
            allow_remote=allow_remote,
            lab_id=lab_id,
        )
        return [plan.to_dict() for plan in plans]
