from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .errors import NetworkConflictError
from .hglog import get_logger

NETWORK_MODES = ("host_only", "nat", "internal", "bridged", "simulated")


@dataclass
class Network:
    id: str
    lab_id: str
    name: str = ""
    cidr: str = ""
    mode: str = "nat"
    gateway: str = ""
    dhcp_enabled: bool = True
    isolated: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id
        if self.mode not in NETWORK_MODES:
            self.mode = "simulated"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def network_from_lab(lab: dict[str, Any]) -> Network:
    """Build the logical per-lab network from an existing lab manifest."""
    lab_id = str(lab.get("lab_id") or "")
    mode = "internal" if str(lab.get("network_mode") or "nat") == "isolated" else "nat"
    subnet = str(lab.get("subnet") or "")
    gateway = ""
    if subnet:
        try:
            network = ipaddress.ip_network(subnet, strict=True)
            gateway = str(next(network.hosts()))
        except (ValueError, StopIteration):
            gateway = ""
    return Network(
        id=str(lab.get("network_id") or f"hg-net-{lab_id}"),
        lab_id=lab_id,
        cidr=subnet,
        mode=mode,
        gateway=gateway,
        dhcp_enabled=True,
        isolated=mode == "internal",
    )


def _parse_cidr(network: Network, errors: list[str]) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    if not network.cidr:
        errors.append(f"Network {network.id}: missing CIDR.")
        return None
    try:
        return ipaddress.ip_network(network.cidr, strict=True)
    except ValueError as exc:
        errors.append(f"Network {network.id}: invalid CIDR '{network.cidr}': {exc}")
        return None


def validate_networks(
    networks: Iterable[Network],
    *,
    vms: Iterable[Any] = (),
) -> dict[str, Any]:
    """Detect conflicts: duplicate/overlapping CIDRs, duplicate gateways,
    gateways outside their CIDR, DHCP overlap, VMs attached to unknown
    networks, and unauthorized cross-lab attachments. Emits structured
    network events; returns {ok, errors, warnings, events}."""
    networks = list(networks)
    errors: list[str] = []
    warnings: list[str] = []
    events: list[dict[str, str]] = []
    log = get_logger()

    def event(kind: str, message: str, lab_id: str = "") -> None:
        events.append({"kind": kind, "message": message, "lab_id": lab_id})
        log.warning("network", message, lab_id=lab_id) if kind != "network_validated" else log.info(
            "network", message, lab_id=lab_id
        )

    parsed: list[tuple[Network, ipaddress.IPv4Network | ipaddress.IPv6Network]] = []
    for network in networks:
        cidr = _parse_cidr(network, errors)
        if cidr is None:
            continue
        if network.gateway:
            try:
                gateway_ip = ipaddress.ip_address(network.gateway)
                if gateway_ip not in cidr:
                    errors.append(f"Network {network.id}: gateway {network.gateway} is outside {network.cidr}.")
            except ValueError:
                errors.append(f"Network {network.id}: invalid gateway '{network.gateway}'.")
        parsed.append((network, cidr))

    for index, (network_a, cidr_a) in enumerate(parsed):
        for network_b, cidr_b in parsed[index + 1 :]:
            if cidr_a.overlaps(cidr_b):
                message = (
                    f"CIDR conflict: {network_a.id} ({network_a.cidr}, lab {network_a.lab_id}) overlaps "
                    f"{network_b.id} ({network_b.cidr}, lab {network_b.lab_id})."
                )
                errors.append(message)
                event("conflict_detected", message, network_a.lab_id)
                if network_a.dhcp_enabled and network_b.dhcp_enabled:
                    dhcp_message = f"DHCP conflict: {network_a.id} and {network_b.id} both serve DHCP on overlapping ranges."
                    errors.append(dhcp_message)
                    event("dhcp_warning", dhcp_message, network_a.lab_id)
            if network_a.gateway and network_a.gateway == network_b.gateway:
                message = f"Duplicate gateway {network_a.gateway} on {network_a.id} and {network_b.id}."
                errors.append(message)
                event("conflict_detected", message, network_a.lab_id)

    by_id = {network.id: network for network in networks}
    for vm in vms:
        vm_id = getattr(vm, "id", "") or getattr(vm, "name", "")
        vm_lab = getattr(vm, "lab_id", "")
        for network_id in getattr(vm, "network_ids", []) or []:
            network = by_id.get(network_id)
            if network is None:
                message = f"VM {vm_id} is attached to a network that does not exist: {network_id}."
                errors.append(message)
                event("conflict_detected", message, vm_lab)
                continue
            if network.lab_id and vm_lab and network.lab_id != vm_lab:
                if vm_lab not in network.allowed_hosts:
                    message = (
                        f"Blocked cross-lab link: VM {vm_id} (lab {vm_lab}) attached to {network_id} "
                        f"(lab {network.lab_id}) without explicit authorization."
                    )
                    errors.append(message)
                    event("blocked_cross_link", message, vm_lab)
                else:
                    warnings.append(
                        f"Cross-lab link allowed by configuration: VM {vm_id} → {network_id}."
                    )
            else:
                events.append({"kind": "vm_connected", "message": f"VM {vm_id} connected to {network_id}.", "lab_id": vm_lab})

    if not errors:
        event("network_validated", f"{len(networks)} network(s) validated without conflicts.")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "events": events}


def require_valid_networks(networks: Iterable[Network], **kwargs: Any) -> dict[str, Any]:
    result = validate_networks(networks, **kwargs)
    if not result["ok"]:
        raise NetworkConflictError("Network validation failed: " + "; ".join(result["errors"]))
    return result
