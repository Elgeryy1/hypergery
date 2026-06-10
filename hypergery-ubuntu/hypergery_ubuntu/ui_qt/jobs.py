"""Registro central de jobs de fondo del UI (TD-3, HG-BUG-0008).

Todas las operaciones de backend que el UI lanza en hilos pasan por
``JobManager``: un único sitio que sabe qué hay en vuelo, conserva un
histórico acotado y ofrece un ``shutdown`` con espera acotada para el
``closeEvent`` de la ventana principal. La máquina de estados de migración
(v1.5) se apoyará en este mismo registro.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject

from .workers import BackendJob


class JobManager(QObject):
    def __init__(self, parent: QObject | None = None, history_limit: int = 20) -> None:
        super().__init__(parent)
        self._active: list[BackendJob] = []
        self._completed: list[BackendJob] = []
        self._history_limit = history_limit
        self._closing = False

    @property
    def active(self) -> list[BackendJob]:
        return list(self._active)

    @property
    def completed(self) -> list[BackendJob]:
        return list(self._completed)

    @property
    def closing(self) -> bool:
        return self._closing

    def submit(
        self,
        label: str,
        fn: Callable[[], Any],
        *,
        on_success: Callable[[BackendJob], None] | None = None,
        on_failure: Callable[[BackendJob], None] | None = None,
        on_finished: Callable[[BackendJob], None] | None = None,
        track_history: bool = True,
    ) -> BackendJob:
        """Lanza ``fn`` en un hilo y registra el job.

        Los callbacks se entregan en el hilo del UI y se suprimen si el job
        fue cancelado o el manager está cerrándose (HG-BUG-0008: nada de
        señales contra widgets ya destruidos).
        """
        job = BackendJob(label, fn)
        self._active.append(job)

        def _succeeded() -> None:
            if self._closing or job.cancelled:
                return
            if on_success:
                on_success(job)

        def _failed() -> None:
            if self._closing or job.cancelled:
                return
            if on_failure:
                on_failure(job)

        def _finished() -> None:
            if job in self._active:
                self._active.remove(job)
            if track_history and self._history_limit > 0:
                self._completed.append(job)
                del self._completed[: -self._history_limit or None]
            if self._closing or job.cancelled:
                return
            if on_finished:
                on_finished(job)

        job.succeeded.connect(_succeeded)
        job.failed.connect(_failed)
        job.finished.connect(_finished)
        job.start()
        return job

    def shutdown(self, timeout_ms: int = 5000) -> list[str]:
        """Cancela todos los jobs y espera de forma acotada.

        Devuelve las etiquetas de los jobs que siguen vivos al agotar el
        plazo. Esos hilos quedan referenciados por el manager (no se
        destruyen mientras corren) y sus callbacks ya están suprimidos.
        """
        self._closing = True
        for job in list(self._active):
            job.cancel()
        deadline = time.monotonic() + timeout_ms / 1000.0
        survivors: list[str] = []
        for job in list(self._active):
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if not job.wait(remaining_ms):
                survivors.append(job.label)
        if survivors:
            logging.warning("Jobs still running after bounded wait: %s", ", ".join(survivors))
        return survivors
