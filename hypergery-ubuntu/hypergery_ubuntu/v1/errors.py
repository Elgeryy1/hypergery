from __future__ import annotations

from ..backend import HyperGeryError

__all__ = [
    "HyperGeryError",
    "HostOfflineError",
    "NasUnavailableError",
    "TeleportError",
    "BatteryUnavailableError",
    "LabValidationError",
    "NetworkConflictError",
    "PermissionDeniedError",
    "MemDiffError",
    "OrchestratorError",
    "error_code",
]


class HostOfflineError(HyperGeryError):
    """A target host is offline or its agent is not responding."""

    code = "HOST_OFFLINE"


class NasUnavailableError(HyperGeryError):
    """The NAS path is missing, unreadable, or not writable."""

    code = "NAS_UNAVAILABLE"


class TeleportError(HyperGeryError):
    """A teleport operation failed; the source is left in a safe state."""

    code = "TELEPORT_FAILED"


class BatteryUnavailableError(HyperGeryError):
    """No battery information is available on this host."""

    code = "BATTERY_UNAVAILABLE"


class LabValidationError(HyperGeryError):
    """A lab manifest failed validation."""

    code = "LAB_INVALID"


class NetworkConflictError(HyperGeryError):
    """Two lab networks conflict (CIDR, gateway, or DHCP)."""

    code = "NETWORK_CONFLICT"


class PermissionDeniedError(HyperGeryError):
    """The current user/role is not allowed to perform this action."""

    code = "PERMISSION_DENIED"


class MemDiffError(HyperGeryError):
    """A MemDiff delta could not be produced, applied, or verified."""

    code = "MEMDIFF_FAILED"


class OrchestratorError(HyperGeryError):
    """The orchestrator could not produce a placement plan."""

    code = "ORCHESTRATOR_FAILED"


def error_code(exc: BaseException) -> str:
    """Stable machine-readable code for an exception (used by the API)."""
    return getattr(exc, "code", "HYPERGERY_ERROR" if isinstance(exc, HyperGeryError) else "INTERNAL_ERROR")
