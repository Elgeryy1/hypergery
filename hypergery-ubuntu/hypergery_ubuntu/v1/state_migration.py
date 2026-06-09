from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..backend import HyperGeryError, now_iso, validate_vm_name
from ..labs import validate_lab_id
from ..migration import safe_package_member
from .hglog import get_logger

STATE_PACKAGE_VERSION = 1
MEMSTATE_FILENAME = "memory-state.save"
DOMAIN_FILENAME = "domain.xml"
MANIFEST_FILENAME = "state-manifest.json"

__all__ = [
    "STATE_PACKAGE_VERSION",
    "export_vm_state_package",
    "import_vm_state_package",
    "validate_state_package",
]


def export_vm_state_package(
    backend: Any,
    vm_name: str,
    output_dir: str | Path,
    *,
    target_vm_name: str = "",
) -> dict[str, Any]:
    """Freeze a RUNNING VM, dump its full RAM+CPU state, and package it with
    its disk(s) so it can continue (not reboot) on another host.

    The source VM ends shut off but defined; its exact running state lives in
    the package. Nothing is deleted.
    """
    vm_name = validate_vm_name(vm_name)
    summary = backend.get_vm(vm_name)
    state = str(summary.state or "").lower()
    if state not in {"running", "paused"}:
        raise HyperGeryError(
            f"State migration needs a running (or paused) VM; {vm_name} is '{state}'. "
            "Use the regular teleport for a shut-off VM."
        )
    target_vm_name = validate_vm_name(target_vm_name or vm_name)
    package = Path(output_dir).expanduser() / f"state-{vm_name}"
    if package.exists():
        raise HyperGeryError(f"State package directory already exists: {package}")
    (package / "disks").mkdir(parents=True)

    # Capture the live domain XML before saving (save leaves it defined/off).
    dump = backend.virsh(["dumpxml", vm_name], check=False)
    if dump.returncode != 0:
        raise HyperGeryError(f"Cannot read domain XML for {vm_name}: {dump.stderr.strip()}")
    (package / DOMAIN_FILENAME).write_text(dump.stdout, encoding="utf-8")

    # Freeze + dump RAM/CPU state. After this the VM is shut off but its exact
    # running state is in the file.
    backend.save_vm(vm_name, package / MEMSTATE_FILENAME)

    root = ET.fromstring(dump.stdout)
    disk_assets: list[dict[str, str]] = []
    for disk in root.findall("./devices/disk"):
        if disk.get("device") != "disk":
            continue
        source = disk.find("source")
        if source is None or not source.attrib.get("file"):
            continue
        original = source.attrib["file"]
        if not Path(original).is_file():
            raise HyperGeryError(f"VM disk not found, cannot package state: {original}")
        rel = f"disks/{Path(original).name}"
        shutil.copy2(original, package / rel)
        disk_assets.append({"original": original, "relative_path": rel})

    manifest = {
        "schema_version": STATE_PACKAGE_VERSION,
        "kind": "state_migration",
        "source_vm_name": vm_name,
        "target_vm_name": target_vm_name,
        "lab_id": summary.lab_id or "default-lab",
        "memory_state": MEMSTATE_FILENAME,
        "domain_xml": DOMAIN_FILENAME,
        "disks": disk_assets,
        "created_at": now_iso(),
        "source_will_be_deleted": False,
    }
    (package / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    get_logger().info(
        "teleport",
        f"state package exported for {vm_name} ({len(disk_assets)} disk(s))",
        vm_id=vm_name,
        details={"package": str(package)},
    )
    return {"package_dir": str(package), "manifest": manifest}


def validate_state_package(package_dir: str | Path) -> dict[str, Any]:
    package = Path(package_dir).expanduser()
    errors: list[str] = []
    manifest_path = package / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {"ok": False, "errors": [f"Missing {MANIFEST_FILENAME}"], "manifest": None}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"Invalid manifest: {exc}"], "manifest": None}
    if manifest.get("kind") != "state_migration":
        errors.append("Not a state migration package.")
    if manifest.get("source_will_be_deleted") is not False:
        errors.append("Manifest must declare source_will_be_deleted=false.")

    def _check_member(rel: str, missing_message: str) -> None:
        try:
            member = safe_package_member(package, rel)
        except HyperGeryError as exc:
            errors.append(str(exc))
            return
        if not member.is_file():
            errors.append(missing_message)

    _check_member(str(manifest.get("memory_state") or ""), "Memory state file missing.")
    _check_member(str(manifest.get("domain_xml") or ""), "Domain XML missing.")
    for asset in manifest.get("disks", []):
        rel = str(asset.get("relative_path") or "")
        _check_member(rel, f"Disk asset missing: {asset.get('relative_path')}")
    return {"ok": not errors, "errors": errors, "manifest": manifest}


def import_vm_state_package(
    backend: Any,
    package_dir: str | Path,
    *,
    target_lab_id: str = "",
) -> dict[str, Any]:
    """Restore a state package on this host: the VM CONTINUES from its saved
    RAM+CPU state (not a reboot). Disk paths and network are rewritten for this
    host, but the guest identity — name and UUID — is preserved, because
    libvirt restore requires it (it is, after all, the SAME VM continuing
    elsewhere). The target host must not already have a domain with that name;
    that holds for a real move between two machines."""
    validation = validate_state_package(package_dir)
    if not validation["ok"]:
        raise HyperGeryError("Invalid state package: " + "; ".join(validation["errors"]))
    package = Path(package_dir).expanduser().resolve()
    manifest = validation["manifest"]
    # State migration preserves identity: the restored VM keeps the source
    # name/UUID (libvirt restore does not allow changing them).
    target_vm_name = validate_vm_name(manifest["source_vm_name"])

    exists = backend.virsh(["dominfo", target_vm_name], check=False)
    if exists.returncode == 0:
        raise HyperGeryError(
            f"This host already has a VM named {target_vm_name}; a state migration keeps the "
            "original name, so the target host must not already define it."
        )

    disk_dir = backend.vms_dir / target_vm_name
    if disk_dir.exists():
        raise HyperGeryError(f"Target VM disk directory already exists: {disk_dir}")
    disk_dir.mkdir(parents=True)
    created: list[Path] = [disk_dir]

    domain_xml_path = safe_package_member(package, str(manifest["domain_xml"]))
    root = ET.fromstring(domain_xml_path.read_text(encoding="utf-8"))
    name_el = root.find("name")
    if name_el is None:
        name_el = ET.SubElement(root, "name")
    name_el.text = target_vm_name

    # Rewrite disk sources to the copies on this host (keep UUID/MAC: restore
    # requires the saved domain's identity, and the source is stopped so there
    # is no collision).
    original_to_rel = {asset["original"]: asset["relative_path"] for asset in manifest.get("disks", [])}
    copied_disks: list[str] = []
    for disk in root.findall("./devices/disk"):
        if disk.get("device") != "disk":
            continue
        source = disk.find("source")
        if source is None:
            continue
        original = source.attrib.get("file", "")
        rel = original_to_rel.get(original)
        if not rel:
            continue
        member = safe_package_member(package, str(rel))
        destination = disk_dir / member.name
        shutil.copy2(member, destination)
        created.append(destination)
        source.attrib["file"] = str(destination)
        copied_disks.append(str(destination))

    lab_id = validate_lab_id(target_lab_id or manifest.get("lab_id") or "default-lab")
    network_id = backend.ensure_network(lab_id, "nat")
    iface_source = root.find("./devices/interface/source")
    if iface_source is not None:
        iface_source.attrib["network"] = network_id

    target_xml_path = package / "target-domain.xml"
    target_xml_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")

    try:
        media = [Path(p) for p in copied_disks]
        if media and hasattr(backend, "grant_libvirt_qemu_access"):
            backend.grant_libvirt_qemu_access(*media)
        # The VM comes up RUNNING, continuing from the saved state.
        memstate_path = safe_package_member(package, str(manifest["memory_state"]))
        backend.restore_vm(memstate_path, xml_path=target_xml_path)
        if hasattr(backend, "update_lab_for_vm"):
            backend.update_lab_for_vm(lab_id, target_vm_name, copied_disks[0] if copied_disks else "", "", network_id)
    except Exception:
        for path in reversed(created):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    get_logger().info(
        "teleport",
        f"state package restored as {target_vm_name} (continued from saved RAM state)",
        vm_id=target_vm_name,
        details={"disks": copied_disks},
    )
    return {
        "imported": True,
        "restored": True,
        "target_vm_name": target_vm_name,
        "target_lab_id": lab_id,
        "disks": copied_disks,
        "source_will_be_deleted": False,
        "state_preserved": True,
    }
