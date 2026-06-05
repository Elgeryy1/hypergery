from __future__ import annotations

import ipaddress
from typing import Any, Iterable

from ..backend import validate_vm_name
from ..labs import LAB_SUBJECTS, LAB_VM_ROLES, validate_lab_id
from .errors import HyperGeryError, LabValidationError

__all__ = ["LAB_SUBJECTS", "validate_lab", "filter_labs"]


def validate_lab(
    manifest: dict[str, Any],
    *,
    existing_labs: Iterable[dict[str, Any]] = (),
    min_free_disk_mib: int | None = None,
    free_disk_mib: int | None = None,
) -> dict[str, Any]:
    """Validate a lab manifest for the v0.9 workspace.

    Checks: lab id, unique VM names, valid VM names, valid roles, subject,
    subnet syntax and conflicts against other labs, and (optionally) storage
    headroom. Returns {ok, errors, warnings}; raises nothing for data issues.
    """
    errors: list[str] = []
    warnings: list[str] = []

    lab_id = str(manifest.get("lab_id") or "")
    try:
        validate_lab_id(lab_id)
    except HyperGeryError as exc:
        errors.append(f"lab_id: {exc}")

    vms = [str(name) for name in manifest.get("vms", [])]
    if len(vms) != len(set(vms)):
        duplicates = sorted({name for name in vms if vms.count(name) > 1})
        errors.append(f"Duplicate VM names in lab: {', '.join(duplicates)}")
    for name in vms:
        try:
            validate_vm_name(name)
        except HyperGeryError as exc:
            errors.append(f"VM name '{name}': {exc}")

    roles = manifest.get("vm_roles") or {}
    for vm_name, role in roles.items():
        if role not in LAB_VM_ROLES:
            errors.append(f"VM '{vm_name}' has unknown role: {role}")
        if vm_name not in vms:
            warnings.append(f"Role assigned to VM not in the lab manifest: {vm_name}")

    subject = str(manifest.get("subject") or "CUSTOM")
    if subject not in LAB_SUBJECTS:
        errors.append(f"Unknown subject: {subject}. Allowed: {', '.join(LAB_SUBJECTS)}")

    subnet = str(manifest.get("subnet") or "")
    network = None
    if subnet:
        try:
            network = ipaddress.ip_network(subnet, strict=True)
        except ValueError as exc:
            errors.append(f"Invalid subnet '{subnet}': {exc}")
    else:
        warnings.append("Lab has no subnet assigned yet.")

    if network is not None:
        for other in existing_labs:
            other_id = str(other.get("lab_id") or "")
            if other_id == lab_id:
                continue
            other_subnet = str(other.get("subnet") or "")
            if not other_subnet:
                continue
            try:
                other_network = ipaddress.ip_network(other_subnet, strict=True)
            except ValueError:
                continue
            if network.overlaps(other_network):
                errors.append(f"Subnet {subnet} overlaps lab '{other_id}' ({other_subnet}).")

    if min_free_disk_mib is not None and free_disk_mib is not None and free_disk_mib < min_free_disk_mib:
        errors.append(
            f"Not enough storage: {free_disk_mib} MiB free, {min_free_disk_mib} MiB required."
        )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def require_valid_lab(manifest: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """validate_lab but raising LabValidationError when invalid."""
    result = validate_lab(manifest, **kwargs)
    if not result["ok"]:
        raise LabValidationError("Lab validation failed: " + "; ".join(result["errors"]))
    return result


def filter_labs(
    labs: Iterable[dict[str, Any]],
    *,
    subject: str | None = None,
    favorites_only: bool = False,
    include_archived: bool = False,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Workspace filters used by UI/CLI: subject, favorites, tags, archived."""
    selected = []
    for lab in labs:
        if not include_archived and lab.get("archived"):
            continue
        if favorites_only and not lab.get("favorite"):
            continue
        if subject and str(lab.get("subject") or "CUSTOM") != subject.upper():
            continue
        if tag and tag not in (lab.get("tags") or []):
            continue
        selected.append(lab)
    return selected
