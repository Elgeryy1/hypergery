from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .backend import HyperGeryError, now_iso, validate_vm_name, xdg_data_home


LAB_SCHEMA_VERSION = 2
RESERVED_LAB_IDS = {"default", "root", "system", "libvirt", "qemu", "admin"}


def normalize_lab_id(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        raise HyperGeryError("Lab id cannot be empty after normalization.")
    return validate_lab_id(value)


def validate_lab_id(lab_id: str) -> str:
    clean = lab_id.strip()
    if clean in RESERVED_LAB_IDS:
        raise HyperGeryError(f"Lab id is reserved: {clean}")
    if clean.startswith("."):
        raise HyperGeryError("Lab id cannot start with a dot.")
    if ".." in clean or "/" in clean or "\\" in clean:
        raise HyperGeryError("Lab id cannot contain path traversal characters.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,46}[a-z0-9]", clean):
        raise HyperGeryError("Lab id must be 3-48 lowercase letters, numbers, and dashes, with no spaces.")
    return clean


def generate_lab_network_name(lab_id: str, network_mode: str = "nat") -> str:
    lab_id = validate_lab_id(lab_id)
    return f"hg-net-{lab_id}" if network_mode == "nat" else f"hg-net-{lab_id}-isolated"


def generate_lab_bridge_name(lab_id: str) -> str:
    import hashlib

    digest = hashlib.sha256(validate_lab_id(lab_id).encode("utf-8")).hexdigest()
    bridge = f"hgbr{digest[:7]}"
    if bridge == "virbr0" or len(bridge) > 15:
        raise HyperGeryError(f"Generated invalid bridge name: {bridge}")
    return bridge


def allocate_lab_subnet(lab_id: str, existing_subnets: set[str] | list[str] | tuple[str, ...] = ()) -> str:
    import hashlib

    existing = set(existing_subnets)
    seed = int(hashlib.sha256(validate_lab_id(lab_id).encode("utf-8")).hexdigest()[:4], 16)
    for offset in range(180):
        octet = 20 + ((seed + offset) % 180)
        if octet == 122:
            continue
        subnet = f"192.168.{octet}.0/24"
        if subnet not in existing:
            return subnet
    raise HyperGeryError("Could not allocate a non-conflicting lab subnet.")


def subnet_gateway(subnet: str) -> str:
    parts = subnet.split("/")
    octets = parts[0].split(".")
    if len(parts) != 2 or parts[1] != "24" or len(octets) != 4:
        raise HyperGeryError(f"Unsupported lab subnet format: {subnet}")
    return ".".join([octets[0], octets[1], octets[2], "1"])


@dataclass
class LabStore:
    data_dir: Path | None = None
    delete_vm_callback: object | None = None
    clone_vm_callback: object | None = None
    vm_state_callback: object | None = None

    def __post_init__(self) -> None:
        root = self.data_dir if self.data_dir is not None else xdg_data_home()
        self.root = Path(root)
        self.labs_dir = self.root / "labs"
        self.labs_dir.mkdir(parents=True, exist_ok=True)

    def lab_path(self, lab_id: str) -> Path:
        return self.labs_dir / validate_lab_id(lab_id) / "lab.json"

    def existing_subnets(self, exclude_lab_id: str = "") -> set[str]:
        subnets = set()
        for path in sorted(self.labs_dir.glob("*/lab.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("lab_id") != exclude_lab_id and manifest.get("subnet"):
                subnets.add(manifest["subnet"])
        return subnets

    def default_manifest(self, lab_id: str, name: str, description: str = "", network_mode: str = "nat") -> dict:
        lab_id = validate_lab_id(lab_id)
        if network_mode not in {"nat", "isolated"}:
            raise HyperGeryError("Network mode must be nat or isolated.")
        now = now_iso()
        subnet = allocate_lab_subnet(lab_id, self.existing_subnets(exclude_lab_id=lab_id))
        return {
            "schema_version": LAB_SCHEMA_VERSION,
            "lab_id": lab_id,
            "name": name.strip() or lab_id,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "network_id": generate_lab_network_name(lab_id, network_mode),
            "network_mode": network_mode,
            "subnet": subnet,
            "bridge_name": generate_lab_bridge_name(lab_id),
            "vms": [],
            "templates_used": [],
            "notes": "",
            "disks": [],
            "iso_references": [],
        }

    def migrate_manifest(self, manifest: dict) -> dict:
        raw_lab_id = manifest.get("lab_id") or manifest.get("name") or "default-lab"
        try:
            lab_id = validate_lab_id(str(raw_lab_id).lower())
        except HyperGeryError:
            lab_id = normalize_lab_id(str(raw_lab_id))
        network_mode = manifest.get("network_mode") or ("isolated" if str(manifest.get("network_id", "")).endswith("-isolated") else "nat")
        now = now_iso()
        migrated = self.default_manifest(
            lab_id,
            str(manifest.get("name") or ("Default Lab" if lab_id == "default-lab" else lab_id)),
            str(manifest.get("description") or ""),
            network_mode,
        )
        migrated.update({k: v for k, v in manifest.items() if k in migrated and v not in (None, "")})
        migrated["schema_version"] = LAB_SCHEMA_VERSION
        migrated["lab_id"] = lab_id
        migrated["updated_at"] = now
        migrated.setdefault("created_at", now)
        migrated["network_id"] = migrated.get("network_id") or generate_lab_network_name(lab_id, network_mode)
        migrated["bridge_name"] = migrated.get("bridge_name") or generate_lab_bridge_name(lab_id)
        migrated["subnet"] = migrated.get("subnet") or allocate_lab_subnet(lab_id, self.existing_subnets(exclude_lab_id=lab_id))
        migrated["vms"] = list(dict.fromkeys(migrated.get("vms", [])))
        migrated["templates_used"] = list(dict.fromkeys(migrated.get("templates_used", [])))
        return migrated

    def read_manifest(self, path: Path) -> dict:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Cannot read lab manifest {path}: {exc}") from exc
        migrated = self.migrate_manifest(manifest)
        if migrated != manifest:
            self.write_lab(migrated)
        return migrated

    def write_lab(self, manifest: dict) -> None:
        manifest = self.migrate_manifest(manifest)
        path = self.lab_path(manifest["lab_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def list_labs(self) -> list[dict]:
        labs = [self.read_manifest(path) for path in sorted(self.labs_dir.glob("*/lab.json"))]
        if not labs:
            labs.append(self.create_lab("Default Lab", notes="Default HyperGery lab."))
        return labs

    def create_lab(self, name: str, description: str = "", network_mode: str = "nat", *, lab_id: str | None = None, notes: str = "") -> dict:
        lab_id = validate_lab_id(lab_id) if lab_id else normalize_lab_id(name)
        path = self.lab_path(lab_id)
        if path.exists():
            raise HyperGeryError(f"Lab already exists: {lab_id}")
        manifest = self.default_manifest(lab_id, name, description, network_mode)
        manifest["notes"] = notes
        self.write_lab(manifest)
        return manifest

    def get_lab(self, lab_id: str) -> dict:
        path = self.lab_path(lab_id)
        if not path.exists():
            raise HyperGeryError(f"Lab does not exist: {lab_id}")
        return self.read_manifest(path)

    def rename_lab(self, lab_id: str, new_name: str) -> dict:
        manifest = self.get_lab(lab_id)
        new_lab_id = normalize_lab_id(new_name)
        if new_lab_id != manifest["lab_id"] and self.lab_path(new_lab_id).exists():
            raise HyperGeryError(f"Lab already exists: {new_lab_id}")
        old_dir = self.lab_path(manifest["lab_id"]).parent
        manifest["lab_id"] = new_lab_id
        manifest["name"] = new_name.strip() or new_lab_id
        manifest["network_id"] = generate_lab_network_name(new_lab_id, manifest.get("network_mode", "nat"))
        manifest["bridge_name"] = generate_lab_bridge_name(new_lab_id)
        manifest["updated_at"] = now_iso()
        if new_lab_id != lab_id:
            new_dir = self.lab_path(new_lab_id).parent
            new_dir.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(new_dir)
            old_dir.rename(new_dir)
        self.write_lab(manifest)
        return manifest

    def delete_lab(self, lab_id: str, delete_vms: bool = False) -> None:
        manifest = self.get_lab(lab_id)
        if delete_vms and self.delete_vm_callback is None and manifest.get("vms"):
            raise HyperGeryError("delete_vms=True requires a VM deletion backend callback.")
        if delete_vms:
            for vm_name in manifest.get("vms", []):
                self.delete_vm_callback(validate_vm_name(vm_name))
        shutil.rmtree(self.lab_path(lab_id).parent)

    def duplicate_lab(self, source_lab_id: str, new_name: str, clone_vms: bool = False) -> dict:
        source = self.get_lab(source_lab_id)
        if clone_vms:
            if self.clone_vm_callback is None or self.vm_state_callback is None:
                raise HyperGeryError("clone_vms=True requires VM state and clone callbacks.")
            for vm_name in source.get("vms", []):
                state = str(self.vm_state_callback(vm_name)).lower()
                if "running" in state or "paused" in state:
                    raise HyperGeryError(f"Cannot clone running VM: {vm_name}")
        duplicate = self.create_lab(new_name, source.get("description", ""), source.get("network_mode", "nat"))
        duplicate["notes"] = source.get("notes", "")
        duplicate["templates_used"] = list(source.get("templates_used", []))
        if clone_vms:
            for vm_name in source.get("vms", []):
                clone_name = f"{duplicate['lab_id']}-{vm_name}"
                self.clone_vm_callback(vm_name, clone_name)
                duplicate["vms"].append(clone_name)
        self.write_lab(duplicate)
        return duplicate

    def portable_manifest(self, manifest: dict) -> dict:
        portable = self.migrate_manifest(manifest)
        portable["disks"] = []
        portable["iso_references"] = []
        return portable

    def export_lab(self, lab_id: str, output_path: str | Path) -> Path:
        manifest = self.portable_manifest(self.get_lab(lab_id))
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output

    def import_lab(self, input_path: str | Path, new_lab_id: str | None = None) -> dict:
        path = Path(input_path).expanduser()
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Invalid lab import file: {exc}") from exc
        if not isinstance(manifest, dict) or "lab_id" not in manifest:
            raise HyperGeryError("Invalid lab import file: missing lab_id.")
        manifest = self.migrate_manifest(manifest)
        if new_lab_id:
            manifest["lab_id"] = validate_lab_id(new_lab_id)
            manifest["network_id"] = generate_lab_network_name(manifest["lab_id"], manifest.get("network_mode", "nat"))
            manifest["bridge_name"] = generate_lab_bridge_name(manifest["lab_id"])
        if self.lab_path(manifest["lab_id"]).exists():
            raise HyperGeryError(f"Lab already exists: {manifest['lab_id']}")
        manifest["updated_at"] = now_iso()
        self.write_lab(manifest)
        return manifest
