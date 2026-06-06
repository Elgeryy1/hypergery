from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.request import Request, urlopen

from .errors import HostOfflineError
from .hglog import get_logger, now_iso
from .settings import V1Settings
from .telemetry import TelemetryService

HOST_ROLES = ("laptop", "home_pc", "nas", "isard", "guest", "unknown")

HOST_CAPABILITIES = (
    "can_run_vms",
    "can_store_labs",
    "can_receive_teleport",
    "can_send_teleport",
    "can_report_battery",
    "can_report_network",
    "can_act_as_hub",
    "experimental",
)


@dataclass
class HostInfo:
    id: str
    name: str = ""
    role: str = "unknown"
    address: str = ""
    agent_url: str = ""
    status: str = "unknown"
    last_seen: str = ""
    cpu: str = ""
    ram_total_mib: int = 0
    ram_free_mib: int = 0
    disk_total_mib: int = 0
    disk_free_mib: int = 0
    battery_percent: int | None = None
    battery_status: str = "unavailable"
    network_interfaces: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.role not in HOST_ROLES:
            self.role = "unknown"
        self.capabilities = [item for item in self.capabilities if item in HOST_CAPABILITIES]

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def loopback_host(host_id: str = "loopback") -> HostInfo:
    """In-memory host for tests and dry-runs without any remote machine."""
    return HostInfo(
        id=host_id,
        name="Loopback (testing)",
        role="unknown",
        status="online",
        last_seen=now_iso(),
        ram_total_mib=8192,
        ram_free_mib=8192,
        disk_free_mib=50 * 1024,
        capabilities=["can_run_vms", "can_receive_teleport", "can_send_teleport", "experimental"],
        tags=["loopback", "testing"],
    )


class HostRegistry:
    """Unified host view: local host + Hub-registered hosts (+ loopback).

    Dependencies are injectable so everything works offline and in tests:
    `hub_client` anything with list_hosts(); `telemetry` a TelemetryService.
    """

    def __init__(
        self,
        *,
        settings: V1Settings | None = None,
        hub_client: Any | None = None,
        telemetry: TelemetryService | None = None,
        role_overrides: dict[str, str] | None = None,
        include_loopback: bool = False,
    ) -> None:
        self.settings = settings or V1Settings()
        self._hub_client = hub_client
        self.telemetry = telemetry or TelemetryService(settings=self.settings)
        self.role_overrides = dict(role_overrides or {})
        self.include_loopback = include_loopback

    # Construction ------------------------------------------------------------ #

    def local_host(self) -> HostInfo:
        sample = self.telemetry.sample_local()
        role = self.role_overrides.get(sample.host_id)
        if role is None:
            role = "laptop" if sample.battery_percent is not None else "home_pc"
        capabilities = [
            "can_run_vms",
            "can_store_labs",
            "can_send_teleport",
            "can_receive_teleport",
            "can_report_network",
        ]
        if sample.battery_percent is not None:
            capabilities.append("can_report_battery")
        return HostInfo(
            id=sample.host_id,
            name=sample.host_id,
            role=role,
            status="online",
            last_seen=sample.timestamp,
            ram_total_mib=sample.ram_total_mib,
            ram_free_mib=sample.ram_free_mib,
            disk_total_mib=sample.disk_total_mib,
            disk_free_mib=sample.disk_free_mib,
            battery_percent=sample.battery_percent,
            battery_status=sample.battery_status,
            network_interfaces=sample.network_interfaces,
            capabilities=capabilities,
            tags=["local"],
        )

    def from_hub(self, record: dict[str, Any]) -> HostInfo:
        host_id = str(record.get("host_id") or "")
        capabilities = ["can_run_vms", "can_receive_teleport", "can_send_teleport"]
        if record.get("libvirt_ok") is False:
            capabilities = []
        return HostInfo(
            id=host_id,
            name=str(record.get("name") or record.get("hostname") or host_id),
            role=self.role_overrides.get(host_id, "unknown"),
            address=str(record.get("hostname") or ""),
            status=str(record.get("status") or "unknown"),
            last_seen=str(record.get("last_seen") or ""),
            cpu=str(record.get("cpu_model") or ""),
            ram_total_mib=int(record.get("ram_total_mib") or 0),
            ram_free_mib=int(record.get("ram_free_mib") or 0),
            disk_free_mib=int(record.get("disk_free_mib") or 0),
            capabilities=capabilities,
            tags=["hub"],
        )

    def _hub_hosts(self) -> list[dict[str, Any]]:
        if self.settings.offline_mode or self._hub_client is None:
            return []
        try:
            return list(self._hub_client.list_hosts())
        except Exception as exc:
            get_logger().warning("hosts", f"Hub host listing unavailable: {exc}")
            return []

    def list_hosts(self) -> list[HostInfo]:
        """Local host first, then Hub hosts (excluding the local duplicate)."""
        local = self.local_host()
        hosts = [local]
        for record in self._hub_hosts():
            if str(record.get("host_id") or "") == local.id:
                # Prefer the live local sample but keep Hub status visibility.
                continue
            hosts.append(self.from_hub(record))
        if self.include_loopback:
            hosts.append(loopback_host())
        return hosts

    def get_host(self, host_id: str) -> HostInfo:
        for host in self.list_hosts():
            if host.id == host_id:
                return host
        raise HostOfflineError(f"Host not found in registry: {host_id}")

    # Health ------------------------------------------------------------------ #

    def health_check(self, host: HostInfo) -> dict[str, Any]:
        """Non-destructive health summary for one host."""
        result: dict[str, Any] = {
            "host_id": host.id,
            "status": host.status,
            "reachable": host.status == "online",
            "latency_ms": None,
            "source": "registry",
            "checked_at": now_iso(),
        }
        if "local" in host.tags:
            result.update({"reachable": True, "source": "local"})
            return result
        if self.settings.offline_mode:
            result.update({"source": "offline_mode", "reachable": False, "status": "offline"})
            return result
        if host.agent_url:
            url = host.agent_url.rstrip("/") + "/health"
            started = time.perf_counter()
            try:
                with urlopen(Request(url, method="GET"), timeout=self.settings.agent_timeout_seconds) as response:
                    body = response.read().decode("utf-8", errors="replace")
                result.update(
                    {
                        "reachable": True,
                        "status": "online",
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "source": "agent_http",
                        "body": json.loads(body) if body else {},
                    }
                )
            except Exception as exc:
                result.update({"reachable": False, "status": "offline", "source": "agent_http", "error": str(exc)})
            return result
        return result
