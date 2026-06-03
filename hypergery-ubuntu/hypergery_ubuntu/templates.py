from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .backend import HyperGeryError, validate_vm_name, xdg_data_home


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
    names_seen: set[str] = set()
    for vm in template["vms"]:
        for key in ("name", "ram_mib", "vcpus", "disk_gb", "os_type", "display"):
            if key not in vm:
                raise HyperGeryError(f"Invalid lab template VM: missing {key}.")
        vm_name = str(vm["name"]).strip()
        if not vm_name:
            raise HyperGeryError("Lab template VM name cannot be empty.")
        try:
            validate_vm_name(vm_name)
        except HyperGeryError as exc:
            raise HyperGeryError(f"Lab template VM name invalid: {exc}") from exc
        if vm_name in names_seen:
            raise HyperGeryError(f"Lab template has duplicate VM name: {vm_name}")
        names_seen.add(vm_name)
        vm["name"] = vm_name
        if "template_id" in vm and vm["template_id"]:
            vm["template_id"] = validate_template_id(str(vm["template_id"]))
        else:
            vm.setdefault("template_id", "")
        if vm["os_type"] not in {"linux", "windows", "other"}:
            raise HyperGeryError("Lab template VM os_type must be linux, windows, or other.")
        if vm["display"] not in {"spice", "vnc"}:
            raise HyperGeryError("Lab template VM display must be spice or vnc.")
        for key in ("ram_mib", "vcpus", "disk_gb"):
            vm[key] = int(vm[key])
            if vm[key] < 1:
                raise HyperGeryError(f"Lab template VM {key} must be positive.")
        vm["iso_required"] = bool(vm.get("iso_required", True))
        vm.setdefault("role", "")
        vm.setdefault("notes", "")
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

    def update_vm_template(self, template_id: str, **kwargs) -> dict:
        template = self.get_vm_template(template_id)
        kwargs.pop("schema_version", None)
        template.update(kwargs)
        template["template_id"] = template_id
        template = validate_vm_template(template)
        self.write_json(self.vm_path(template_id), template)
        return template

    def update_lab_template(self, template_id: str, **kwargs) -> dict:
        template = self.get_lab_template(template_id)
        kwargs.pop("schema_version", None)
        template.update(kwargs)
        template["template_id"] = template_id
        template = validate_lab_template(template)
        self.write_json(self.lab_path(template_id), template)
        return template

    def _resolve_planned_vm(self, planned_vm: dict) -> dict:
        resolved: dict = {
            "os_type": "linux",
            "ram_mib": 4096,
            "vcpus": 2,
            "disk_gb": 40,
            "network_mode": "nat",
            "display": "spice",
        }
        if planned_vm.get("template_id"):
            try:
                vm_tmpl = self.get_vm_template(planned_vm["template_id"])
                for key in ("os_type", "ram_mib", "vcpus", "disk_gb", "network_mode", "display"):
                    if key in vm_tmpl:
                        resolved[key] = vm_tmpl[key]
            except HyperGeryError:
                pass
        for key in ("os_type", "ram_mib", "vcpus", "disk_gb", "display"):
            if key in planned_vm:
                resolved[key] = planned_vm[key]
        return resolved

    def instantiate_lab_template(
        self,
        template_id: str,
        new_lab_name: str,
        vm_iso_map: dict,
        *,
        dry_run: bool = False,
        new_lab_description: str = "",
        new_lab_id: str | None = None,
    ) -> dict:
        if self.backend is None or self.lab_store is None:
            raise HyperGeryError("instantiate_lab_template requires a backend and lab_store.")

        template = self.get_lab_template(template_id)
        planned_vms = template.get("vms", [])

        errors: list[str] = []
        warnings: list[str] = []
        vm_plans: list[dict] = []

        if not new_lab_name or not new_lab_name.strip():
            errors.append("Lab name is required.")

        for vm in planned_vms:
            vm_name = str(vm.get("name", "")).strip()
            resolved = self._resolve_planned_vm(vm)
            iso_required = vm.get("iso_required", True)
            iso_path = str(vm_iso_map.get(vm_name, "")).strip()

            if iso_required and not iso_path:
                errors.append(f"VM '{vm_name}' requires an ISO path.")
            elif iso_path:
                p = Path(iso_path).expanduser()
                if not p.exists():
                    errors.append(f"VM '{vm_name}': ISO not found: {iso_path}")
                elif not p.is_file():
                    errors.append(f"VM '{vm_name}': ISO is not a file: {iso_path}")

            if planned_vm_tmpl := vm.get("template_id"):
                try:
                    self.get_vm_template(planned_vm_tmpl)
                except HyperGeryError:
                    warnings.append(f"VM '{vm_name}': VM template '{planned_vm_tmpl}' not found; using planned VM values.")

            vm_plans.append({
                "name": vm_name,
                "resolved": resolved,
                "iso_path": iso_path,
                "iso_required": iso_required,
                "role": vm.get("role", ""),
                "template_id": vm.get("template_id", ""),
            })

        result: dict = {
            "template_id": template_id,
            "lab_name": new_lab_name,
            "vm_plans": vm_plans,
            "warnings": warnings,
            "errors": errors,
            "dry_run": dry_run,
            "lab": None,
            "vms_created": [],
        }

        if errors or dry_run:
            return result

        lab = self.lab_store.create_lab(
            new_lab_name,
            new_lab_description,
            template.get("network_mode", "nat"),
            lab_id=new_lab_id if new_lab_id else None,
        )
        result["lab"] = lab
        lab_id_created = lab["lab_id"]
        created_vms: list[str] = []

        try:
            for plan in vm_plans:
                resolved = plan["resolved"]
                self.backend.create_vm(
                    name=plan["name"],
                    iso_path=plan["iso_path"],
                    os_type=resolved["os_type"],
                    ram_mib=int(resolved["ram_mib"]),
                    vcpus=int(resolved["vcpus"]),
                    disk_gb=int(resolved["disk_gb"]),
                    disk_dir=None,
                    network_mode=resolved["network_mode"],
                    display_mode=resolved["display"],
                    lab_id=lab_id_created,
                )
                created_vms.append(plan["name"])
                result["vms_created"].append(plan["name"])
        except HyperGeryError as exc:
            result["errors"].append(f"VM creation failed: {exc}")
            rollback_errors: list[str] = []
            for vm_name in created_vms:
                try:
                    self.backend.delete_vm(validate_vm_name(vm_name), delete_disks=True)
                except Exception as rb_exc:
                    rollback_errors.append(f"Could not delete VM '{vm_name}': {rb_exc}")
            try:
                lab_dir = self.lab_store.lab_path(lab_id_created).parent
                shutil.rmtree(lab_dir)
            except Exception as rb_exc:
                rollback_errors.append(f"Could not delete lab '{lab_id_created}': {rb_exc}")
            if rollback_errors:
                result["warnings"].extend(rollback_errors)
                result["warnings"].append(
                    "Partial rollback failed. Check remaining VMs/labs and remove manually."
                )
            result["lab"] = None
            return result

        used = list(lab.get("templates_used", []))
        if template_id not in used:
            used.append(template_id)
        lab["templates_used"] = used
        lab.setdefault("vms", [])
        for vm_name in created_vms:
            if vm_name not in lab["vms"]:
                lab["vms"].append(vm_name)
        self.lab_store.write_lab(lab)
        result["lab"] = lab
        return result
