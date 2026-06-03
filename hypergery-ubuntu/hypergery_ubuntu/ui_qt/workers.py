from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class BackendJob(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, label: str, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.label = label
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn())
        except Exception as exc:
            logging.error("Qt backend job failed: %s", exc, exc_info=True)
            self.failed.emit(str(exc))
