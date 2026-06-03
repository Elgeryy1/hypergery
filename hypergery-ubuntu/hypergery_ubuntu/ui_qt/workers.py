from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class BackendJob(QThread):
    succeeded = Signal()
    failed = Signal()

    def __init__(self, label: str, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.label = label
        self.fn = fn
        self.result: Any = None
        self.error_message = ""

    def run(self) -> None:
        try:
            self.result = self.fn()
            self.succeeded.emit()
        except Exception as exc:
            logging.error("Qt backend job failed: %s", exc, exc_info=True)
            self.error_message = str(exc)
            self.failed.emit()
