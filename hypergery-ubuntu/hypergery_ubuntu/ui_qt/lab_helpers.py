from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..backend import HyperGeryError, VmSummary
from ..labs import allocate_lab_subnet, generate_lab_bridge_name, generate_lab_network_name, normalize_lab_id


def build_lab_preview(
    name: str,
    network_mode: str,
    existing_lab_ids: Iterable[str] = (),
    existing_subnets: Iterable[str] = (),
) -> dict[str, Any]:
    preview: dict[str, Any] = {
        "valid": False,
        "error": "",
        "lab_id": "",
        "network_id": "",
        "network_mode": network_mode,
        "bridge_name": "",
        "subnet": "",
    }
    try:
        lab_id = normalize_lab_id(name)
        if lab_id in set(existing_lab_ids):
            raise HyperGeryError(f"Lab already exists: {lab_id}")
        if network_mode not in {"nat", "isolated"}:
            raise HyperGeryError("Network mode must be NAT or isolated.")
        preview.update(
            {
                "valid": True,
                "lab_id": lab_id,
                "network_id": generate_lab_network_name(lab_id, network_mode),
                "bridge_name": generate_lab_bridge_name(lab_id),
                "subnet": allocate_lab_subnet(lab_id, set(existing_subnets)),
            }
        )
    except HyperGeryError as exc:
        preview["error"] = str(exc)
    return preview


def vm_belongs_to_lab(vm: VmSummary, lab_id: str) -> bool:
    return (vm.lab_id or "default-lab") == lab_id


def filter_vms_for_lab(vms: Iterable[VmSummary], lab_id: str | None, selected_lab_only: bool) -> list[VmSummary]:
    items = list(vms)
    if not selected_lab_only or not lab_id:
        return items
    return [vm for vm in items if vm_belongs_to_lab(vm, lab_id)]


def vm_count_for_lab(lab: dict[str, Any], vms: Iterable[VmSummary]) -> int:
    lab_id = str(lab.get("lab_id", ""))
    live_names = {vm.name for vm in vms if vm_belongs_to_lab(vm, lab_id)}
    manifest_names = {str(name) for name in lab.get("vms", [])}
    return len(live_names | manifest_names)
