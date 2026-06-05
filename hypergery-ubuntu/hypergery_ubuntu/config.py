from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .backend import HyperGeryError


CONFIG_FIELDS = {
    "hub_url",
    "host_id",
    "host_name",
    "nas_staging_path",
    "default_display",
    "default_iso_folder",
    "default_vm_storage_path",
}

ENV_KEYS = {
    "hub_url": ("HYPERGERY_HUB_URL", "HYPERGERY_REGISTRY_URL"),
    "host_id": ("HYPERGERY_HOST_ID",),
    "host_name": ("HYPERGERY_HOST_NAME",),
    "nas_staging_path": ("HYPERGERY_NAS_STAGING_PATH",),
    "default_display": ("HYPERGERY_DEFAULT_DISPLAY",),
    "default_iso_folder": ("HYPERGERY_DEFAULT_ISO_FOLDER",),
    "default_vm_storage_path": ("HYPERGERY_DEFAULT_VM_STORAGE_PATH",),
}


def xdg_config_home() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    return Path(override).expanduser() if override else Path.home() / ".config"


def config_path() -> Path:
    override = os.environ.get("HYPERGERY_CONFIG")
    return Path(override).expanduser() if override else xdg_config_home() / "hypergery" / "config.json"


def default_config_values() -> dict[str, str]:
    return {
        # The Hub runs in Container Station on the NAS; point at it directly
        # so fresh installs on any LAN host work without extra configuration.
        "hub_url": "http://192.168.1.150:8765",
        "host_id": socket.gethostname(),
        "host_name": socket.gethostname(),
        "nas_staging_path": str(Path.home() / "hypergery-nas" / "migrations"),
        "default_display": "vnc",
        "default_iso_folder": str(Path.home()),
        "default_vm_storage_path": "",
    }


@dataclass(frozen=True)
class EffectiveValue:
    value: str
    source: str


@dataclass
class HyperGeryConfig:
    hub_url: str = ""
    host_id: str = ""
    host_name: str = ""
    nas_staging_path: str = ""
    default_display: str = ""
    default_iso_folder: str = ""
    default_vm_storage_path: str = ""

    @classmethod
    def load(cls, path: str | Path | None = None) -> "HyperGeryConfig":
        candidate = Path(path).expanduser() if path else config_path()
        if not candidate.exists():
            return cls()
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Cannot read HyperGery config {candidate}: {exc}") from exc
        if not isinstance(data, dict):
            raise HyperGeryError(f"HyperGery config must be a JSON object: {candidate}")
        filtered = {key: str(value) for key, value in data.items() if key in CONFIG_FIELDS and value is not None}
        return cls(**filtered)

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}

    def save(self, path: str | Path | None = None) -> Path:
        candidate = Path(path).expanduser() if path else config_path()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return candidate


def _env_value(field: str) -> EffectiveValue | None:
    for key in ENV_KEYS[field]:
        value = os.environ.get(key)
        if value:
            return EffectiveValue(value, f"env:{key}")
    return None


def effective_config(path: str | Path | None = None) -> dict[str, EffectiveValue]:
    saved = HyperGeryConfig.load(path)
    saved_values = saved.to_dict()
    defaults = default_config_values()
    result: dict[str, EffectiveValue] = {}
    for field in CONFIG_FIELDS:
        env = _env_value(field)
        if env is not None:
            result[field] = env
        elif saved_values.get(field):
            result[field] = EffectiveValue(saved_values[field], "config")
        else:
            result[field] = EffectiveValue(defaults[field], "default")
    display = result["default_display"].value.lower()
    if display not in {"vnc", "spice"}:
        result["default_display"] = EffectiveValue(defaults["default_display"], "default")
    return result


def effective_value(field: str, path: str | Path | None = None) -> str:
    if field not in CONFIG_FIELDS:
        raise KeyError(field)
    return effective_config(path)[field].value
