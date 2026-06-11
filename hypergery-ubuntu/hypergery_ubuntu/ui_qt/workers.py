from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class BackendJob(QThread):
    succeeded = Signal()
    failed = Signal()
    # Mensajes de avance desde el hilo del trabajo: emitir una señal es seguro
    # (Qt la encola al hilo de la UI); tocar widgets desde aquí NO lo sería.
    progress = Signal(str)

    def __init__(self, label: str, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.label = label
        self.fn = fn
        self.result: Any = None
        self.error_message = ""
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Cancelación cooperativa: el trabajo en curso no puede abortarse a
        mitad (llamadas bloqueantes a virsh/subprocess), pero tras cancelar no
        se emite ningún resultado al UI."""
        self._cancelled = True
        self.requestInterruption()

    def run(self) -> None:
        try:
            result = self.fn()
            if self._cancelled:
                return
            self.result = result
            self.succeeded.emit()
        except Exception as exc:
            if self._cancelled:
                return
            logging.error("Qt backend job failed: %s", exc, exc_info=True)
            self.error_message = str(exc)
            self.failed.emit()
