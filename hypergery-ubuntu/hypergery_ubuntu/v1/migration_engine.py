"""Máquina de estados de migración (TD-4) — base de la live migration v1.5.

Fases ordenadas: PREFLIGHT → TRANSFER → SWITCHOVER → ACTIVATE. Cada fase es
un objeto con ``run``/``rollback``; el motor:

- ejecuta las fases en orden publicando fase/porcentaje/métricas en el canal
  de progreso (TD-9);
- ante un fallo, ejecuta el rollback de las fases YA completadas en orden
  inverso (y el de la fase fallida primero), dejando el origen intacto;
- respeta la regla de oro: **el origen no se toca hasta confirmar el
  destino**. Solo las fases posteriores a ``SWITCHOVER`` pueden declarar
  ``touches_source=True``, y el motor se niega a ejecutar una fase que toque
  el origen antes de ese punto;
- soporta cancelación cooperativa entre fases (→ rollback ordenado).

v1.5 enchufará aquí las fases reales de live migration
(virDomainMigrateToURI3); la migración offline existente queda como fallback.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import HyperGeryError
from .hglog import get_logger
from .progress import ProgressChannel, get_progress_channel

PHASE_ORDER = ("preflight", "transfer", "switchover", "activate")

# Hasta dónde puede llegar una migración sin tocar el origen: todo lo
# anterior al switchover debe ser de solo lectura sobre la VM de origen.
FIRST_SOURCE_MUTATING_PHASE = "switchover"


class MigrationCancelled(HyperGeryError):
    pass


@dataclass
class MigrationPhase:
    """Una fase de la migración.

    ``run(context)`` hace el trabajo (puede usar ``context['report']`` para
    progreso fino); ``rollback(context)`` deshace lo que la fase hubiera
    hecho. ``touches_source`` declara si la fase modifica la VM de ORIGEN.
    """

    name: str
    run: Callable[[dict[str, Any]], Any]
    rollback: Callable[[dict[str, Any]], Any] | None = None
    touches_source: bool = False
    weight: float = 1.0


@dataclass
class MigrationResult:
    ok: bool
    status: str
    operation_id: str
    completed_phases: list[str] = field(default_factory=list)
    rolled_back_phases: list[str] = field(default_factory=list)
    rollback_errors: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "operation_id": self.operation_id,
            "completed_phases": list(self.completed_phases),
            "rolled_back_phases": list(self.rolled_back_phases),
            "rollback_errors": list(self.rollback_errors),
            "error": self.error,
        }


class MigrationEngine:
    def __init__(
        self,
        phases: list[MigrationPhase],
        *,
        channel: ProgressChannel | None = None,
        kind: str = "migration",
    ) -> None:
        names = [phase.name for phase in phases]
        if len(set(names)) != len(names):
            raise HyperGeryError(f"Duplicate phase names: {names}")
        unknown = [name for name in names if name not in PHASE_ORDER]
        if unknown:
            raise HyperGeryError(f"Unknown migration phases: {unknown} (allowed: {PHASE_ORDER})")
        if names != sorted(names, key=PHASE_ORDER.index):
            raise HyperGeryError(f"Phases out of order: {names} (order: {PHASE_ORDER})")
        switchover_index = PHASE_ORDER.index(FIRST_SOURCE_MUTATING_PHASE)
        for phase in phases:
            if phase.touches_source and PHASE_ORDER.index(phase.name) < switchover_index:
                raise HyperGeryError(
                    f"Phase {phase.name} declares touches_source before {FIRST_SOURCE_MUTATING_PHASE}: "
                    "the source VM must stay untouched until the destination is confirmed."
                )
        self.phases = phases
        self.channel = channel or get_progress_channel()
        self.kind = kind
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Cancelación cooperativa: surte efecto entre fases (y dentro de una
        fase si su run consulta context['cancelled']())."""
        self._cancel_requested.set()

    def run(self, context: dict[str, Any] | None = None, *, operation_id: str = "") -> MigrationResult:
        context = dict(context or {})
        total_weight = sum(phase.weight for phase in self.phases) or 1.0
        operation_id = self.channel.start(self.kind, operation_id=operation_id, message="Migración iniciada")
        log = get_logger()
        completed: list[MigrationPhase] = []
        result = MigrationResult(ok=False, status="running", operation_id=operation_id)
        context["operation_id"] = operation_id
        context["cancelled"] = self._cancel_requested.is_set

        done_weight = 0.0
        try:
            for phase in self.phases:
                if self._cancel_requested.is_set():
                    raise MigrationCancelled("Migration cancelled before phase " + phase.name)
                base = 100.0 * done_weight / total_weight

                def report(message: str = "", *, fraction: float = 0.0, metrics: dict[str, Any] | None = None, _phase=phase, _base=base) -> None:
                    span = 100.0 * _phase.weight / total_weight
                    self.channel.update(
                        operation_id,
                        phase=_phase.name,
                        percent=_base + span * max(0.0, min(1.0, fraction)),
                        message=message or None,
                        metrics=metrics,
                    )

                context["report"] = report
                report(f"Fase {phase.name} iniciada")
                phase.run(context)
                completed.append(phase)
                result.completed_phases.append(phase.name)
                done_weight += phase.weight
                self.channel.update(
                    operation_id,
                    phase=phase.name,
                    percent=100.0 * done_weight / total_weight,
                    message=f"Fase {phase.name} completada",
                )
                if self._cancel_requested.is_set():
                    raise MigrationCancelled("Migration cancelled after phase " + phase.name)
            result.ok = True
            result.status = "done"
            self.channel.complete(operation_id, "Migración completada")
            return result
        except BaseException as exc:
            cancelled = isinstance(exc, MigrationCancelled)
            result.error = str(exc)
            result.status = "cancelled" if cancelled else "failed"
            log.warning(
                "teleport",
                f"migration {result.status}: {exc} — rolling back {len(completed)} phase(s)",
                operation_id=operation_id,
            )
            self.channel.update(operation_id, message=f"Rollback en curso ({result.status}): {exc}")
            for phase in reversed(completed):
                if phase.rollback is None:
                    continue
                try:
                    phase.rollback(context)
                    result.rolled_back_phases.append(phase.name)
                except Exception as rollback_exc:  # noqa: BLE001 — el rollback nunca enmascara el error original
                    result.rollback_errors.append(f"{phase.name}: {rollback_exc}")
            if cancelled:
                self.channel.cancel(operation_id, f"Cancelada: origen intacto. {result.error}")
            else:
                self.channel.fail(operation_id, result.error, message="Migración fallida: origen intacto.")
            if not isinstance(exc, (HyperGeryError, Exception)):
                raise
            return result
