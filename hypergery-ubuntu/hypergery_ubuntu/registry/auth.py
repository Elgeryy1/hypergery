"""Autenticación del Hub (HG-BUG-0001, TD-5).

Token bearer obligatorio por defecto: el servidor lo genera y persiste con
permisos 0600 junto a la base de datos; los clientes lo envían en
``Authorization: Bearer <token>``. Sin TLS el token viaja en claro: para salir
de la LAN de confianza hay que poner el Hub detrás de un reverse proxy TLS o
una VPN (ver docs/HUB_SECURITY.md).
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from pathlib import Path

TOKEN_FILE_NAME = "hub_token"
TOKEN_ENV_VAR = "HYPERGERY_HUB_TOKEN"

# Anti fuerza bruta: tras MAX_FAILURES fallos de auth en WINDOW_SECONDS la IP
# queda bloqueada hasta que expire la ventana.
AUTH_FAILURE_WINDOW_SECONDS = 60.0
AUTH_MAX_FAILURES_PER_WINDOW = 10


def load_or_create_hub_token(db_path: str | Path) -> str:
    """Token del Hub: env > fichero junto a la DB (creado con 0600)."""
    env_token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if env_token:
        return env_token
    token_path = Path(db_path).expanduser().parent / TOKEN_FILE_NAME
    if token_path.is_file():
        stored = token_path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_urlsafe(32)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.touch(mode=0o600, exist_ok=True)
    token_path.chmod(0o600)
    token_path.write_text(token + "\n", encoding="utf-8")
    return token


def token_matches(expected: str, presented: str) -> bool:
    return bool(expected) and hmac.compare_digest(expected, presented)


def bearer_token(authorization_header: str | None) -> str:
    """Extrae el token de un header ``Authorization: Bearer <token>``."""
    value = (authorization_header or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


class AuthRateLimiter:
    """Limitador de fallos de autenticación por IP (ventana deslizante)."""

    def __init__(
        self,
        *,
        max_failures: int = AUTH_MAX_FAILURES_PER_WINDOW,
        window_seconds: float = AUTH_FAILURE_WINDOW_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        entries = [stamp for stamp in self._failures.get(key, []) if now - stamp < self.window_seconds]
        if entries:
            self._failures[key] = entries
        else:
            self._failures.pop(key, None)
        return entries

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, self._clock())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(key, now)
            self._failures.setdefault(key, []).append(now)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
