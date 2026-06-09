"""Canal de progreso uniforme (TD-9).

Contrato único para CUALQUIER operación larga (migración v1.5, backups,
teleport…): porcentaje + fase + mensaje + métricas vivas, consumible por la
UI Qt, el CLI y la app Android (v1.6) vía long-poll del API.

Registro en memoria, thread-safe y versionado: cada update incrementa
``version``, y ``wait_for_change`` bloquea hasta que haya una versión más
nueva (o venza el timeout) — eso es todo lo que necesita un long-poll HTTP.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from .hglog import get_logger, now_iso

OPERATION_STATUSES = ("running", "done", "failed", "cancelled")

# Cuántas operaciones terminadas se retienen para consulta.
FINISHED_HISTORY_LIMIT = 50


class ProgressOperation:
    def __init__(self, operation_id: str, kind: str, *, message: str = "") -> None:
        self.operation_id = operation_id
        self.kind = kind
        self.status = "running"
        self.phase = ""
        self.percent = 0.0
        self.message = message
        self.metrics: dict[str, Any] = {}
        self.error = ""
        self.version = 0
        self.created_at = now_iso()
        self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "status": self.status,
            "phase": self.phase,
            "percent": round(float(self.percent), 1),
            "message": self.message,
            "metrics": dict(self.metrics),
            "error": self.error,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProgressChannel:
    def __init__(self) -> None:
        self._operations: dict[str, ProgressOperation] = {}
        self._finished_order: list[str] = []
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)

    # Escritura ----------------------------------------------------------- #

    def start(self, kind: str, *, operation_id: str = "", message: str = "") -> str:
        operation_id = operation_id or f"op-{kind}-{uuid.uuid4().hex[:10]}"
        with self._changed:
            operation = ProgressOperation(operation_id, kind, message=message)
            self._operations[operation_id] = operation
            self._changed.notify_all()
        get_logger().info("app", f"operation started: {operation_id}", operation_id=operation_id, details={"kind": kind})
        return operation_id

    def _mutate(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        with self._changed:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(f"Unknown operation: {operation_id}")
            for key, value in changes.items():
                if value is None:
                    continue
                if key == "metrics":
                    operation.metrics.update(value)
                else:
                    setattr(operation, key, value)
            operation.percent = max(0.0, min(100.0, float(operation.percent)))
            operation.version += 1
            operation.updated_at = now_iso()
            if operation.status in {"done", "failed", "cancelled"}:
                self._remember_finished(operation_id)
            self._changed.notify_all()
            return operation.to_dict()

    def update(
        self,
        operation_id: str,
        *,
        phase: str | None = None,
        percent: float | None = None,
        message: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._mutate(operation_id, phase=phase, percent=percent, message=message, metrics=metrics)

    def complete(self, operation_id: str, message: str = "") -> dict[str, Any]:
        return self._mutate(operation_id, status="done", percent=100.0, message=message or None)

    def fail(self, operation_id: str, error: str, *, message: str = "") -> dict[str, Any]:
        return self._mutate(operation_id, status="failed", error=error, message=message or None)

    def cancel(self, operation_id: str, message: str = "") -> dict[str, Any]:
        return self._mutate(operation_id, status="cancelled", message=message or None)

    def _remember_finished(self, operation_id: str) -> None:
        # Llamar con el lock cogido.
        if operation_id not in self._finished_order:
            self._finished_order.append(operation_id)
        while len(self._finished_order) > FINISHED_HISTORY_LIMIT:
            stale = self._finished_order.pop(0)
            self._operations.pop(stale, None)

    # Lectura -------------------------------------------------------------- #

    def get(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(f"Unknown operation: {operation_id}")
            return operation.to_dict()

    def list(self, *, kind: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            snapshot = [operation.to_dict() for operation in self._operations.values()]
        if kind:
            snapshot = [op for op in snapshot if op["kind"] == kind]
        if active_only:
            snapshot = [op for op in snapshot if op["status"] == "running"]
        return sorted(snapshot, key=lambda op: op["created_at"])

    def wait_for_change(self, operation_id: str, *, since_version: int = -1, timeout: float = 25.0) -> dict[str, Any]:
        """Long-poll: devuelve el estado en cuanto version > since_version
        (inmediato si ya lo es), o el estado actual al vencer el timeout."""
        deadline = threading.TIMEOUT_MAX if timeout is None else timeout
        with self._changed:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(f"Unknown operation: {operation_id}")
            self._changed.wait_for(
                lambda: self._operations[operation_id].version > since_version
                or self._operations[operation_id].status != "running",
                timeout=deadline,
            )
            return self._operations[operation_id].to_dict()


_channel: ProgressChannel | None = None
_channel_lock = threading.Lock()


def get_progress_channel() -> ProgressChannel:
    global _channel
    with _channel_lock:
        if _channel is None:
            _channel = ProgressChannel()
        return _channel
