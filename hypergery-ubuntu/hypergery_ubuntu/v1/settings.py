from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .errors import HyperGeryError

BATTERY_MODES = ("disabled", "recommend_only", "auto_prepare", "auto_execute_safe")
LOG_LEVELS = ("debug", "info", "warning", "error")
TELEPORT_MODES = ("dry_run", "local_loopback", "suspend_copy_start", "experimental_memdiff")

ENV_PREFIX = "HYPERGERY_V1_"


def v1_settings_path() -> Path:
    override = os.environ.get("HYPERGERY_V1_SETTINGS")
    if override:
        return Path(override).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "hypergery" / "v1-settings.json"


@dataclass
class V1Settings:
    """Central v0.9/v1 knobs. Safe defaults: dry-run on, nothing automatic."""

    offline_mode: bool = False
    dry_run_default: bool = True
    # Battery thresholds (percent) — must be strictly decreasing.
    battery_eco_percent: int = 50
    battery_offload_percent: int = 30
    battery_emergency_percent: int = 20
    battery_critical_percent: int = 10
    battery_mode: str = "recommend_only"
    # Resource thresholds.
    ram_low_threshold_mib: int = 1024
    disk_low_threshold_mib: int = 5120
    # Telemetry.
    telemetry_history_samples: int = 60
    telemetry_stale_seconds: int = 180
    # Networking / agents.
    agent_timeout_seconds: int = 10
    # Logging.
    log_level: str = "info"
    # Experimental flags.
    experimental_memdiff: bool = False
    teleport_default_mode: str = "dry_run"
    # Android-ready API service.
    api_host: str = "127.0.0.1"
    api_port: int = 8799

    def validate(self) -> "V1Settings":
        levels = [
            self.battery_eco_percent,
            self.battery_offload_percent,
            self.battery_emergency_percent,
            self.battery_critical_percent,
        ]
        if any(not 0 < level <= 100 for level in levels):
            raise HyperGeryError("Battery thresholds must be percentages between 1 and 100.")
        if sorted(levels, reverse=True) != levels or len(set(levels)) != len(levels):
            raise HyperGeryError(
                "Battery thresholds must be strictly decreasing: eco > offload > emergency > critical."
            )
        if self.battery_mode not in BATTERY_MODES:
            raise HyperGeryError(f"battery_mode must be one of: {', '.join(BATTERY_MODES)}")
        if self.log_level not in LOG_LEVELS:
            raise HyperGeryError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
        if self.teleport_default_mode not in TELEPORT_MODES:
            raise HyperGeryError(f"teleport_default_mode must be one of: {', '.join(TELEPORT_MODES)}")
        if self.ram_low_threshold_mib < 0 or self.disk_low_threshold_mib < 0:
            raise HyperGeryError("Resource thresholds cannot be negative.")
        if not 0 < int(self.api_port) < 65536:
            raise HyperGeryError("api_port must be a valid TCP port.")
        if self.telemetry_history_samples < 1:
            raise HyperGeryError("telemetry_history_samples must be at least 1.")
        return self

    @classmethod
    def _coerce(cls, name: str, kind: type, value: object) -> object:
        if kind is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        try:
            return kind(value)
        except (TypeError, ValueError) as exc:
            raise HyperGeryError(f"Invalid value for v1 setting {name}: {value!r}") from exc

    @classmethod
    def load(cls, path: str | Path | None = None) -> "V1Settings":
        """Load settings: file (if present) then HYPERGERY_V1_* env overrides."""
        candidate = Path(path).expanduser() if path else v1_settings_path()
        data: dict[str, object] = {}
        if candidate.exists():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HyperGeryError(f"Cannot read v1 settings {candidate}: {exc}") from exc
            if not isinstance(raw, dict):
                raise HyperGeryError(f"v1 settings must be a JSON object: {candidate}")
            data.update(raw)
        for field in fields(cls):
            env_value = os.environ.get(ENV_PREFIX + field.name.upper())
            if env_value is not None:
                data[field.name] = env_value
        kwargs = {}
        known = {field.name: field.type for field in fields(cls)}
        defaults = cls()
        for name in known:
            if name in data:
                kwargs[name] = cls._coerce(name, type(getattr(defaults, name)), data[name])
        return cls(**kwargs).validate()

    def save(self, path: str | Path | None = None) -> Path:
        candidate = Path(path).expanduser() if path else v1_settings_path()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return candidate

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
