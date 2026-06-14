"""Políticas de backup hacia el NAS (v1.3).

Una política dice: cada N horas, exporta la VM X (paquete completo con
checksums, el mismo formato que la migración offline) a un directorio del
NAS, y conserva las últimas R copias. ``run_due`` está pensado para llamarse
desde cron/systemd-timer o desde la UI; no hay demonio propio.

La poda de copias antiguas SOLO borra directorios de paquete dentro del root
de backups de la política cuyo manifest pertenece a esa VM. Nunca toca VMs,
discos importados ni nada fuera del root.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..backend import HyperGeryError, validate_vm_name, xdg_state_home
from ..migration import PACKAGE_ROOT_NAME, export_vm_package
from .hglog import get_logger, now_iso

POLICIES_FILE = "backup_policies.json"


def _policies_path() -> Path:
    return Path(xdg_state_home()) / POLICIES_FILE


@dataclass
class BackupPolicy:
    id: str
    vm_name: str
    target_dir: str
    interval_hours: float = 24.0
    retention: int = 3
    enabled: bool = True
    include_iso: bool = False
    last_run_at: str = ""
    last_result: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.vm_name = validate_vm_name(self.vm_name)
        if not str(self.target_dir or "").strip():
            raise HyperGeryError("Backup policy requires a target_dir.")
        if float(self.interval_hours) <= 0:
            raise HyperGeryError("interval_hours must be positive.")
        if int(self.retention) < 1:
            raise HyperGeryError("retention must keep at least 1 copy.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_due(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if not self.last_run_at:
            return True
        try:
            last = datetime.fromisoformat(self.last_run_at)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (now or datetime.now(UTC)) - last >= timedelta(hours=float(self.interval_hours))


class BackupPolicyStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _policies_path()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def add(self, policy: BackupPolicy) -> BackupPolicy:
        data = self._load()
        data[policy.id] = policy.to_dict()
        self._save(data)
        return policy

    def remove(self, policy_id: str) -> bool:
        data = self._load()
        existed = policy_id in data
        data.pop(policy_id, None)
        self._save(data)
        return existed

    def get(self, policy_id: str) -> BackupPolicy:
        data = self._load()
        if policy_id not in data:
            raise HyperGeryError(f"Backup policy does not exist: {policy_id}")
        return BackupPolicy(**data[policy_id])

    def list(self) -> list[BackupPolicy]:
        return [BackupPolicy(**entry) for entry in self._load().values()]

    def update(self, policy: BackupPolicy) -> None:
        data = self._load()
        data[policy.id] = policy.to_dict()
        self._save(data)


def new_policy(
    vm_name: str,
    target_dir: str,
    *,
    interval_hours: float = 24.0,
    retention: int = 3,
    include_iso: bool = False,
) -> BackupPolicy:
    return BackupPolicy(
        id=f"bkp-{uuid.uuid4().hex[:10]}",
        vm_name=vm_name,
        target_dir=str(target_dir),
        interval_hours=interval_hours,
        retention=retention,
        include_iso=include_iso,
    )


def list_policy_backups(policy: BackupPolicy) -> list[Path]:
    """Directorios de paquete de ESTA VM bajo el root de la política, de más
    reciente a más antiguo."""
    root = Path(policy.target_dir).expanduser() / PACKAGE_ROOT_NAME
    if not root.is_dir():
        return []
    owned: list[tuple[float, Path]] = []
    for entry in root.iterdir():
        manifest_path = entry / "manifest.json"
        if entry.is_symlink() or not entry.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("source_vm_name")) == policy.vm_name:
            owned.append((entry.stat().st_mtime, entry))
    return [path for _, path in sorted(owned, reverse=True)]


def prune_policy_backups(policy: BackupPolicy) -> list[str]:
    """Borra las copias por encima de la retención (solo paquetes de la VM
    de la política, solo bajo su root de backups)."""
    backups = list_policy_backups(policy)
    removed: list[str] = []
    root = (Path(policy.target_dir).expanduser() / PACKAGE_ROOT_NAME).resolve()
    for stale in backups[max(1, int(policy.retention)) :]:
        resolved = stale.resolve()
        if resolved.parent != root:
            continue
        shutil.rmtree(resolved, ignore_errors=True)
        removed.append(str(resolved))
    return removed


def run_policy(backend: Any, policy: BackupPolicy, store: BackupPolicyStore | None = None) -> dict[str, Any]:
    log = get_logger()
    result: dict[str, Any] = {"policy_id": policy.id, "vm_name": policy.vm_name, "ok": False}
    try:
        export = export_vm_package(
            backend,
            policy.vm_name,
            policy.target_dir,
            migration_id=f"{policy.vm_name}-backup-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
            include_iso=policy.include_iso,
        )
        result["package_dir"] = export["package_dir"]
        result["pruned"] = prune_policy_backups(policy)
        result["ok"] = True
        policy.last_result = "ok"
        log.info("nas", f"backup ok: {policy.vm_name} → {export['package_dir']}", vm_id=policy.vm_name)
    except HyperGeryError as exc:
        result["error"] = str(exc)
        policy.last_result = f"error: {exc}"
        log.error("nas", f"backup failed: {policy.vm_name}: {exc}", vm_id=policy.vm_name)
    policy.last_run_at = now_iso()
    if store is not None:
        store.update(policy)
    return result


def run_due(backend: Any, store: BackupPolicyStore, *, now: datetime | None = None) -> list[dict[str, Any]]:
    return [run_policy(backend, policy, store) for policy in store.list() if policy.is_due(now)]
