"""Journal persistente de migraciones en vuelo (HG-BUG-0028).

El invariante "nunca activa en dos hosts" de la live migration (v1.5) vivía
solo en memoria: si el proceso moría entre el switchover (origen ya parado
por libvirt, destino corriendo) y la confirmación final, el origen quedaba
DEFINIDO y arrancable. Con shared storage, un `virsh start` manual del origen
mientras el destino corre = corrupción de disco.

Este journal escribe en disco la VM que ha cruzado el punto de no retorno
(switchover) y aún no se ha confirmado. ``backend.start_vm`` lo consulta y se
niega a arrancar una VM con una migración sin resolver; el preflight de
migración también lo mira. Es un fichero JSON pequeño bajo el state dir, con
una entrada por VM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .backend import HyperGeryError, now_iso, xdg_state_home

JOURNAL_FILE = "migration_journal.json"


def journal_path(state_dir: str | Path | None = None) -> Path:
    base = Path(state_dir) if state_dir else Path(xdg_state_home())
    return base / JOURNAL_FILE


class MigrationJournal:
    """Registro de migraciones que cruzaron el switchover sin confirmarse."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else journal_path()

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

    def begin(self, vm_name: str, *, target_uri: str, operation_id: str = "", phase: str = "switchover") -> None:
        """Marca que ``vm_name`` ha entrado en el punto de no retorno."""
        data = self._load()
        data[vm_name] = {
            "vm_name": vm_name,
            "target_uri": target_uri,
            "operation_id": operation_id,
            "phase": phase,
            "started_at": now_iso(),
        }
        self._save(data)

    def clear(self, vm_name: str) -> bool:
        """Quita la entrada al confirmar el destino (o tras un rollback OK)."""
        data = self._load()
        existed = vm_name in data
        if existed:
            del data[vm_name]
            self._save(data)
        return existed

    def get(self, vm_name: str) -> dict[str, Any] | None:
        return self._load().get(vm_name)

    def list(self) -> list[dict[str, Any]]:
        return list(self._load().values())

    def assert_startable(self, vm_name: str) -> None:
        """Lanza si la VM tiene una migración sin resolver (HG-BUG-0028)."""
        entry = self.get(vm_name)
        if entry is not None:
            raise HyperGeryError(
                f"Refusing to start {vm_name}: it has an unconfirmed migration to "
                f"{entry.get('target_uri', '?')} (since {entry.get('started_at', '?')}). "
                "The VM may already be running on the target — confirm/clean the migration first "
                "(hypergery-cli v1 migrate-journal clear " + vm_name + ")."
            )
