from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import HyperGeryError

CATEGORIES = (
    "app",
    "agent",
    "hub",
    "nas",
    "teleport",
    "battery",
    "orchestrator",
    "network",
    "guest",
    "api",
    "memdiff",
    "telemetry",
    "hosts",
    "labs",
    "vms",
    "tests",
)

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}

_MEMORY_LIMIT = 2000


def xdg_state_home() -> Path:
    override = os.environ.get("XDG_STATE_HOME")
    base = Path(override).expanduser() if override else Path.home() / ".local" / "state"
    return base


def default_log_path() -> Path:
    return xdg_state_home() / "hypergery" / "logs" / "v1-events.jsonl"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_operation_id(kind: str) -> str:
    """Operation id for long-running operations (teleport, nas commit, ...)."""
    clean = "".join(ch for ch in str(kind or "op").lower() if ch.isalnum() or ch == "-") or "op"
    return f"{clean}-{uuid.uuid4().hex[:12]}"


class StructuredLogger:
    """Structured JSONL event log with an in-memory ring buffer.

    Every record carries: timestamp, level, category, module, host, lab_id,
    vm_id, operation_id, message, details. Events also flow into the standard
    `logging` module so the existing activity log keeps working.
    """

    def __init__(self, path: str | Path | None = None, *, level: str = "info") -> None:
        self.path = Path(path).expanduser() if path else default_log_path()
        self.set_level(level)
        self._memory: deque[dict[str, Any]] = deque(maxlen=_MEMORY_LIMIT)
        self._lock = threading.Lock()

    def set_level(self, level: str) -> None:
        if level not in LEVELS:
            raise HyperGeryError(f"Unknown log level: {level}. Allowed: {', '.join(LEVELS)}")
        self.level = level

    def log(
        self,
        level: str,
        category: str,
        message: str,
        *,
        module: str = "",
        host: str = "",
        lab_id: str = "",
        vm_id: str = "",
        operation_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if level not in LEVELS:
            raise HyperGeryError(f"Unknown log level: {level}")
        if category not in CATEGORIES:
            raise HyperGeryError(f"Unknown log category: {category}. Allowed: {', '.join(CATEGORIES)}")
        if LEVELS[level] < LEVELS[self.level]:
            return None
        record = {
            "timestamp": now_iso(),
            "level": level,
            "category": category,
            "module": module,
            "host": host,
            "lab_id": lab_id,
            "vm_id": vm_id,
            "operation_id": operation_id,
            "message": str(message),
            "details": details or {},
        }
        with self._lock:
            self._memory.append(record)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError:
                # Logging must never break an operation; memory buffer keeps it.
                pass
        logging.log(LEVELS[level], "[%s] %s", category, message)
        return record

    def debug(self, category: str, message: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.log("debug", category, message, **kwargs)

    def info(self, category: str, message: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.log("info", category, message, **kwargs)

    def warning(self, category: str, message: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.log("warning", category, message, **kwargs)

    def error(self, category: str, message: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.log("error", category, message, **kwargs)

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._memory)
        return items[-max(1, limit):]

    def query(
        self,
        *,
        category: str | None = None,
        level: str | None = None,
        operation_id: str | None = None,
        host: str | None = None,
        lab_id: str | None = None,
        contains: str | None = None,
        limit: int = 200,
        from_file: bool = False,
    ) -> list[dict[str, Any]]:
        """Filter events from memory (default) or the JSONL file on disk."""
        if from_file:
            records = self._read_file()
        else:
            records = self.recent(limit=_MEMORY_LIMIT)
        minimum = LEVELS.get(level or "", None)
        out: list[dict[str, Any]] = []
        for record in records:
            if category and record.get("category") != category:
                continue
            if minimum is not None and LEVELS.get(record.get("level", ""), 0) < minimum:
                continue
            if operation_id and record.get("operation_id") != operation_id:
                continue
            if host and record.get("host") != host:
                continue
            if lab_id and record.get("lab_id") != lab_id:
                continue
            if contains and contains.lower() not in str(record.get("message", "")).lower():
                continue
            out.append(record)
        return out[-max(1, limit):]

    def _read_file(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return records

    def export(self, destination: str | Path, **filters: Any) -> Path:
        """Export filtered events (from the file) to a JSON document."""
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        events = self.query(from_file=True, limit=100000, **filters)
        target.write_text(json.dumps({"events": events, "exported_at": now_iso()}, indent=2) + "\n", encoding="utf-8")
        return target


_default_logger: StructuredLogger | None = None
_default_lock = threading.Lock()


def get_logger() -> StructuredLogger:
    """Process-wide structured logger (created lazily)."""
    global _default_logger
    with _default_lock:
        if _default_logger is None:
            _default_logger = StructuredLogger()
        return _default_logger
