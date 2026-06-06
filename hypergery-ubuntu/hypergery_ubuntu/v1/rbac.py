from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import HyperGeryError, PermissionDeniedError
from .hglog import get_logger, now_iso, xdg_state_home

ROLES = ("SuperAdmin", "Admin", "Operator", "Guest")

PERMISSIONS = (
    "can_view_labs",
    "can_start_vm",
    "can_stop_vm",
    "can_commit_nas",
    "can_teleport",
    "can_use_remote_compute",
    "can_manage_guests",
    "can_change_settings",
)

# Default permission sets per role. Guests get the local minimum; anything
# else must be granted explicitly per user.
DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "SuperAdmin": PERMISSIONS,
    "Admin": (
        "can_view_labs",
        "can_start_vm",
        "can_stop_vm",
        "can_commit_nas",
        "can_teleport",
        "can_use_remote_compute",
        "can_manage_guests",
        "can_change_settings",
    ),
    "Operator": (
        "can_view_labs",
        "can_start_vm",
        "can_stop_vm",
        "can_commit_nas",
        "can_teleport",
        "can_use_remote_compute",
    ),
    "Guest": ("can_view_labs", "can_start_vm", "can_stop_vm"),
}

# Permissions a Guest can never hold, even by explicit grant — guests must
# not consume the admin's remote compute, manage users, or change settings.
GUEST_FORBIDDEN = ("can_use_remote_compute", "can_manage_guests", "can_change_settings")

# Permissions scoped to a lab: guests only exercise them on assigned labs.
LAB_SCOPED_PERMISSIONS = ("can_view_labs", "can_start_vm", "can_stop_vm", "can_commit_nas", "can_teleport")


@dataclass
class User:
    id: str
    name: str = ""
    role: str = "Guest"
    assigned_labs: list[str] = field(default_factory=list)
    extra_permissions: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id
        if self.role not in ROLES:
            raise HyperGeryError(f"Unknown role: {self.role}. Allowed: {', '.join(ROLES)}")
        self.extra_permissions = [item for item in self.extra_permissions if item in PERMISSIONS]
        if not self.created_at:
            self.created_at = now_iso()

    def permissions(self) -> set[str]:
        granted = set(DEFAULT_ROLE_PERMISSIONS[self.role]) | set(self.extra_permissions)
        if self.role == "Guest":
            granted -= set(GUEST_FORBIDDEN)
        return granted

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_permission(user: User, permission: str, *, lab_id: str | None = None) -> bool:
    """True when the user holds the permission (and lab access if scoped)."""
    if permission not in PERMISSIONS:
        raise HyperGeryError(f"Unknown permission: {permission}")
    if permission not in user.permissions():
        return False
    if user.role == "Guest" and lab_id is not None and permission in LAB_SCOPED_PERMISSIONS:
        return lab_id in user.assigned_labs
    return True


def audit(user: User, action: str, *, allowed: bool, lab_id: str = "", details: dict[str, Any] | None = None) -> None:
    """Audit entry for every permission decision (structured log, guest category)."""
    get_logger().log(
        "info" if allowed else "warning",
        "guest",
        f"{'ALLOWED' if allowed else 'DENIED'} {action} for {user.id} (role {user.role})"
        + (f" on lab {lab_id}" if lab_id else ""),
        lab_id=lab_id,
        details={"user": user.id, "role": user.role, "action": action, "allowed": allowed, **(details or {})},
    )


def require_permission(user: User, permission: str, *, lab_id: str | None = None) -> None:
    allowed = check_permission(user, permission, lab_id=lab_id)
    audit(user, permission, allowed=allowed, lab_id=lab_id or "")
    if not allowed:
        scope = f" on lab {lab_id}" if lab_id else ""
        raise PermissionDeniedError(f"{user.id} (role {user.role}) is not allowed to {permission}{scope}.")


def default_users_path() -> Path:
    return xdg_state_home() / "hypergery" / "users.json"


class UserStore:
    """JSON-backed user registry. No passwords are stored — this is local
    RBAC for collaboration control, not network authentication."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_users_path()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Cannot read users file {self.path}: {exc}") from exc

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        # Atomic write so a concurrent reader never sees a partial file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def add_user(self, user: User) -> User:
        data = self._read()
        if user.id in data:
            raise HyperGeryError(f"User already exists: {user.id}")
        data[user.id] = user.to_dict()
        self._write(data)
        return user

    def get_user(self, user_id: str) -> User:
        data = self._read()
        if user_id not in data:
            raise HyperGeryError(f"User does not exist: {user_id}")
        return User(**data[user_id])

    def list_users(self) -> list[User]:
        return [User(**record) for record in sorted(self._read().values(), key=lambda item: item["id"])]

    def remove_user(self, user_id: str) -> None:
        data = self._read()
        if user_id not in data:
            raise HyperGeryError(f"User does not exist: {user_id}")
        del data[user_id]
        self._write(data)

    def assign_lab(self, user_id: str, lab_id: str) -> User:
        data = self._read()
        if user_id not in data:
            raise HyperGeryError(f"User does not exist: {user_id}")
        labs = data[user_id].setdefault("assigned_labs", [])
        if lab_id not in labs:
            labs.append(lab_id)
        self._write(data)
        return User(**data[user_id])
