from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .backend import HG_NS, HyperGeryError, now_iso, validate_lab_id, validate_vm_name
from .labs import LabStore
from .templates import TemplateStore


MIGRATION_SCHEMA_VERSION = 1
PACKAGE_ROOT_NAME = "migrations"
REMOTE_MIGRATION_STEPS = [
    "preflight",
    "packaging",
    "uploaded",
    "waiting_target",
    "importing",
    "defining_vm",
    "done",
    "failed",
]


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_info(path: Path) -> dict:
    resolved = path.expanduser().resolve()
    exists = resolved.is_file()
    return {
        "path": str(resolved),
        "exists": exists,
        "size_bytes": resolved.stat().st_size if exists else 0,
    }


def _copy_file(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "package_path": str(destination),
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
    }


def _unique_name(existing: set[str], preferred: str) -> str:
    if preferred not in existing:
        existing.add(preferred)
        return preferred
    stem = Path(preferred).stem or "asset"
    suffix = Path(preferred).suffix
    index = 2
    while True:
        candidate = f"{stem}-{index}{suffix}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        index += 1


def _parse_domain_xml(xml: str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise HyperGeryError(f"Cannot parse libvirt domain XML: {exc}") from exc


def _domain_media_assets(xml: str, *, include_iso: bool) -> list[dict]:
    root = _parse_domain_xml(xml)
    assets: list[dict] = []
    for index, disk in enumerate(root.findall("./devices/disk")):
        source = disk.find("source")
        if source is None:
            continue
        source_path = source.attrib.get("file", "")
        if not source_path:
            continue
        device = disk.attrib.get("device", "disk")
        if device == "cdrom" and not include_iso:
            continue
        if device not in {"disk", "cdrom"}:
            continue
        target = disk.find("target")
        target_dev = target.attrib.get("dev", "") if target is not None else ""
        asset_type = "iso" if device == "cdrom" else "disk"
        info = _file_info(Path(source_path))
        assets.append(
            {
                "id": f"{asset_type}-{index}",
                "type": asset_type,
                "device": device,
                "target_dev": target_dev,
                "driver_type": (disk.find("driver").attrib.get("type", "") if disk.find("driver") is not None else ""),
                **info,
            }
        )
    return assets


def _snapshot_assets(backend: object, vm_name: str) -> tuple[list[dict], list[dict]]:
    snapshots: list[dict] = []
    assets: list[dict] = []
    try:
        names = backend.list_snapshots(vm_name)
    except Exception as exc:
        snapshots.append({"name": "", "error": f"Cannot list snapshots: {exc}"})
        return snapshots, assets
    for snapshot_name in names:
        entry: dict = {"name": snapshot_name}
        result = backend.virsh(["snapshot-dumpxml", "--domain", vm_name, snapshot_name], check=False)
        if result.returncode != 0:
            entry["warning"] = result.stderr.strip() or result.stdout.strip() or "Cannot dump snapshot XML."
            snapshots.append(entry)
            continue
        entry["xml"] = result.stdout
        snapshots.append(entry)
        try:
            root = ET.fromstring(result.stdout)
        except ET.ParseError:
            continue
        for index, source in enumerate(root.findall(".//disks/disk/source")):
            file_path = source.attrib.get("file", "")
            if not file_path:
                continue
            info = _file_info(Path(file_path))
            assets.append(
                {
                    "id": f"snapshot-{snapshot_name}-{index}",
                    "type": "snapshot",
                    "snapshot_name": snapshot_name,
                    **info,
                }
            )
    return snapshots, assets


def collect_vm_assets(
    backend: object,
    vm_name: str,
    *,
    include_iso: bool = True,
    include_snapshots: bool = True,
) -> dict:
    vm_name = validate_vm_name(vm_name)
    vm = backend.get_vm(vm_name)
    assets = _domain_media_assets(vm.xml, include_iso=include_iso)
    snapshots: list[dict] = []
    if include_snapshots:
        snapshots, snapshot_assets = _snapshot_assets(backend, vm_name)
        assets.extend(snapshot_assets)
    return {
        "vm": {
            "name": vm.name,
            "state": vm.state,
            "lab_id": vm.lab_id,
            "ram_mib": vm.ram_mib,
            "vcpus": vm.vcpus,
            "network": vm.network,
            "graphics": vm.graphics,
        },
        "assets": assets,
        "snapshots": snapshots,
    }


def estimate_migration_size(
    backend: object,
    vm_name: str,
    *,
    include_iso: bool = True,
    include_snapshots: bool = True,
) -> int:
    data = collect_vm_assets(backend, vm_name, include_iso=include_iso, include_snapshots=include_snapshots)
    return sum(int(asset.get("size_bytes", 0)) for asset in data["assets"] if asset.get("exists"))


def _read_optional_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _template_metadata(data_dir: Path, lab_manifest: dict | None) -> dict:
    templates: dict[str, dict] = {"lab": {}, "vm": {}}
    if not lab_manifest:
        return templates
    store = TemplateStore(data_dir)
    for template_id in lab_manifest.get("templates_used", []):
        try:
            lab_template = store.get_lab_template(template_id)
        except HyperGeryError:
            continue
        templates["lab"][template_id] = lab_template
        for planned in lab_template.get("vms", []):
            vm_template_id = planned.get("template_id", "")
            if not vm_template_id or vm_template_id in templates["vm"]:
                continue
            try:
                templates["vm"][vm_template_id] = store.get_vm_template(vm_template_id)
            except HyperGeryError:
                continue
    return templates


def _lab_metadata(backend: object, lab_id: str) -> dict | None:
    if not lab_id:
        return None
    try:
        return LabStore(backend.data_dir).get_lab(lab_id)
    except HyperGeryError:
        return None


def migration_preflight(
    backend: object,
    vm_name: str,
    *,
    target_host: str = "",
    target_vm_name: str = "",
    nas_path: str = "",
    allow_paused: bool = False,
    include_iso: bool = True,
    include_snapshots: bool = True,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    assets: list[dict] = []
    vm_data: dict = {}

    try:
        collected = collect_vm_assets(backend, vm_name, include_iso=include_iso, include_snapshots=include_snapshots)
        vm_data = collected["vm"]
        assets = collected["assets"]
    except HyperGeryError as exc:
        errors.append(str(exc))

    state = str(vm_data.get("state", "")).lower()
    if state == "running":
        errors.append("Running VM migration is blocked; shut down or pause the VM before packaging.")
    elif state == "paused" and not allow_paused:
        errors.append("Paused VM packaging requires --allow-paused.")
    elif state == "paused":
        warnings.append("Packaging a paused VM is allowed, but offline shutoff packaging is safer.")
    elif state and state != "shut off":
        warnings.append(f"VM state is '{vm_data.get('state')}', not 'shut off'.")

    for asset in assets:
        path = asset.get("path", "")
        if not asset.get("exists"):
            if asset.get("type") == "iso":
                errors.append(f"Attached ISO media is missing: {path}")
            else:
                errors.append(f"Required VM asset is missing: {path}")

    snapshots = []
    if vm_data:
        try:
            snapshots = backend.list_snapshots(vm_name)
        except Exception as exc:
            warnings.append(f"Cannot inspect snapshots: {exc}")
    if snapshots:
        warnings.append(f"VM has {len(snapshots)} snapshot(s); validate import behavior before deleting any source resources.")

    estimated_size = sum(int(asset.get("size_bytes", 0)) for asset in assets if asset.get("exists"))
    if nas_path:
        staging = Path(nas_path).expanduser()
        try:
            staging.mkdir(parents=True, exist_ok=True)
            if not os.access(staging, os.W_OK):
                errors.append(f"NAS staging path is not writable: {staging}")
            free = shutil.disk_usage(staging).free
            if free < estimated_size:
                errors.append(f"NAS staging path has insufficient free space: {staging}")
        except OSError as exc:
            errors.append(f"Cannot use NAS staging path {staging}: {exc}")

    if target_vm_name:
        try:
            target_vm_name = validate_vm_name(target_vm_name)
            result = backend.virsh(["dominfo", target_vm_name], check=False)
            if result.returncode == 0:
                errors.append(f"Target VM name already exists locally: {target_vm_name}")
        except HyperGeryError as exc:
            errors.append(str(exc))

    preflight_items = []
    try:
        preflight_items = [item.__dict__ for item in backend.preflight()]
        for item in preflight_items:
            if item.get("status") == "Error" and item.get("name") in {"libvirt connection", "qemu-img"}:
                errors.append(f"Host preflight failed: {item.get('name')}: {item.get('detail')}")
            elif item.get("status") == "Warning":
                warnings.append(f"Host preflight warning: {item.get('name')}: {item.get('detail')}")
    except Exception as exc:
        warnings.append(f"Host preflight could not run: {exc}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "vm": vm_data,
        "assets": assets,
        "estimated_size_bytes": estimated_size,
        "target_host": target_host,
        "target_vm_name": target_vm_name or "",
        "strategy": "offline-copy",
        "source_will_be_deleted": False,
        "preflight": preflight_items,
    }


def create_migration_manifest(
    backend: object,
    vm_name: str,
    *,
    migration_id: str,
    target_vm_name: str = "",
    include_iso: bool = True,
    include_snapshots: bool = True,
) -> dict:
    collected = collect_vm_assets(backend, vm_name, include_iso=include_iso, include_snapshots=include_snapshots)
    vm = backend.get_vm(vm_name)
    lab_manifest = _lab_metadata(backend, vm.lab_id)
    return {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "migration_id": migration_id,
        "created_at": now_iso(),
        "strategy": "offline-copy",
        "source_will_be_deleted": False,
        "source_vm_name": vm.name,
        "target_vm_name": target_vm_name or vm.name,
        "vm": collected["vm"],
        "assets": collected["assets"],
        "snapshots": collected["snapshots"],
        "lab": lab_manifest,
        "templates": _template_metadata(backend.data_dir, lab_manifest),
    }


def export_vm_package(
    backend: object,
    vm_name: str,
    output_dir: str | Path,
    *,
    migration_id: str = "",
    target_vm_name: str = "",
    allow_paused: bool = False,
    include_iso: bool = True,
    include_snapshots: bool = True,
) -> dict:
    vm_name = validate_vm_name(vm_name)
    preflight = migration_preflight(
        backend,
        vm_name,
        target_vm_name=target_vm_name,
        nas_path=str(output_dir),
        allow_paused=allow_paused,
        include_iso=include_iso,
        include_snapshots=include_snapshots,
    )
    if not preflight["ok"]:
        raise HyperGeryError("Migration preflight failed: " + "; ".join(preflight["errors"]))

    migration_id = migration_id or f"{vm_name}-{uuid.uuid4().hex[:12]}"
    package_dir = Path(output_dir).expanduser().resolve() / PACKAGE_ROOT_NAME / migration_id
    package_dir.mkdir(parents=True, exist_ok=False)
    manifest = create_migration_manifest(
        backend,
        vm_name,
        migration_id=migration_id,
        target_vm_name=target_vm_name,
        include_iso=include_iso,
        include_snapshots=include_snapshots,
    )
    vm = backend.get_vm(vm_name)
    (package_dir / "logs").mkdir(parents=True, exist_ok=True)
    (package_dir / "domain.xml").write_text(vm.xml, encoding="utf-8")
    (package_dir / "logs" / "migration.log").write_text(
        f"{now_iso()} exported source_vm={vm_name} strategy=offline-copy source_will_be_deleted=false\n",
        encoding="utf-8",
    )

    used_names: dict[str, set[str]] = {"disk": set(), "iso": set(), "snapshot": set()}
    for asset in manifest["assets"]:
        if not asset.get("exists"):
            continue
        asset_type = asset["type"]
        source = Path(asset["path"])
        subdir = {"disk": "disks", "iso": "isos", "snapshot": "snapshots"}[asset_type]
        filename = _unique_name(used_names[asset_type], source.name)
        destination = package_dir / subdir / filename
        copied = _copy_file(source, destination)
        asset["relative_path"] = str(destination.relative_to(package_dir))
        asset["package_size_bytes"] = copied["size_bytes"]
        asset["sha256"] = copied["sha256"]

    lab = manifest.get("lab")
    if lab:
        lab_dir = package_dir / "labs"
        lab_dir.mkdir(parents=True, exist_ok=True)
        (lab_dir / "lab.json").write_text(json.dumps(lab, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    template_dir = package_dir / "templates"
    for kind, entries in manifest.get("templates", {}).items():
        for template_id, template in entries.items():
            destination = template_dir / kind / f"{template_id}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    (package_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logging.info("exported migration package vm=%s package=%s", vm_name, package_dir)
    return {
        "migration_id": migration_id,
        "package_dir": str(package_dir),
        "manifest": manifest,
        "preflight": preflight,
    }


def validate_vm_package(package_dir: str | Path) -> dict:
    package = Path(package_dir).expanduser().resolve()
    manifest_path = package / "manifest.json"
    errors: list[str] = []
    warnings: list[str] = []
    manifest = _read_optional_json(manifest_path)
    if manifest is None:
        return {"ok": False, "errors": [f"Invalid or missing manifest: {manifest_path}"], "warnings": [], "manifest": None}
    if manifest.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        errors.append(f"Unsupported migration schema version: {manifest.get('schema_version')}")
    if manifest.get("source_will_be_deleted") is not False:
        errors.append("Package manifest must declare source_will_be_deleted=false.")
    for asset in manifest.get("assets", []):
        rel = asset.get("relative_path", "")
        if not rel:
            if asset.get("exists") is False and asset.get("type") == "iso":
                warnings.append(f"Missing optional ISO was not packaged: {asset.get('path', '')}")
                continue
            errors.append(f"Asset has no package path: {asset.get('path', '')}")
            continue
        path = package / rel
        if not path.is_file():
            errors.append(f"Packaged asset is missing: {rel}")
            continue
        expected_size = int(asset.get("package_size_bytes", asset.get("size_bytes", 0)))
        if path.stat().st_size != expected_size:
            errors.append(f"Packaged asset size mismatch: {rel}")
        expected_sha = asset.get("sha256", "")
        if expected_sha and _sha256(path) != expected_sha:
            errors.append(f"Packaged asset checksum mismatch: {rel}")
    if not (package / "domain.xml").is_file():
        errors.append("Package is missing domain.xml.")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "manifest": manifest}


def generate_target_vm_identity(xml: str, target_vm_name: str) -> dict:
    validate_vm_name(target_vm_name)
    root = _parse_domain_xml(xml)
    name_el = root.find("name")
    if name_el is None:
        name_el = ET.SubElement(root, "name")
    name_el.text = target_vm_name
    uuid_el = root.find("uuid")
    new_uuid = str(uuid.uuid4())
    if uuid_el is None:
        uuid_el = ET.SubElement(root, "uuid")
    uuid_el.text = new_uuid
    macs: list[str] = []
    for mac in root.findall("./devices/interface/mac"):
        generated = _generate_mac()
        mac.attrib["address"] = generated
        macs.append(generated)
    if not macs:
        for iface in root.findall("./devices/interface"):
            generated = _generate_mac()
            ET.SubElement(iface, "mac", {"address": generated})
            macs.append(generated)
    return {"xml": ET.tostring(root, encoding="unicode"), "uuid": new_uuid, "mac_addresses": macs}


def _generate_mac() -> str:
    raw = uuid.uuid4().bytes
    return "52:54:%02x:%02x:%02x:%02x" % (raw[0], raw[1], raw[2], raw[3])


def _set_hg_metadata(root: ET.Element, updates: dict[str, str]) -> None:
    metadata = root.find("metadata")
    if metadata is None:
        metadata = ET.SubElement(root, "metadata")
    hg = metadata.find(f"{{{HG_NS}}}hypergery")
    if hg is None:
        hg = ET.SubElement(metadata, f"{{{HG_NS}}}hypergery")
    for key, value in updates.items():
        child = hg.find(f"{{{HG_NS}}}{key}")
        if child is None:
            child = ET.SubElement(hg, f"{{{HG_NS}}}{key}")
        child.text = value


def cleanup_failed_migration(paths: list[Path], backend: object | None = None, target_vm_name: str = "") -> list[str]:
    errors: list[str] = []
    if backend is not None and target_vm_name:
        try:
            result = backend.virsh(["dominfo", target_vm_name], check=False)
            if result.returncode == 0:
                backend.undefine_domain(target_vm_name)
        except Exception as exc:
            errors.append(f"Could not undefine partial VM {target_vm_name}: {exc}")
    for path in reversed(paths):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"Could not remove partial path {path}: {exc}")
    return errors


def import_vm_package(
    backend: object,
    package_dir: str | Path,
    *,
    target_vm_name: str = "",
    target_lab_id: str = "",
) -> dict:
    validation = validate_vm_package(package_dir)
    if not validation["ok"]:
        raise HyperGeryError("Invalid migration package: " + "; ".join(validation["errors"]))
    package = Path(package_dir).expanduser().resolve()
    manifest = validation["manifest"]
    target_vm_name = validate_vm_name(target_vm_name or manifest["target_vm_name"])
    result = backend.virsh(["dominfo", target_vm_name], check=False)
    if result.returncode == 0:
        raise HyperGeryError(f"Target VM already exists: {target_vm_name}")

    created_paths: list[Path] = []
    disk_dir = backend.vms_dir / target_vm_name
    if disk_dir.exists():
        raise HyperGeryError(f"Target VM disk directory already exists: {disk_dir}")
    disk_dir.mkdir(parents=True)
    created_paths.append(disk_dir)
    iso_dir = backend.data_dir / "isos"
    iso_dir.mkdir(parents=True, exist_ok=True)

    root = _parse_domain_xml((package / "domain.xml").read_text(encoding="utf-8"))
    name_el = root.find("name")
    if name_el is None:
        name_el = ET.SubElement(root, "name")
    name_el.text = target_vm_name
    uuid_el = root.find("uuid")
    if uuid_el is None:
        uuid_el = ET.SubElement(root, "uuid")
    uuid_el.text = str(uuid.uuid4())
    for mac in root.findall("./devices/interface/mac"):
        mac.attrib["address"] = _generate_mac()
    for iface in root.findall("./devices/interface"):
        if iface.find("mac") is None:
            ET.SubElement(iface, "mac", {"address": _generate_mac()})

    copied_disks: list[str] = []
    copied_isos: list[str] = []
    asset_by_path = {asset.get("path", ""): asset for asset in manifest.get("assets", [])}
    for disk in root.findall("./devices/disk"):
        source = disk.find("source")
        if source is None:
            continue
        original = source.attrib.get("file", "")
        asset = asset_by_path.get(original)
        if not asset or not asset.get("relative_path"):
            continue
        package_asset = package / asset["relative_path"]
        if asset["type"] == "disk":
            destination = disk_dir / package_asset.name
            shutil.copy2(package_asset, destination)
            created_paths.append(destination)
            source.attrib["file"] = str(destination)
            copied_disks.append(str(destination))
        elif asset["type"] == "iso":
            destination = iso_dir / package_asset.name
            if not destination.exists():
                shutil.copy2(package_asset, destination)
                created_paths.append(destination)
            source.attrib["file"] = str(destination)
            copied_isos.append(str(destination))

    lab_id = target_lab_id or (manifest.get("lab") or {}).get("lab_id") or "default-lab"
    lab_id = validate_lab_id(lab_id)
    network_mode = (manifest.get("lab") or {}).get("network_mode", "nat")
    network_id = backend.ensure_network(lab_id, network_mode)
    iface_source = root.find("./devices/interface/source")
    if iface_source is not None:
        iface_source.attrib["network"] = network_id
    _set_hg_metadata(
        root,
        {
            "managed": "true",
            "lab_id": lab_id,
            "disk_path": copied_disks[0] if copied_disks else "",
            "iso_path": copied_isos[0] if copied_isos else "",
            "network_id": network_id,
            "migration_id": manifest["migration_id"],
            "source_vm_name": manifest["source_vm_name"],
            "imported_at": now_iso(),
        },
    )
    xml = ET.tostring(root, encoding="unicode")

    try:
        media_paths = [Path(path) for path in copied_disks + copied_isos]
        if media_paths and hasattr(backend, "grant_libvirt_qemu_access"):
            backend.grant_libvirt_qemu_access(*media_paths)
        backend.define_domain_xml(xml)
        backend.update_lab_for_vm(
            lab_id,
            target_vm_name,
            copied_disks[0] if copied_disks else "",
            copied_isos[0] if copied_isos else "",
            network_id,
        )
    except Exception:
        cleanup_failed_migration(created_paths, backend=backend, target_vm_name=target_vm_name)
        raise

    logging.info("imported migration package vm=%s package=%s", target_vm_name, package)
    return {
        "imported": True,
        "migration_id": manifest["migration_id"],
        "target_vm_name": target_vm_name,
        "target_lab_id": lab_id,
        "disks": copied_disks,
        "isos": copied_isos,
        "source_will_be_deleted": False,
        "validation_warnings": validation["warnings"],
    }


def list_migration_packages(path: str | Path) -> list[dict]:
    root = Path(path).expanduser()
    packages_root = root / PACKAGE_ROOT_NAME if (root / PACKAGE_ROOT_NAME).is_dir() else root
    results: list[dict] = []
    for manifest_path in sorted(packages_root.glob("*/manifest.json")):
        manifest = _read_optional_json(manifest_path)
        if not manifest:
            continue
        results.append(
            {
                "migration_id": manifest.get("migration_id", ""),
                "source_vm_name": manifest.get("source_vm_name", ""),
                "target_vm_name": manifest.get("target_vm_name", ""),
                "created_at": manifest.get("created_at", ""),
                "package_dir": str(manifest_path.parent),
            }
        )
    return results


def _migration_status_payload(
    *,
    source_host_id: str,
    target_host_id: str,
    source_vm_name: str,
    target_vm_name: str,
    status: str,
    package_path: str = "",
    result: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source_host_id": source_host_id,
        "target_host_id": target_host_id,
        "source_vm_name": source_vm_name,
        "target_vm_name": target_vm_name,
        "strategy": "nas_clone",
        "status": status,
        "package_path": package_path,
        "result": result or {},
        "errors": errors or [],
        "warnings": warnings or [],
    }


def create_remote_import_command(
    client: object,
    *,
    migration_id: str,
    source_host_id: str,
    target_host_id: str,
    source_vm_name: str,
    target_vm_name: str,
    package_dir: str,
    target_lab_id: str = "",
    start_after_import: bool = False,
) -> dict[str, Any]:
    if not target_host_id:
        raise HyperGeryError("target_host_id is required.")
    if not package_dir:
        raise HyperGeryError("package_dir is required.")
    command = client.create_command(
        target_host_id,
        "import_vm_package",
        {
            "migration_id": migration_id,
            "source_host_id": source_host_id,
            "source_vm_name": source_vm_name,
            "package_dir": package_dir,
            "target_vm_name": target_vm_name,
            "target_lab_id": target_lab_id,
            "start_after_import": start_after_import,
        },
    )
    client.update_migration_status(
        migration_id,
        _migration_status_payload(
            source_host_id=source_host_id,
            target_host_id=target_host_id,
            source_vm_name=source_vm_name,
            target_vm_name=target_vm_name,
            status="waiting_target",
            package_path=package_dir,
            result={"package_dir": package_dir, "command_id": command["command_id"]},
        ),
    )
    return command


def start_remote_migration(
    backend: object,
    client: object,
    vm_name: str,
    nas_path: str | Path,
    *,
    source_host_id: str,
    target_host_id: str,
    target_vm_name: str = "",
    target_lab_id: str = "",
    allow_paused: bool = False,
    include_iso: bool = True,
    include_snapshots: bool = True,
    start_after_import: bool = False,
) -> dict[str, Any]:
    if not source_host_id:
        raise HyperGeryError("source_host_id is required.")
    if not target_host_id:
        raise HyperGeryError("target_host_id is required.")
    target_host = client.get_host(target_host_id)
    if target_host.get("status") != "online":
        raise HyperGeryError(f"Target host is offline: {target_host_id}")
    if not target_host.get("kvm_ok") or not target_host.get("libvirt_ok"):
        raise HyperGeryError(f"Target host is not ready for KVM/libvirt import: {target_host_id}")

    target_vm_name = target_vm_name or vm_name
    preflight = migration_preflight(
        backend,
        vm_name,
        target_host=target_host_id,
        target_vm_name=target_vm_name,
        nas_path=str(nas_path),
        allow_paused=allow_paused,
        include_iso=include_iso,
        include_snapshots=include_snapshots,
    )
    migration_id = f"{vm_name}-{uuid.uuid4().hex[:12]}"
    client.update_migration_status(
        migration_id,
        _migration_status_payload(
            source_host_id=source_host_id,
            target_host_id=target_host_id,
            source_vm_name=vm_name,
            target_vm_name=target_vm_name,
            status="preflight",
            result={"preflight": preflight},
            errors=preflight["errors"],
            warnings=preflight["warnings"],
        ),
    )
    if not preflight["ok"]:
        client.update_migration_status(
            migration_id,
            _migration_status_payload(
                source_host_id=source_host_id,
                target_host_id=target_host_id,
                source_vm_name=vm_name,
                target_vm_name=target_vm_name,
                status="failed",
                result={"preflight": preflight},
                errors=preflight["errors"],
                warnings=preflight["warnings"],
            ),
        )
        raise HyperGeryError("Migration preflight failed: " + "; ".join(preflight["errors"]))

    client.update_migration_status(
        migration_id,
        _migration_status_payload(
            source_host_id=source_host_id,
            target_host_id=target_host_id,
            source_vm_name=vm_name,
            target_vm_name=target_vm_name,
            status="packaging",
            result={"preflight": preflight},
            warnings=preflight["warnings"],
        ),
    )
    exported = export_vm_package(
        backend,
        vm_name,
        nas_path,
        target_vm_name=target_vm_name,
        allow_paused=allow_paused,
        include_iso=include_iso,
        include_snapshots=include_snapshots,
        migration_id=migration_id,
    )
    package_dir = exported["package_dir"]
    client.update_migration_status(
        migration_id,
        _migration_status_payload(
            source_host_id=source_host_id,
            target_host_id=target_host_id,
            source_vm_name=vm_name,
            target_vm_name=target_vm_name,
            status="uploaded",
            package_path=package_dir,
            result={"package_dir": package_dir, "preflight": preflight},
            warnings=preflight["warnings"],
        ),
    )
    command = create_remote_import_command(
        client,
        migration_id=migration_id,
        source_host_id=source_host_id,
        target_host_id=target_host_id,
        source_vm_name=vm_name,
        target_vm_name=target_vm_name,
        package_dir=package_dir,
        target_lab_id=target_lab_id,
        start_after_import=start_after_import,
    )
    return {
        "migration_id": migration_id,
        "command_id": command["command_id"],
        "package_dir": package_dir,
        "source_will_be_deleted": False,
        "steps": REMOTE_MIGRATION_STEPS,
        "preflight": preflight,
    }


def poll_remote_migration_status(client: object, migration_id: str) -> dict[str, Any]:
    migration = client.migration(migration_id)
    result = dict(migration.get("result") or {})
    command_id = result.get("command_id", "")
    command: dict[str, Any] | None = None
    if command_id:
        command = client.command(command_id)
        command_status = command.get("status")
        if command_status == "pending":
            status = "waiting_target"
        elif command_status == "running":
            status = "importing"
        elif command_status == "done":
            status = "done"
        elif command_status == "failed":
            status = "failed"
        else:
            status = str(migration.get("status") or "created")
        if status != migration.get("status"):
            errors = []
            if status == "failed":
                error = (command.get("result") or {}).get("error", "Target import failed.")
                errors = [str(error)]
            migration = client.update_migration_status(
                migration_id,
                _migration_status_payload(
                    source_host_id=str(migration.get("source_host_id") or ""),
                    target_host_id=str(migration.get("target_host_id") or ""),
                    source_vm_name=str(migration.get("source_vm_name") or ""),
                    target_vm_name=str(migration.get("target_vm_name") or ""),
                    status=status,
                    result={**result, "command": command},
                    errors=errors,
                    warnings=list(migration.get("warnings") or []),
                ),
            )
    return {"migration": migration, "command": command, "steps": REMOTE_MIGRATION_STEPS}
