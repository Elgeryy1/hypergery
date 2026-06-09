"""Autenticación del API v1 (TD-5): tokens bearer ligados a usuarios RBAC.

Dos tipos de credencial:
- **Token de propietario** (``api_token``, generado con 0600): identidad
  SuperAdmin implícita del dueño del equipo (UI local, CLI).
- **Tokens de usuario** (``api_tokens.json``, 0600): emitidos por usuario de
  ``v1/rbac.py`` (p. ej. un Guest de un lab o la app Android); cada petición
  se autoriza con los permisos efectivos de ese usuario.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from ..backend import xdg_state_home
from .rbac import User, UserStore

OWNER_TOKEN_FILE = "api_token"
TOKEN_STORE_FILE = "api_tokens.json"
API_TOKEN_ENV_VAR = "HYPERGERY_API_TOKEN"

OWNER_USER = User(id="owner", name="Propietario", role="SuperAdmin")


def _state_dir() -> Path:
    return Path(xdg_state_home())


def load_or_create_api_token(state_dir: str | Path | None = None) -> str:
    env_token = os.environ.get(API_TOKEN_ENV_VAR, "").strip()
    if env_token:
        return env_token
    token_path = Path(state_dir) if state_dir else _state_dir()
    token_path = token_path / OWNER_TOKEN_FILE
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


class ApiTokenStore:
    """token → user_id, persistido en JSON con 0600."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _state_dir() / TOKEN_STORE_FILE

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.touch(mode=0o600, exist_ok=True)
        tmp.chmod(0o600)
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        self.path.chmod(0o600)

    def issue(self, user_id: str) -> str:
        """Emite un token nuevo para el usuario (revoca el anterior)."""
        data = {token: uid for token, uid in self._load().items() if uid != user_id}
        token = secrets.token_urlsafe(32)
        data[token] = user_id
        self._save(data)
        return token

    def revoke(self, user_id: str) -> int:
        data = self._load()
        kept = {token: uid for token, uid in data.items() if uid != user_id}
        removed = len(data) - len(kept)
        if removed:
            self._save(kept)
        return removed

    def resolve(self, token: str) -> str | None:
        if not token:
            return None
        return self._load().get(token)


def resolve_user(
    token: str,
    *,
    owner_token: str,
    token_store: ApiTokenStore,
    user_store: UserStore,
) -> User | None:
    """Usuario autenticado para un token bearer, o None si no es válido."""
    import hmac

    if owner_token and token and hmac.compare_digest(owner_token, token):
        return OWNER_USER
    user_id = token_store.resolve(token)
    if not user_id:
        return None
    try:
        return user_store.get_user(user_id)
    except Exception:
        return None
