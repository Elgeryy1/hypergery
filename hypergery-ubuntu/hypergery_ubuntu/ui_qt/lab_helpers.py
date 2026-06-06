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


def build_lab_topology(lab: dict[str, Any], vms: Iterable[VmSummary]) -> dict[str, Any]:
    lab_id = str(lab.get("lab_id", ""))
    live = {vm.name: vm for vm in vms if vm_belongs_to_lab(vm, lab_id)}
    manifest_vm_names = [str(n) for n in lab.get("vms", [])]
    all_names: list[str] = list(dict.fromkeys(list(live.keys()) + manifest_vm_names))
    vm_nodes = []
    for name in all_names:
        vm = live.get(name)
        vm_nodes.append({
            "name": name,
            "state": (vm.state or "unknown").lower() if vm else "not created",
            "ram_mib": vm.ram_mib or 0 if vm else 0,
            "vcpus": vm.vcpus or 0 if vm else 0,
            "live": vm is not None,
        })
    return {
        "lab_id": lab_id,
        "lab_name": lab.get("name", lab_id),
        "network_mode": lab.get("network_mode", "nat"),
        "network_id": lab.get("network_id", ""),
        "subnet": lab.get("subnet", ""),
        "bridge_name": lab.get("bridge_name", ""),
        "vms": vm_nodes,
    }


def topology_to_json(topology: dict[str, Any]) -> dict[str, Any]:
    return dict(topology)


def _normalized_state(state: str) -> str:
    value = str(state or "unknown").lower()
    if value in {"shutoff", "shut off"}:
        return "shut off"
    return value


def unify_lab_vms(
    lab: dict[str, Any],
    local_vms: Iterable[VmSummary],
    remote_vms: Iterable[dict[str, Any]],
    local_host_id: str,
) -> list[dict[str, Any]]:
    """Combine local libvirt VMs and Hub remote inventory for one lab.

    Remote entries for the local host are skipped (they are the same VMs the
    local backend already reports). Manifest-only VMs that do not exist
    anywhere yet appear with state 'not created'.
    """
    lab_id = str(lab.get("lab_id", ""))
    roles = lab.get("vm_roles") or {}
    unified: list[dict[str, Any]] = []
    for vm in local_vms:
        if not vm_belongs_to_lab(vm, lab_id):
            continue
        unified.append(
            {
                "name": vm.name,
                "state": _normalized_state(vm.state),
                "host_id": local_host_id,
                "ram_mib": vm.ram_mib or 0,
                "vcpus": vm.vcpus or 0,
                "remote": False,
                "role": str(roles.get(vm.name) or ""),
            }
        )
    for vm in remote_vms:
        host_id = str(vm.get("host_id") or "")
        if not host_id or host_id == local_host_id:
            continue
        if (str(vm.get("lab_id") or "") or "default-lab") != lab_id:
            continue
        name = str(vm.get("vm_name") or vm.get("name") or "")
        if not name:
            continue
        unified.append(
            {
                "name": name,
                "state": _normalized_state(str(vm.get("state") or "unknown")),
                "host_id": host_id,
                "ram_mib": int(vm.get("ram_mib") or 0),
                "vcpus": int(vm.get("vcpus") or 0),
                "remote": True,
                "role": str(roles.get(name) or ""),
            }
        )
    known = {vm["name"] for vm in unified}
    for manifest_name in lab.get("vms", []):
        name = str(manifest_name)
        if name in known:
            continue
        unified.append(
            {
                "name": name,
                "state": "not created",
                "host_id": "",
                "ram_mib": 0,
                "vcpus": 0,
                "remote": False,
                "role": str(roles.get(name) or ""),
            }
        )
    return sorted(unified, key=lambda vm: vm["name"])


def lab_status_summary(unified_vms: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts and host distribution for a lab's unified VM list."""
    counts = {"total": 0, "running": 0, "shut_off": 0, "paused": 0, "unknown": 0, "not_created": 0}
    hosts: dict[str, list[str]] = {}
    for vm in unified_vms:
        counts["total"] += 1
        state = vm["state"]
        if state == "running":
            counts["running"] += 1
        elif state == "shut off":
            counts["shut_off"] += 1
        elif state == "paused":
            counts["paused"] += 1
        elif state == "not created":
            counts["not_created"] += 1
        else:
            counts["unknown"] += 1
        if vm["host_id"]:
            hosts.setdefault(vm["host_id"], []).append(vm["name"])
    return {"counts": counts, "hosts": hosts}


# Role-aware boot order: infrastructure first on start, clients first on
# shutdown. Unassigned roles ("") go last on start / first on shutdown,
# alphabetically within each tier.
ROLE_START_TIERS = {
    "router": 0,
    "firewall": 0,
    "dns": 1,
    "ad": 1,
    "server": 2,
    "db": 2,
    "web": 2,
    "client": 3,
    "": 4,
}


def order_lab_vms_for_action(vms: Iterable[dict[str, Any]], action: str) -> list[dict[str, Any]]:
    """Order VMs by role tier: start boots infrastructure first; shutdown reverses."""
    fallback_tier = max(ROLE_START_TIERS.values())

    def tier(vm: dict[str, Any]) -> int:
        value = ROLE_START_TIERS.get(str(vm.get("role") or ""), fallback_tier)
        return value if action == "start" else fallback_tier - value

    return sorted(vms, key=lambda vm: (tier(vm), vm["name"]))


def plan_lab_power_action(unified_vms: Iterable[dict[str, Any]], action: str) -> dict[str, Any]:
    """Decide which lab VMs a start/shutdown action targets, in role order.

    start targets shut off VMs (routers/firewalls → dns/ad → servers →
    clients); shutdown targets running VMs (ACPI) in the reverse order. VMs
    in other states are reported as skipped with a reason — never forced.
    """
    if action == "start":
        eligible = {"shut off"}
    elif action == "shutdown":
        eligible = {"running"}
    else:
        raise HyperGeryError(f"Unsupported lab power action: {action}")
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for vm in unified_vms:
        if vm["state"] in eligible:
            targets.append(vm)
        else:
            skipped.append({"name": vm["name"], "reason": f"state is '{vm['state']}'"})
    targets = order_lab_vms_for_action(targets, action)
    host_ids = {vm["host_id"] for vm in targets if vm["host_id"]}
    return {"action": action, "targets": targets, "skipped": skipped, "host_count": len(host_ids)}
