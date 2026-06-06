from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .battery import BatteryState
from .errors import OrchestratorError
from .hglog import get_logger, new_operation_id, now_iso
from .hosts import HostInfo
from .providers import VmInfo
from .settings import V1Settings

VM_WEIGHTS = ("light", "medium", "heavy", "critical")


def classify_vm_weight(vm: VmInfo, *, critical_tags: Iterable[str] = ("critical",)) -> str:
    """light <= 2 GiB, medium <= 4 GiB, heavy > 4 GiB; 'critical' via notes tag."""
    notes = (vm.notes or "").lower()
    if any(tag in notes for tag in critical_tags):
        return "critical"
    if vm.ram_mb <= 2048:
        return "light"
    if vm.ram_mb <= 4096:
        return "medium"
    return "heavy"


@dataclass
class PlacementPlan:
    lab_id: str
    vm_id: str
    current_host: str
    target_host: str
    reason: str
    confidence: float
    actions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    weight: str = "light"

    @property
    def is_move(self) -> bool:
        return self.current_host != self.target_host

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_move"] = self.is_move
        return data


class OrchestratorService:
    """Auto-Boost decision engine: explainable VM placement plans.

    Pure with respect to its inputs — hosts, VMs, and battery state are
    passed in, so it is fully testable and works the same against real,
    Hub, or simulated providers. It never executes anything: it returns
    plans; teleport/UI decide whether to apply them.
    """

    def __init__(self, *, settings: V1Settings | None = None) -> None:
        self.settings = settings or V1Settings()

    # Internal helpers --------------------------------------------------------- #

    def _eligible_hosts(self, hosts: list[HostInfo], *, allow_remote: bool, local_id: str) -> list[HostInfo]:
        eligible = []
        for host in hosts:
            if host.status != "online":
                continue
            if not host.has_capability("can_run_vms"):
                continue
            if self.settings.offline_mode and host.id != local_id:
                continue
            if not allow_remote and host.id != local_id:
                continue
            eligible.append(host)
        return eligible

    def _headroom_ok(self, host: HostInfo, vm: VmInfo, *, current_host_id: str = "") -> bool:
        if not host.ram_total_mib:
            # Unknown RAM (e.g. loopback/external minimal record): assume ok.
            return True
        # A VM already running/paused on this host is fine staying there: its
        # RAM is already reflected in the host's free figure, so don't subtract
        # it again (that would falsely reject a perfectly healthy placement).
        if host.id == current_host_id and str(vm.status).lower() in {"running", "paused"}:
            return host.ram_free_mib >= 0
        return host.ram_free_mib - vm.ram_mb >= self.settings.ram_low_threshold_mib

    # Planning ------------------------------------------------------------------#

    def plan(
        self,
        *,
        hosts: list[HostInfo],
        vms: list[VmInfo],
        battery: BatteryState | None = None,
        local_host_id: str | None = None,
        allow_remote: bool = True,
        lab_id: str | None = None,
    ) -> list[PlacementPlan]:
        """One explainable PlacementPlan per VM (filtered by lab_id if given)."""
        if not hosts:
            raise OrchestratorError("Cannot plan without any host information.")
        local_id = local_host_id or hosts[0].id
        host_by_id = {host.id: host for host in hosts}
        eligible = self._eligible_hosts(hosts, allow_remote=allow_remote, local_id=local_id)
        operation_id = new_operation_id("orchestrator")
        battery_tier = battery.tier if battery is not None and battery.available and not battery.charging else "normal"
        battery_percent = battery.percent if battery is not None else None
        plans: list[PlacementPlan] = []

        for vm in vms:
            if lab_id and vm.lab_id != lab_id:
                continue
            weight = classify_vm_weight(vm)
            current = vm.host_id or local_id
            current_host = host_by_id.get(current)
            warnings: list[str] = []
            data_points = [f"weight={weight}", f"state={vm.status}", f"battery_tier={battery_tier}"]
            if battery_percent is not None:
                data_points.append(f"battery={battery_percent}%")

            def finish(target: str, reason: str, confidence: float) -> None:
                actions: list[dict[str, Any]] = []
                if target != current:
                    actions.append(
                        {
                            "kind": "teleport",
                            "vm_id": vm.id,
                            "from_host": current,
                            "to_host": target,
                            "mode": self.settings.teleport_default_mode,
                        }
                    )
                else:
                    actions.append({"kind": "stay", "vm_id": vm.id, "host": current})
                plans.append(
                    PlacementPlan(
                        lab_id=vm.lab_id,
                        vm_id=vm.id,
                        current_host=current,
                        target_host=target,
                        reason=f"{reason} [data: {', '.join(data_points)}; fallback: keep on {current}]",
                        confidence=round(confidence, 2),
                        actions=actions,
                        warnings=warnings,
                        weight=weight,
                    )
                )

            # Rule: critical VMs are never moved automatically.
            if weight == "critical":
                warnings.append("VM is tagged critical — automatic moves are disabled for it.")
                finish(current, f"{vm.id} is critical; it stays on {current} until moved manually.", 0.95)
                continue

            # Rule: current host offline → must find a new home.
            if current_host is not None and current_host.status != "online":
                warnings.append(f"Current host {current} is offline.")

            candidates = [host for host in eligible if self._headroom_ok(host, vm, current_host_id=current)]
            if not candidates:
                warnings.append("No eligible host has enough free RAM; keeping current placement.")
                finish(current, f"No host can take {vm.id} right now (RAM headroom < {self.settings.ram_low_threshold_mib} MiB).", 0.4)
                continue

            local = host_by_id.get(local_id)
            local_ok = local is not None and local in candidates
            remote_candidates = [host for host in candidates if host.id != local_id]
            home_pcs = [host for host in remote_candidates if host.role == "home_pc"]

            target: HostInfo | None = None
            reason = ""
            confidence = 0.6

            if self.settings.offline_mode or not allow_remote:
                if local_ok:
                    target, reason, confidence = local, f"{'Offline mode' if self.settings.offline_mode else 'Remote compute not allowed for this user'}: {vm.id} runs locally on {local_id}.", 0.8
                    if not allow_remote and not self.settings.offline_mode:
                        warnings.append("Remote compute denied by role permissions.")
                else:
                    warnings.append("Local host cannot take this VM and remote use is not allowed.")
                    finish(current, f"{vm.id} cannot be placed: local host lacks headroom and remote compute is unavailable.", 0.3)
                    continue
            elif battery_tier in {"offload", "emergency", "critical"} and current == local_id and weight in {"medium", "heavy"}:
                if remote_candidates:
                    target = home_pcs[0] if home_pcs else remote_candidates[0]
                    reason = (
                        f"{vm.id} moved to {target.id} because the laptop battery is at "
                        f"{battery_percent}% (tier {battery_tier}) and the VM is {weight} "
                        f"({vm.ram_mb} MB). {target.id} has {target.ram_free_mib} MiB free."
                    )
                    confidence = 0.85 if battery_tier != "critical" else 0.9
                else:
                    warnings.append("Battery is low but no remote host is available.")
                    target, reason, confidence = (local if local_ok else None), f"{vm.id} stays on {current}: battery low but no remote candidate.", 0.45
            elif weight == "light":
                target = local if local_ok else (home_pcs[0] if home_pcs else candidates[0])
                where = "locally" if target is local else f"on {target.id}"
                reason = f"{vm.id} is light ({vm.ram_mb} MB); it runs {where} with minimal cost."
                confidence = 0.8 if target is local else 0.6
            elif weight == "heavy" and home_pcs:
                target = home_pcs[0]
                reason = (
                    f"{vm.id} is heavy ({vm.ram_mb} MB); {target.id} (home_pc) has "
                    f"{target.ram_free_mib} MiB free and handles it better than the laptop."
                )
                confidence = 0.8
            else:
                # Medium VMs (or heavy without a home_pc): prefer where it is,
                # else the roomiest candidate.
                if current_host in candidates:
                    target = current_host
                    reason = f"{vm.id} stays on {current}: the host is online with enough headroom."
                    confidence = 0.75
                else:
                    target = max(candidates, key=lambda host: host.ram_free_mib)
                    reason = f"{vm.id} moves to {target.id}: current host unavailable; it has the most free RAM ({target.ram_free_mib} MiB)."
                    confidence = 0.65

            if target is None:
                continue
            finish(target.id, reason, confidence)

        get_logger().info(
            "orchestrator",
            f"Placement plan generated for {len(plans)} VM(s)",
            operation_id=operation_id,
            details={
                "moves": sum(1 for plan in plans if plan.is_move),
                "battery_tier": battery_tier,
                "generated_at": now_iso(),
            },
        )
        return plans
