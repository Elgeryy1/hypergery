from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hglog import get_logger, now_iso, xdg_state_home
from .settings import V1Settings

try:  # pragma: no cover - psutil presence depends on the environment
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


@dataclass
class TelemetrySample:
    timestamp: str = ""
    host_id: str = ""
    cpu_percent: float = 0.0
    ram_total_mib: int = 0
    ram_free_mib: int = 0
    ram_used_mib: int = 0
    disk_total_mib: int = 0
    disk_free_mib: int = 0
    disk_used_mib: int = 0
    battery_percent: int | None = None
    battery_status: str = "unavailable"
    uptime_seconds: int = 0
    network_interfaces: list[str] = field(default_factory=list)
    source: str = "local"
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Low-level readers (psutil when available, /proc + /sys fallback otherwise). #
# --------------------------------------------------------------------------- #


def read_cpu_percent() -> float:
    if psutil is not None:
        try:
            return float(psutil.cpu_percent(interval=0.1))
        except Exception:
            pass
    try:
        def snapshot() -> tuple[int, int]:
            parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
            values = [int(item) for item in parts]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return sum(values), idle

        total_a, idle_a = snapshot()
        time.sleep(0.1)
        total_b, idle_b = snapshot()
        delta_total = max(1, total_b - total_a)
        return round(100.0 * (1 - (idle_b - idle_a) / delta_total), 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def read_memory_mib() -> tuple[int, int]:
    """(total_mib, available_mib) best effort."""
    if psutil is not None:
        try:
            memory = psutil.virtual_memory()
            return memory.total // (1024 * 1024), memory.available // (1024 * 1024)
        except Exception:
            pass
    total = available = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            value = int(rest.strip().split()[0]) if rest.strip() else 0
            if key == "MemTotal":
                total = value // 1024
            elif key == "MemAvailable":
                available = value // 1024
    except (OSError, ValueError):
        return 0, 0
    return total, available


def read_disk_mib(path: str | Path = "/") -> tuple[int, int]:
    """(total_mib, free_mib) for the filesystem containing `path`."""
    try:
        usage = shutil.disk_usage(Path(path).expanduser())
        return usage.total // (1024 * 1024), usage.free // (1024 * 1024)
    except OSError:
        return 0, 0


def read_uptime_seconds() -> int:
    try:
        return int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def read_network_interfaces() -> list[str]:
    try:
        return sorted(
            entry for entry in os.listdir("/sys/class/net") if entry != "lo"
        )
    except OSError:
        if psutil is not None:
            try:
                return sorted(name for name in psutil.net_if_addrs() if name != "lo")
            except Exception:
                return []
        return []


def read_battery(power_supply_dir: str | Path = "/sys/class/power_supply") -> tuple[int | None, str]:
    """(percent, status) from sysfs; (None, 'unavailable') without a battery."""
    base = Path(power_supply_dir)
    try:
        entries = sorted(base.iterdir()) if base.is_dir() else []
    except OSError:
        entries = []
    for entry in entries:
        capacity = entry / "capacity"
        if not capacity.is_file():
            continue
        try:
            percent = int(capacity.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        status = "unknown"
        status_file = entry / "status"
        if status_file.is_file():
            try:
                status = status_file.read_text(encoding="utf-8").strip().lower().replace(" ", "_")
            except OSError:
                status = "unknown"
        return max(0, min(100, percent)), status
    if psutil is not None:  # pragma: no cover - depends on hardware
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                return int(battery.percent), "charging" if battery.power_plugged else "discharging"
        except Exception:
            pass
    return None, "unavailable"


# --------------------------------------------------------------------------- #
# Service                                                                      #
# --------------------------------------------------------------------------- #


def default_history_path() -> Path:
    return xdg_state_home() / "hypergery" / "telemetry" / "history.json"


class TelemetryService:
    """Local sampling, per-host history, remote (Hub) samples, and alerts."""

    def __init__(
        self,
        *,
        settings: V1Settings | None = None,
        history_path: str | Path | None = None,
        host_id: str = "",
        power_supply_dir: str | Path = "/sys/class/power_supply",
        disk_path: str | Path = "/",
    ) -> None:
        self.settings = settings or V1Settings()
        self.history_path = Path(history_path).expanduser() if history_path else default_history_path()
        self.power_supply_dir = power_supply_dir
        self.disk_path = disk_path
        if not host_id:
            from ..config import effective_value

            host_id = effective_value("host_id")
        self.host_id = host_id

    def sample_local(self) -> TelemetrySample:
        ram_total, ram_free = read_memory_mib()
        disk_total, disk_free = read_disk_mib(self.disk_path)
        battery_percent, battery_status = read_battery(self.power_supply_dir)
        return TelemetrySample(
            timestamp=now_iso(),
            host_id=self.host_id,
            cpu_percent=read_cpu_percent(),
            ram_total_mib=ram_total,
            ram_free_mib=ram_free,
            ram_used_mib=max(0, ram_total - ram_free),
            disk_total_mib=disk_total,
            disk_free_mib=disk_free,
            disk_used_mib=max(0, disk_total - disk_free),
            battery_percent=battery_percent,
            battery_status=battery_status,
            uptime_seconds=read_uptime_seconds(),
            network_interfaces=read_network_interfaces(),
            source="local",
        )

    def remote_sample(self, hub_host: dict[str, Any]) -> TelemetrySample:
        """Build a sample from a Hub host record, flagging stale data."""
        last_seen = str(hub_host.get("last_seen") or "")
        stale = True
        if last_seen:
            try:
                seen = datetime.fromisoformat(last_seen)
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=UTC)
                stale = (datetime.now(UTC) - seen).total_seconds() > self.settings.telemetry_stale_seconds
            except ValueError:
                stale = True
        return TelemetrySample(
            timestamp=last_seen or now_iso(),
            host_id=str(hub_host.get("host_id") or ""),
            ram_total_mib=int(hub_host.get("ram_total_mib") or 0),
            ram_free_mib=int(hub_host.get("ram_free_mib") or 0),
            ram_used_mib=max(0, int(hub_host.get("ram_total_mib") or 0) - int(hub_host.get("ram_free_mib") or 0)),
            disk_free_mib=int(hub_host.get("disk_free_mib") or 0),
            source="hub",
            stale=stale or str(hub_host.get("status") or "") != "online",
        )

    # History ---------------------------------------------------------------- #

    def _read_history(self) -> dict[str, list[dict[str, Any]]]:
        if not self.history_path.exists():
            return {}
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def record(self, sample: TelemetrySample) -> None:
        history = self._read_history()
        per_host = history.setdefault(sample.host_id or "unknown", [])
        per_host.append(sample.to_dict())
        del per_host[: max(0, len(per_host) - self.settings.telemetry_history_samples)]
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            get_logger().warning("telemetry", f"Cannot persist telemetry history at {self.history_path}")

    def history(self, host_id: str | None = None) -> list[dict[str, Any]]:
        history = self._read_history()
        if host_id:
            return list(history.get(host_id, []))
        merged: list[dict[str, Any]] = []
        for samples in history.values():
            merged.extend(samples)
        return sorted(merged, key=lambda item: str(item.get("timestamp", "")))


# --------------------------------------------------------------------------- #
# Alerts                                                                       #
# --------------------------------------------------------------------------- #


def evaluate_alerts(
    *,
    local_sample: TelemetrySample | None = None,
    hub_hosts: list[dict[str, Any]] | None = None,
    nas_path: str | Path | None = None,
    settings: V1Settings | None = None,
) -> list[dict[str, str]]:
    """Minimum alert set: RAM low, battery low, host offline, NAS offline,
    disk low, agent stale. Pure function — easy to test and reuse in UI/API."""
    cfg = settings or V1Settings()
    alerts: list[dict[str, str]] = []

    def alert(severity: str, kind: str, host: str, message: str) -> None:
        alerts.append({"severity": severity, "kind": kind, "host": host, "message": message})

    if local_sample is not None:
        host = local_sample.host_id or "local"
        if local_sample.ram_total_mib and local_sample.ram_free_mib < cfg.ram_low_threshold_mib:
            alert("warning", "ram_low", host, f"Low RAM: {local_sample.ram_free_mib} MiB free (< {cfg.ram_low_threshold_mib}).")
        if local_sample.disk_total_mib and local_sample.disk_free_mib < cfg.disk_low_threshold_mib:
            alert("warning", "disk_low", host, f"Low disk: {local_sample.disk_free_mib} MiB free (< {cfg.disk_low_threshold_mib}).")
        if local_sample.battery_percent is not None and local_sample.battery_status not in {"charging", "full"}:
            percent = local_sample.battery_percent
            if percent <= cfg.battery_critical_percent:
                alert("error", "battery_critical", host, f"Battery CRITICAL: {percent}%.")
            elif percent <= cfg.battery_emergency_percent:
                alert("error", "battery_emergency", host, f"Battery emergency: {percent}%.")
            elif percent <= cfg.battery_offload_percent:
                alert("warning", "battery_low", host, f"Battery low: {percent}% — offload recommended.")
            elif percent <= cfg.battery_eco_percent:
                alert("info", "battery_eco", host, f"Battery at {percent}% — eco mode recommended.")
    for hub_host in hub_hosts or []:
        host_id = str(hub_host.get("host_id") or "?")
        if str(hub_host.get("status") or "offline") != "online":
            alert("warning", "host_offline", host_id, f"Host {host_id} is offline (agent not responding).")
    if nas_path is not None:
        path = Path(nas_path).expanduser()
        if not path.is_dir() or not os.access(path, os.W_OK):
            alert("error", "nas_offline", str(nas_path), f"NAS path not available or not writable: {path}.")
    return alerts
