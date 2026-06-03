from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .backend import HyperGeryError, xdg_data_home
from .labs import validate_lab_id


VM_TEMPLATE_SCHEMA_VERSION = 1
LAB_TEMPLATE_SCHEMA_VERSION = 1


def normalize_template_id(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        raise HyperGeryError("Template id cannot be empty after normalization.")
    return validate_template_id(value)


def validate_template_id(template_id: str) -> str:
    clean = template_id.strip()
    if clean.startswith(".") or ".." in clean or "/" in clean or "\\" in clean:
        raise HyperGeryError("Template id cannot contain path traversal characters.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", clean):
        raise HyperGeryError("Template id must be 3-64 lowercase letters, numbers, and dashes.")
    return clean


def validate_vm_template(template: dict) -> dict:
    required = ("template_id", "name", "os_type", "ram_mib", "vcpus", "disk_gb", "network_mode", "display")
    for key in required:
        if key not in template:
            raise HyperGeryError(f"Invalid VM template: missing {key}.")
    template["template_id"] = validate_template_id(str(template["template_id"]))
    if template["os_type"] not in {"linux", "windows", "other"}:
        raise HyperGeryError("VM template os_type must be linux, windows, or other.")
    if template["network_mode"] not in {"nat", "isolated"}:
        raise HyperGeryError("VM template network_mode must be nat or isolated.")
    if template["display"] not in {"spice", "vnc"}:
        raise HyperGeryError("VM template display must be spice or vnc.")
    for key in ("ram_mib", "vcpus", "disk_gb"):
        template[key] = int(template[key])
        if template[key] < 1:
            raise HyperGeryError(f"VM template {key} must be positive.")
    template["schema_version"] = VM_TEMPLATE_SCHEMA_VERSION
    template.setdefault("notes", "")
    return template


def validate_lab_template(template: dict) -> dict:
    required = ("template_id", "name", "description", "network_mode", "vms")
    for key in required:
        if key not in template:
            raise HyperGeryError(f"Invalid lab template: missing {key}.")
    template["template_id"] = validate_template_id(str(template["template_id"]))
    if template["network_mode"] not in {"nat", "isolated"}:
        raise HyperGeryError("Lab template network_mode must be nat or isolated.")
    if not isinstance(template["vms"], list):
        raise HyperGeryError("Lab template vms must be a list.")
    for vm in template["vms"]:
        for key in ("name", "ram_mib", "vcpus", "disk_gb", "os_type", "display"):
            if key not in vm:
                raise HyperGeryError(f"Invalid lab template VM: missing {key}.")
        if "template_id" in vm and vm["template_id"]:
            vm["template_id"] = validate_template_id(str(vm["template_id"]))
        if vm["os_type"] not in {"linux", "windows", "other"}:
            raise HyperGeryError("Lab template VM os_type must be linux, windows, or other.")
        if vm["display"] not in {"spice", "vnc"}:
            raise HyperGeryError("Lab template VM display must be spice or vnc.")
        for key in ("ram_mib", "vcpus", "disk_gb"):
            vm[key] = int(vm[key])
            if vm[key] < 1:
                raise HyperGeryError(f"Lab template VM {key} must be positive.")
    template["schema_version"] = LAB_TEMPLATE_SCHEMA_VERSION
    template.setdefault("notes", "")
    return template


@dataclass
class TemplateStore:
    data_dir: Path | None = None
    backend: object | None = None
    lab_store: object | None = None

    def __post_init__(self) -> None:
        root = self.data_dir if self.data_dir is not None else xdg_data_home()
        self.root = Path(root)
        self.vm_dir = self.root / "templates" / "vm"
        self.lab_dir = self.root / "templates" / "lab"
        self.vm_dir.mkdir(parents=True, exist_ok=True)
        self.lab_dir.mkdir(parents=True, exist_ok=True)

    def vm_path(self, template_id: str) -> Path:
        return self.vm_dir / f"{validate_template_id(template_id)}.json"

    def lab_path(self, template_id: str) -> Path:
        return self.lab_dir / f"{validate_template_id(template_id)}.json"

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def read_json(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Invalid template file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise HyperGeryError(f"Invalid template file {path}: expected object.")
        return data

    def list_vm_templates(self) -> list[dict]:
        return [validate_vm_template(self.read_json(path)) for path in sorted(self.vm_dir.glob("*.json"))]

    def create_vm_template(
        self,
        name: str,
        *,
        os_type: str = "linux",
        ram_mib: int = 4096,
        vcpus: int = 2,
        disk_gb: int = 40,
        network_mode: str = "nat",
        display: str = "spice",
        notes: str = "",
        template_id: str | None = None,
    ) -> dict:
        template_id = validate_template_id(template_id) if template_id else normalize_template_id(name)
        path = self.vm_path(template_id)
        if path.exists():
            raise HyperGeryError(f"VM template already exists: {template_id}")
        template = validate_vm_template(
            {
                "schema_version": VM_TEMPLATE_SCHEMA_VERSION,
                "template_id": template_id,
                "name": name.strip() or template_id,
                "os_type": os_type,
                "ram_mib": ram_mib,
                "vcpus": vcpus,
                "disk_gb": disk_gb,
                "network_mode": network_mode,
                "display": display,
                "notes": notes,
            }
        )
        self.write_json(path, template)
        return template

    def create_vm_template_from_vm(self, vm_name: str, *, template_id: str | None = None, name: str | None = None) -> dict:
        if self.backend is None:
            raise HyperGeryError("create_vm_template_from_vm requires a backend.")
        vm = self.backend.get_vm(vm_name)
        return self.create_vm_template(
            name or vm.name,
            template_id=template_id,
            os_type=(vm.graphics and "linux") or "linux",
            ram_mib=vm.ram_mib or 4096,
            vcpus=vm.vcpus or 2,
            disk_gb=40,
            network_mode="isolated" if str(vm.network).endswith("-isolated") else "nat",
            display=vm.graphics if vm.graphics in {"spice", "vnc"} else "spice",
            notes="Created from existing VM without ISO path.",
        )

    def get_vm_template(self, template_id: str) -> dict:
        path = self.vm_path(template_id)
        if not path.exists():
            raise HyperGeryError(f"VM template does not exist: {template_id}")
        return validate_vm_template(self.read_json(path))

    def delete_vm_template(self, template_id: str) -> None:
        path = self.vm_path(template_id)
        if not path.exists():
            raise HyperGeryError(f"VM template does not exist: {template_id}")
        path.unlink()

    def list_lab_templates(self) -> list[dict]:
        return [validate_lab_template(self.read_json(path)) for path in sorted(self.lab_dir.glob("*.json"))]

    def create_lab_template(
        self,
        name: str,
        description: str = "",
        network_mode: str = "nat",
        vms: list[dict] | None = None,
        notes: str = "",
        template_id: str | None = None,
    ) -> dict:
        template_id = validate_template_id(template_id) if template_id else normalize_template_id(name)
        path = self.lab_path(template_id)
        if path.exists():
            raise HyperGeryError(f"Lab template already exists: {template_id}")
        template = validate_lab_template(
            {
                "schema_version": LAB_TEMPLATE_SCHEMA_VERSION,
                "template_id": template_id,
                "name": name.strip() or template_id,
                "description": description,
                "network_mode": network_mode,
                "vms": vms or [],
                "notes": notes,
            }
        )
        self.write_json(path, template)
        return template

    def create_lab_template_from_lab(self, lab_id: str, *, template_id: str | None = None, name: str | None = None) -> dict:
        if self.lab_store is None:
            raise HyperGeryError("create_lab_template_from_lab requires a lab store.")
        lab = self.lab_store.get_lab(lab_id)
        return self.create_lab_template(
            name or lab["name"],
            lab.get("description", ""),
            lab.get("network_mode", "nat"),
            [],
            lab.get("notes", ""),
            template_id=template_id,
        )

    def get_lab_template(self, template_id: str) -> dict:
        path = self.lab_path(template_id)
        if not path.exists():
            raise HyperGeryError(f"Lab template does not exist: {template_id}")
        return validate_lab_template(self.read_json(path))

    def delete_lab_template(self, template_id: str) -> None:
        path = self.lab_path(template_id)
        if not path.exists():
            raise HyperGeryError(f"Lab template does not exist: {template_id}")
        path.unlink()

    def export_vm_template(self, template_id: str, output_path: str | Path) -> Path:
        template = self.get_vm_template(template_id)
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.write_json(output, template)
        return output

    def import_vm_template(self, input_path: str | Path) -> dict:
        path = Path(input_path).expanduser()
        template = validate_vm_template(self.read_json(path))
        destination = self.vm_path(template["template_id"])
        if destination.exists():
            raise HyperGeryError(f"VM template already exists: {template['template_id']}")
        self.write_json(destination, template)
        return template

    def export_lab_template(self, template_id: str, output_path: str | Path) -> Path:
        template = self.get_lab_template(template_id)
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.write_json(output, template)
        return output

    def import_lab_template(self, input_path: str | Path) -> dict:
        path = Path(input_path).expanduser()
        template = validate_lab_template(self.read_json(path))
        destination = self.lab_path(template["template_id"])
        if destination.exists():
            raise HyperGeryError(f"Lab template already exists: {template['template_id']}")
        self.write_json(destination, template)
        return template
