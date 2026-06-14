from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .backend import HyperGeryError, now_iso, validate_vm_name, xdg_data_home


LAB_SCHEMA_VERSION = 2
RESERVED_LAB_IDS = {"default", "root", "system", "libvirt", "qemu", "admin"}

# Optional per-VM roles inside a lab (v0.8 Labs workspace). Purely
# descriptive metadata; "" means no role assigned.
LAB_VM_ROLES = ("router", "firewall", "dns", "ad", "server", "db", "web", "client")

# v0.9 lab subjects (course/topic the lab belongs to).
LAB_SUBJECTS = ("ASR", "PAR", "ISO", "SAD", "DB", "WEB", "CUSTOM")

# Tercer octeto de 192.168.X.0/24 reservados que nunca se asignan a un lab:
#   122 -> red por defecto de libvirt (192.168.122.0/24)
# El rango de candidatos cubre 0-255 (256 subredes posibles) menos estos.
RESERVED_LAB_SUBNET_OCTETS = frozenset({122})
LAB_SUBNET_OCTET_RANGE = range(0, 256)


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
    # Octetos candidatos: todo el rango válido 0-255 menos los reservados
    # (p. ej. 122, la red por defecto de libvirt). Recorremos el rango completo
    # para no quedarnos sin direcciones cuando hay muchos labs.
    candidates = [octet for octet in LAB_SUBNET_OCTET_RANGE if octet not in RESERVED_LAB_SUBNET_OCTETS]
    span = len(candidates)
    # Punto de inicio determinista por lab_id para repartir las subredes y
    # mantener estable la asignación de un lab concreto entre ejecuciones.
    seed = int(hashlib.sha256(validate_lab_id(lab_id).encode("utf-8")).hexdigest()[:4], 16)
    for offset in range(span):
        octet = candidates[(seed + offset) % span]
        subnet = f"192.168.{octet}.0/24"
        if subnet not in existing:
            return subnet
    raise HyperGeryError(
        "No quedan subredes 192.168.X.0/24 libres para asignar al laboratorio; "
        "libera o elimina algún laboratorio existente antes de crear uno nuevo."
    )


def check_lab_budget(manifest: dict, vms: list) -> list[str]:
    """v1.3: violaciones del presupuesto del lab para una lista de VMs
    (objetos con ram_mib/vcpus, p. ej. VmSummary). Lista vacía = todo OK."""
    budget = manifest.get("budget") or {}
    if not budget:
        return []
    lab_vms = [vm for vm in vms if getattr(vm, "lab_id", "") == manifest.get("lab_id")]
    violations: list[str] = []
    max_vms = int(budget.get("max_vms") or 0)
    if max_vms and len(lab_vms) > max_vms:
        violations.append(f"VMs: {len(lab_vms)} > max_vms={max_vms}")
    max_ram = int(budget.get("max_ram_mib") or 0)
    total_ram = sum(int(getattr(vm, "ram_mib", 0) or 0) for vm in lab_vms)
    if max_ram and total_ram > max_ram:
        violations.append(f"RAM: {total_ram} MiB > max_ram_mib={max_ram}")
    max_vcpus = int(budget.get("max_vcpus") or 0)
    total_vcpus = sum(int(getattr(vm, "vcpus", 0) or 0) for vm in lab_vms)
    if max_vcpus and total_vcpus > max_vcpus:
        violations.append(f"vCPUs: {total_vcpus} > max_vcpus={max_vcpus}")
    return violations


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
            "vm_roles": {},
            "templates_used": [],
            "notes": "",
            "disks": [],
            "iso_references": [],
            # v0.9 workspace metadata. Old manifests without these fields
            # keep working; migrate_manifest fills safe defaults.
            "subject": "CUSTOM",
            "owner": "",
            "tags": [],
            "favorite": False,
            "archived": False,
            "last_started_at": "",
            # v1.3: etiquetas por VM y presupuesto de recursos del lab.
            "vm_tags": {},
            "budget": {},
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
        roles = migrated.get("vm_roles")
        migrated["vm_roles"] = {
            str(vm_name): str(role)
            for vm_name, role in (roles.items() if isinstance(roles, dict) else ())
            if str(role) in LAB_VM_ROLES
        }
        subject = str(migrated.get("subject") or "CUSTOM").upper()
        migrated["subject"] = subject if subject in LAB_SUBJECTS else "CUSTOM"
        migrated["owner"] = str(migrated.get("owner") or "")
        migrated["tags"] = sorted({str(tag) for tag in migrated.get("tags", []) if str(tag).strip()})
        migrated["favorite"] = bool(migrated.get("favorite"))
        migrated["archived"] = bool(migrated.get("archived"))
        migrated["last_started_at"] = str(migrated.get("last_started_at") or "")
        raw_vm_tags = migrated.get("vm_tags")
        migrated["vm_tags"] = {
            str(vm_name): sorted({str(tag).strip() for tag in tags if str(tag).strip()})
            for vm_name, tags in (raw_vm_tags.items() if isinstance(raw_vm_tags, dict) else ())
            if isinstance(tags, (list, tuple, set)) and tags
        }
        raw_budget = migrated.get("budget")
        migrated["budget"] = {
            key: int(raw_budget[key])
            for key in ("max_ram_mib", "max_vcpus", "max_vms")
            if isinstance(raw_budget, dict) and str(raw_budget.get(key, "")).strip().isdigit() and int(raw_budget[key]) > 0
        }
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

    def set_vm_role(self, lab_id: str, vm_name: str, role: str) -> dict:
        """Assign (or clear with role='') a descriptive role to one lab VM."""
        clean_role = str(role or "").strip()
        if clean_role and clean_role not in LAB_VM_ROLES:
            allowed = ", ".join(LAB_VM_ROLES)
            raise HyperGeryError(f"Unsupported VM role: {clean_role}. Allowed: {allowed}.")
        manifest = self.get_lab(lab_id)
        clean_name = validate_vm_name(vm_name)
        roles = dict(manifest.get("vm_roles") or {})
        if clean_role:
            roles[clean_name] = clean_role
        else:
            roles.pop(clean_name, None)
        manifest["vm_roles"] = roles
        manifest["updated_at"] = now_iso()
        self.write_lab(manifest)
        return self.get_lab(lab_id)

    def set_vm_tags(self, lab_id: str, vm_name: str, tags: list[str]) -> dict:
        """v1.3: etiquetas libres por VM (p. ej. "produccion", "victima")."""
        manifest = self.get_lab(lab_id)
        clean_name = validate_vm_name(vm_name)
        clean_tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        vm_tags = dict(manifest.get("vm_tags") or {})
        if clean_tags:
            vm_tags[clean_name] = clean_tags
        else:
            vm_tags.pop(clean_name, None)
        manifest["vm_tags"] = vm_tags
        manifest["updated_at"] = now_iso()
        self.write_lab(manifest)
        return self.get_lab(lab_id)

    def set_budget(self, lab_id: str, *, max_ram_mib: int = 0, max_vcpus: int = 0, max_vms: int = 0) -> dict:
        """v1.3: presupuesto de recursos del lab (0 = sin límite)."""
        manifest = self.get_lab(lab_id)
        budget = {}
        for key, value in (("max_ram_mib", max_ram_mib), ("max_vcpus", max_vcpus), ("max_vms", max_vms)):
            value = int(value)
            if value < 0:
                raise HyperGeryError(f"Budget {key} cannot be negative.")
            if value:
                budget[key] = value
        manifest["budget"] = budget
        manifest["updated_at"] = now_iso()
        self.write_lab(manifest)
        return self.get_lab(lab_id)

    WORKSPACE_FIELDS = {"subject", "owner", "tags", "favorite", "archived", "description", "notes"}

    def update_workspace_fields(self, lab_id: str, **fields) -> dict:
        """Update v0.9 workspace metadata (subject, owner, tags, favorite,
        archived, description, notes). Values are sanitized by migration."""
        unknown = set(fields) - self.WORKSPACE_FIELDS
        if unknown:
            raise HyperGeryError(f"Unknown lab workspace fields: {', '.join(sorted(unknown))}")
        if "subject" in fields:
            subject = str(fields["subject"] or "").upper()
            if subject not in LAB_SUBJECTS:
                raise HyperGeryError(f"Unknown lab subject: {fields['subject']}. Allowed: {', '.join(LAB_SUBJECTS)}")
            fields["subject"] = subject
        manifest = self.get_lab(lab_id)
        manifest.update(fields)
        manifest["updated_at"] = now_iso()
        self.write_lab(manifest)
        return self.get_lab(lab_id)

    def touch_started(self, lab_id: str) -> dict:
        """Record that the lab was just started (Labs workspace actions)."""
        manifest = self.get_lab(lab_id)
        manifest["last_started_at"] = now_iso()
        manifest["updated_at"] = manifest["last_started_at"]
        self.write_lab(manifest)
        return self.get_lab(lab_id)

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
