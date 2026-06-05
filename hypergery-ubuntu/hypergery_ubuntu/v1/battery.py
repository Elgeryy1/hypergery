from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import BatteryUnavailableError
from .hglog import get_logger, now_iso
from .settings import V1Settings
from .telemetry import read_battery

# Battery tiers from highest to lowest charge.
TIERS = ("normal", "eco", "offload", "emergency", "critical")

CHARGING_STATUSES = {"charging", "full"}


@dataclass
class BatteryState:
    available: bool = False
    percent: int | None = None
    status: str = "unavailable"
    charging: bool = False
    tier: str = "normal"
    timestamp: str = ""
    thresholds: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BatteryService:
    """Reads the real battery (sysfs/psutil) and turns it into tiers,
    events, and recommended actions according to the configured mode.

    The service never executes anything itself: it returns action
    descriptors; executing them is the caller's job (orchestrator/UI),
    and only `auto_execute_safe` marks safe actions as executable.
    """

    def __init__(
        self,
        *,
        settings: V1Settings | None = None,
        power_supply_dir: str = "/sys/class/power_supply",
        host_id: str = "",
    ) -> None:
        self.settings = settings or V1Settings()
        self.power_supply_dir = power_supply_dir
        self.host_id = host_id

    def thresholds(self) -> dict[str, int]:
        return {
            "eco": self.settings.battery_eco_percent,
            "offload": self.settings.battery_offload_percent,
            "emergency": self.settings.battery_emergency_percent,
            "critical": self.settings.battery_critical_percent,
        }

    def tier_for(self, percent: int | None, *, charging: bool = False) -> str:
        if percent is None or charging:
            return "normal"
        levels = self.thresholds()
        if percent <= levels["critical"]:
            return "critical"
        if percent <= levels["emergency"]:
            return "emergency"
        if percent <= levels["offload"]:
            return "offload"
        if percent <= levels["eco"]:
            return "eco"
        return "normal"

    def read(self) -> BatteryState:
        percent, status = read_battery(self.power_supply_dir)
        charging = status in CHARGING_STATUSES
        return BatteryState(
            available=percent is not None,
            percent=percent,
            status=status,
            charging=charging,
            tier=self.tier_for(percent, charging=charging),
            timestamp=now_iso(),
            thresholds=self.thresholds(),
        )

    def require(self) -> BatteryState:
        state = self.read()
        if not state.available:
            raise BatteryUnavailableError(
                "No battery information available on this host (no sysfs battery, no psutil sensor)."
            )
        return state

    def events(self, previous: BatteryState | None, current: BatteryState) -> list[dict[str, Any]]:
        """Tier-transition events (for logs/alerts). Empty when unchanged."""
        events: list[dict[str, Any]] = []
        previous_tier = previous.tier if previous is not None else "normal"
        if previous_tier == current.tier:
            return events
        direction = "worsened" if TIERS.index(current.tier) > TIERS.index(previous_tier) else "improved"
        event = {
            "kind": f"battery_{current.tier}",
            "tier": current.tier,
            "previous_tier": previous_tier,
            "direction": direction,
            "percent": current.percent,
            "timestamp": current.timestamp,
        }
        events.append(event)
        get_logger().log(
            "warning" if direction == "worsened" and current.tier in {"offload", "emergency", "critical"} else "info",
            "battery",
            f"Battery tier {previous_tier} → {current.tier} ({current.percent}%)",
            host=self.host_id,
            details=event,
        )
        return events

    def recommended_actions(self, state: BatteryState | None = None) -> list[dict[str, Any]]:
        """Actions for the current tier, shaped by settings.battery_mode.

        Action descriptor: {kind, reason, prepared, execute}. `execute` is
        only ever True in auto_execute_safe mode and only for actions that
        cannot lose data (reducing refresh; teleports/commits stay prepared).
        """
        mode = self.settings.battery_mode
        if mode == "disabled":
            return []
        if state is None:
            state = self.read()
        if not state.available or state.charging:
            return []
        actions: list[dict[str, Any]] = []

        def action(kind: str, reason: str, *, safe: bool = False) -> None:
            actions.append(
                {
                    "kind": kind,
                    "reason": reason,
                    "prepared": mode in {"auto_prepare", "auto_execute_safe"},
                    "execute": bool(safe and mode == "auto_execute_safe"),
                }
            )

        percent = state.percent
        if state.tier in {"eco", "offload", "emergency", "critical"}:
            action("reduce_refresh", f"Battery at {percent}% — lower UI/telemetry refresh rates.", safe=True)
        if state.tier in {"offload", "emergency", "critical"}:
            action("recommend_stop_heavy_vms", f"Battery at {percent}% — consider stopping heavy VMs.")
            action("prepare_teleport", f"Battery at {percent}% — prepare teleport of running VMs to a powered host.")
        if state.tier in {"emergency", "critical"}:
            action("nas_commit", f"Battery at {percent}% — commit lab state to the NAS while possible.")
        if state.tier == "critical":
            action("emergency_shutdown_recommended", f"Battery CRITICAL at {percent}% — plug in or shut down workloads now.")
        return actions
