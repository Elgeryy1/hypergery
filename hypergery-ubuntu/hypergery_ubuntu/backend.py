from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    import grp
except ImportError:  # pragma: no cover - Windows editing environment only.
    grp = None  # type: ignore[assignment]

try:
    import pwd
except ImportError:  # pragma: no cover - Windows editing environment only.
    pwd = None  # type: ignore[assignment]


APP_NAME = "HyperGery"
LIBVIRT_URI = os.environ.get("HYPERGERY_LIBVIRT_URI", "qemu:///system")
HG_NS = "https://hypergery.local/schema/0.1"
ET.register_namespace("hg", HG_NS)


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back on default."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Timeout por defecto para órdenes virsh/qemu-img cortas (consultas, listados,
# definiciones). Se mantiene en 120s por compatibilidad con las llamadas
# existentes que no especifican timeout.
DEFAULT_COMMAND_TIMEOUT = 120

# Timeout para operaciones largas que copian/convierten discos completos
# (clonado con `qemu-img convert`, exportación/importación/migración). Por
# defecto 1800s (30 min) y configurable con HYPERGERY_LONG_OP_TIMEOUT para
# discos muy grandes o NAS lentos.
LONG_OPERATION_TIMEOUT = _env_int("HYPERGERY_LONG_OP_TIMEOUT", 1800)


class HyperGeryError(RuntimeError):
    pass


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class PreflightItem:
    name: str
    status: str
    detail: str
    fix: str = ""


@dataclass
class VmSummary:
    name: str
    state: str
    lab_id: str
    ram_mib: int | None = None
    vcpus: int | None = None
    disk_path: str = ""
    disk_virtual: str = ""
    disk_actual: str = ""
    iso_path: str = ""
    network: str = ""
    graphics: str = ""
    xml: str = ""


@dataclass
class ConsoleDisplay:
    type: str
    host: str
    port: int
    display: str
    uri: str


def is_snap_private_xdg_path(path: Path) -> bool:
    try:
        return bool(os.environ.get("SNAP")) and (Path.home() / "snap") in path.parents
    except RuntimeError:
        return False


def _console_port(display_type: str, value: str) -> tuple[int, str]:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raise HyperGeryError("Console display does not expose a usable TCP port.")
    if display_type == "vnc" and 0 <= raw < 100:
        return 5900 + raw, f":{raw}"
    if raw <= 0:
        raise HyperGeryError("Console display does not expose a usable TCP port.")
    if display_type == "vnc" and raw >= 5900:
        return raw, f":{raw - 5900}"
    return raw, f":{raw}"


def parse_console_display(uri: str = "", xml: str = "") -> ConsoleDisplay:
    display_type = ""
    host = "127.0.0.1"
    port = 0
    display = ""
    uri = (uri or "").strip()
    if uri:
        parsed = urlparse(uri)
        display_type = parsed.scheme.lower()
        if display_type not in {"vnc", "spice"}:
            raise HyperGeryError(f"Unsupported console display type: {display_type or uri}")
        if parsed.hostname and parsed.hostname not in {"0.0.0.0", "::", "[::]"}:
            host = parsed.hostname
        if parsed.port is not None:
            port, display = _console_port(display_type, str(parsed.port))
    if xml and (not display_type or not port):
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise HyperGeryError(f"Cannot parse libvirt domain XML for console display: {exc}") from exc
        graphics = root.find("./devices/graphics")
        if graphics is not None:
            display_type = display_type or graphics.attrib.get("type", "").lower()
            listen = graphics.attrib.get("listen", "")
            if listen and listen not in {"0.0.0.0", "::"}:
                host = listen
            if not port:
                port_attr = graphics.attrib.get("port") or graphics.attrib.get("tlsPort") or ""
                port, display = _console_port(display_type, port_attr)
    if display_type not in {"vnc", "spice"}:
        raise HyperGeryError("VM has no supported graphical console display.")
    if not port:
        raise HyperGeryError("VM console display is not ready yet. Start the VM and retry.")
    normalized_uri = f"{display_type}://{host}:{port}"
    if not display:
        display = f":{port - 5900}" if display_type == "vnc" and port >= 5900 else f":{port}"
    return ConsoleDisplay(display_type, host, port, display, normalized_uri)


def pick_render_node(
    by_path_dir: str | Path = "/dev/dri/by-path",
    sysfs_devices: str | Path = "/sys/bus/pci/devices",
) -> str:
    """Nodo DRM de render para VirGL (ruta by-path, estable entre reinicios).

    Prefiere una GPU con driver Mesa (amdgpu/i915/…): el EGL headless del
    driver propietario NVIDIA no se inicializa para el usuario libvirt-qemu
    (necesita /dev/nvidia*, que libvirt no concede). Además, sin rendernode
    explícito libvirt no añade NINGÚN nodo al cgroup de qemu → EGL_NOT_INITIALIZED.
    """
    mesa_drivers = {"amdgpu", "i915", "radeon", "nouveau", "xe"}
    candidates: list[tuple[str, str]] = []
    base = Path(by_path_dir)
    if base.is_dir():
        for link in sorted(base.glob("pci-*-render")):
            address = link.name[len("pci-"):-len("-render")]
            driver_link = Path(sysfs_devices) / address / "driver"
            driver = driver_link.resolve().name if driver_link.is_symlink() else ""
            candidates.append((driver, str(link)))
    for driver, node in candidates:
        if driver in mesa_drivers:
            return node
    return candidates[0][1] if candidates else ""


def normalize_render_node_for_host(root: ET.Element, render_node: str | None = None) -> bool:
    """Adapta el rendernode de VirGL al equipo LOCAL. Devuelve True si cambió algo.

    El XML de una VM con aceleración 3D lleva grabada la ruta del nodo de
    render del equipo donde se creó (p. ej. pci-0000:11:00.0-render); al
    importarla en otro equipo esa ruta no existe y qemu no arranca. Aquí se
    reescribe al mejor nodo local; si el equipo no tiene ninguno utilizable,
    se degrada con elegancia: virtio sin GL (la VM arranca, sin 3D).
    """
    devices = root.find("./devices")
    if devices is None:
        return False
    egl_elements = [g for g in devices.findall("graphics") if g.attrib.get("type") == "egl-headless"]
    if not egl_elements:
        return False
    local = pick_render_node() if render_node is None else render_node
    changed = False
    for egl in egl_elements:
        if not local:
            devices.remove(egl)
            changed = True
            continue
        gl = egl.find("gl")
        if gl is None:
            gl = ET.SubElement(egl, "gl")
            changed = True
        if gl.attrib.get("rendernode") != local:
            gl.set("rendernode", local)
            changed = True
    if not local:
        for accel in devices.findall("./video/model/acceleration"):
            if accel.attrib.get("accel3d") == "yes":
                accel.set("accel3d", "no")
                changed = True
    return changed


def normalize_graphics_audio_for_display(root: ET.Element, display_mode: str) -> None:
    if display_mode not in {"spice", "vnc"}:
        raise HyperGeryError("Display mode must be spice or vnc.")
    devices = root.find("./devices")
    if devices is None:
        devices = ET.SubElement(root, "devices")

    graphics = devices.find("graphics")
    if graphics is None:
        graphics = ET.SubElement(devices, "graphics")
    graphics.attrib.clear()
    graphics.attrib.update({"type": display_mode, "autoport": "yes", "listen": "127.0.0.1"})

    spice_channels = [channel for channel in devices.findall("channel") if channel.attrib.get("type") == "spicevmc"]
    if display_mode == "spice":
        if not spice_channels:
            channel = ET.SubElement(devices, "channel", {"type": "spicevmc"})
            ET.SubElement(channel, "target", {"type": "virtio", "name": "com.redhat.spice.0"})
        return

    for channel in spice_channels:
        devices.remove(channel)
    for audio in list(devices.findall("audio")):
        if audio.attrib.get("type") == "spice":
            devices.remove(audio)


def xdg_data_home() -> Path:
    override = os.environ.get("HYPERGERY_DATA_HOME")
    if override:
        return Path(override).expanduser() / "hypergery"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        candidate = Path(xdg).expanduser()
        if not is_snap_private_xdg_path(candidate):
            return candidate / "hypergery"
    return Path.home() / ".local" / "share" / "hypergery"


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "hypergery"


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def validate_vm_name(name: str) -> str:
    clean = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", clean):
        raise HyperGeryError(
            "VM names must start with a letter or number and contain only letters, numbers, dot, dash, or underscore."
        )
    if ".." in clean or "/" in clean or "\\" in clean:
        raise HyperGeryError("VM name cannot contain path traversal characters.")
    return clean


# Espacio de octetos de las redes HyperGery (192.168.X.0/24): 20-199 sin el
# 122 (libvirt default) más 200-239. HG-BUG-0012: con hash directo dos labs
# podían colisionar en el mismo octeto; allocate_network_octet sondea el
# espacio hasta encontrar uno libre.
HG_NETWORK_OCTETS: tuple[int, ...] = tuple(o for o in range(20, 200) if o != 122) + tuple(range(200, 240))


def derive_network_octet(lab_id: str, network_mode: str) -> int:
    """Octeto base (determinista por hash) de la red de un lab."""
    digest = hashlib.sha256(f"{validate_lab_id(lab_id)}:{network_mode}".encode()).hexdigest()
    octet = 20 + (int(digest[:2], 16) % 180)
    if octet == 122:
        octet = 200 + (int(digest[2:4], 16) % 40)
    return octet


def allocate_network_octet(lab_id: str, network_mode: str, used_octets: set[int] | frozenset[int]) -> int:
    """Primer octeto libre empezando por el derivado del hash (HG-BUG-0012)."""
    base = derive_network_octet(lab_id, network_mode)
    if base not in used_octets:
        return base
    order = HG_NETWORK_OCTETS
    start = order.index(base)
    for step in range(1, len(order)):
        candidate = order[(start + step) % len(order)]
        if candidate not in used_octets:
            return candidate
    raise HyperGeryError(f"No free HyperGery network octet left (all {len(order)} in use).")


def validate_lab_id(lab_id: str) -> str:
    clean = lab_id.strip() or "default-lab"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,48}", clean):
        raise HyperGeryError("Lab id must contain only letters, numbers, dot, dash, or underscore.")
    if ".." in clean or "/" in clean or "\\" in clean:
        raise HyperGeryError("Lab id cannot contain path traversal characters.")
    return clean


class HyperGeryBackend:
    def __init__(self) -> None:
        self.data_dir = xdg_data_home()
        self.state_dir = xdg_state_home()
        self.vms_dir = self.data_dir / "vms"
        self.labs_dir = self.data_dir / "labs"
        self.log_dir = self.state_dir / "logs"
        for directory in (self.vms_dir, self.labs_dir, self.log_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HyperGeryError(
                    f"Cannot create HyperGery directory {directory}. Check XDG_DATA_HOME/XDG_STATE_HOME or home directory permissions."
                ) from exc
        self.log_file = self.log_dir / "hypergery.log"
        logging.basicConfig(
            filename=self.log_file,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            force=True,
        )
        self.ensure_default_lab()

    def run(self, args: list[str], *, timeout: int = DEFAULT_COMMAND_TIMEOUT, check: bool = True) -> CommandResult:
        logging.info("run: %s", " ".join(args))
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        try:
            proc = subprocess.run(
                args,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            logging.error("missing executable: %s", args[0])
            raise HyperGeryError(f"Required executable not found: {args[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            logging.error("command timed out: %s", " ".join(args))
            raise HyperGeryError(f"Command timed out: {' '.join(args)}") from exc
        result = CommandResult(args, proc.returncode, proc.stdout, proc.stderr)
        if proc.stdout.strip():
            logging.info("stdout: %s", proc.stdout.strip())
        if proc.stderr.strip():
            logging.info("stderr: %s", proc.stderr.strip())
        if check and proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
            logging.error("command failed: %s: %s", " ".join(args), msg)
            raise HyperGeryError(f"{' '.join(args)} failed: {msg}")
        return result

    def virsh(self, args: list[str], *, timeout: int = DEFAULT_COMMAND_TIMEOUT, check: bool = True) -> CommandResult:
        return self.run(["virsh", "--connect", LIBVIRT_URI, *args], timeout=timeout, check=check)

    def qemu_img(self, args: list[str], *, timeout: int = DEFAULT_COMMAND_TIMEOUT, check: bool = True) -> CommandResult:
        return self.run(["qemu-img", *args], timeout=timeout, check=check)

    def preflight(self) -> list[PreflightItem]:
        items: list[PreflightItem] = []
        kvm = Path("/dev/kvm")
        if kvm.exists():
            if os.access(kvm, os.R_OK | os.W_OK):
                items.append(PreflightItem("/dev/kvm", "OK", "KVM device exists and is accessible."))
            else:
                items.append(
                    PreflightItem(
                        "/dev/kvm",
                        "Warning",
                        "KVM device exists but this user cannot access it.",
                        "sudo usermod -aG kvm,libvirt $USER && newgrp libvirt",
                    )
                )
        else:
            items.append(
                PreflightItem(
                    "/dev/kvm",
                    "Error",
                    "KVM device is missing. Hardware virtualization may be disabled or KVM is not loaded.",
                    "Enable virtualization in BIOS/UEFI and install qemu-kvm.",
                )
            )

        group_names = self.current_group_names()
        missing_groups = [group for group in ("kvm", "libvirt") if group not in group_names]
        if not missing_groups:
            items.append(PreflightItem("user groups", "OK", "Current user is in kvm and libvirt groups."))
        else:
            items.append(
                PreflightItem(
                    "user groups",
                    "Warning",
                    f"Current user is missing group(s): {', '.join(missing_groups)}.",
                    "sudo usermod -aG kvm,libvirt $USER  # then log out and back in",
                )
            )

        for exe in ("qemu-system-x86_64", "qemu-img", "virsh"):
            found = shutil.which(exe)
            items.append(
                PreflightItem(
                    exe,
                    "OK" if found else "Error",
                    found or f"{exe} is not installed.",
                    "" if found else "sudo apt install qemu-kvm qemu-system-x86 qemu-utils libvirt-clients libvirt-daemon-system",
                )
            )

        viewer = next((tool for tool in ("virt-viewer", "remote-viewer") if shutil.which(tool)), None)
        items.append(
            PreflightItem(
                "console viewer",
                "OK" if viewer else "Error",
                viewer or "No graphical VM console viewer found.",
                "" if viewer else "sudo apt install virt-viewer",
            )
        )

        systemctl = shutil.which("systemctl")
        if systemctl:
            active_services = []
            for service in ("libvirtd", "virtqemud"):
                result = self.run([systemctl, "is-active", service], check=False, timeout=10)
                if result.returncode == 0 and result.stdout.strip() == "active":
                    active_services.append(service)
            items.append(
                PreflightItem(
                    "libvirt daemon",
                    "OK" if active_services else "Error",
                    ", ".join(active_services) + " active" if active_services else "libvirtd/virtqemud is not active.",
                    "" if active_services else "sudo systemctl enable --now libvirtd  # or: sudo systemctl enable --now virtqemud",
                )
            )
        else:
            items.append(PreflightItem("libvirt daemon", "Warning", "systemctl is unavailable; daemon status not checked."))

        if shutil.which("virsh"):
            result = self.virsh(["list", "--all"], check=False, timeout=20)
            items.append(
                PreflightItem(
                    "libvirt connection",
                    "OK" if result.returncode == 0 else "Error",
                    "Connected to qemu:///system." if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip()),
                    "" if result.returncode == 0 else "Add your user to libvirt/kvm groups, log out/in, and confirm libvirt is running.",
                )
            )
        return items

    @staticmethod
    def current_group_names() -> set[str]:
        names: set[str] = set()
        if grp is None:
            return names
        for gid in os.getgroups():
            try:
                names.add(grp.getgrgid(gid).gr_name)
            except KeyError:
                continue
        try:
            names.add(grp.getgrgid(os.getgid()).gr_name)
        except KeyError:
            pass
        return names

    def ensure_default_lab(self) -> dict:
        return self.ensure_lab("default-lab", "Default Lab", notes="Default HyperGery lab.")

    def lab_store(self):
        from .labs import LabStore

        return LabStore(self.data_dir)

    def ensure_lab(self, lab_id: str, name: str, notes: str = "") -> dict:
        store = self.lab_store()
        try:
            return store.get_lab(lab_id)
        except HyperGeryError:
            return store.create_lab(name, lab_id=lab_id, notes=notes)

    def write_lab(self, manifest: dict) -> None:
        self.lab_store().write_lab(manifest)

    def load_labs(self) -> list[dict]:
        return self.lab_store().list_labs()

    def update_lab_for_vm(self, lab_id: str, vm_name: str, disk_path: str, iso_path: str, network_id: str) -> None:
        manifest = self.ensure_lab(lab_id, "Default Lab" if lab_id == "default-lab" else lab_id)
        if vm_name not in manifest["vms"]:
            manifest["vms"].append(vm_name)
        for key, value in (("disks", disk_path), ("iso_references", iso_path)):
            if value and value not in manifest[key]:
                manifest[key].append(value)
        manifest["network_id"] = network_id
        self.write_lab(manifest)

    def move_vm_to_lab(self, old_lab_id: str, new_lab_id: str, vm_name: str, disk_path: str, iso_path: str, network_id: str) -> None:
        old_lab_id = validate_lab_id(old_lab_id) if old_lab_id else ""
        new_lab_id = validate_lab_id(new_lab_id)
        if old_lab_id and old_lab_id != new_lab_id:
            old_path = self.labs_dir / old_lab_id / "lab.json"
            if old_path.exists():
                try:
                    old_manifest = json.loads(old_path.read_text(encoding="utf-8"))
                    old_manifest["vms"] = [name for name in old_manifest.get("vms", []) if name != vm_name]
                    self.write_lab(old_manifest)
                except (OSError, json.JSONDecodeError) as exc:
                    logging.error("cannot update old lab manifest %s: %s", old_path, exc)
        self.update_lab_for_vm(new_lab_id, vm_name, disk_path, iso_path, network_id)

    def remove_vm_from_labs(self, vm_name: str) -> None:
        for manifest in self.load_labs():
            if vm_name in manifest.get("vms", []):
                manifest["vms"] = [name for name in manifest["vms"] if name != vm_name]
                self.write_lab(manifest)

    def manifest_vm_names(self) -> set[str]:
        names: set[str] = set()
        for manifest in self.load_labs():
            names.update(manifest.get("vms", []))
        return names

    def manifest_disk_paths(self) -> set[Path]:
        disks: set[Path] = set()
        for manifest in self.load_labs():
            for disk in manifest.get("disks", []):
                try:
                    disks.add(Path(disk).expanduser().resolve())
                except OSError:
                    logging.warning("ignoring invalid disk path in manifest: %s", disk)
        return disks

    def network_name(self, lab_id: str, network_mode: str) -> str:
        suffix = validate_lab_id(lab_id).lower().replace("_", "-")
        base = f"hg-net-{suffix}"
        return base if network_mode == "nat" else f"{base}-isolated"

    def bridge_name(self, lab_id: str, network_mode: str) -> str:
        digest = hashlib.sha256(f"{validate_lab_id(lab_id)}:{network_mode}".encode()).hexdigest()
        bridge = f"hgbr{digest[:7]}"
        if bridge == "virbr0" or len(bridge) > 15 or not re.fullmatch(r"[A-Za-z0-9_.-]+", bridge):
            raise HyperGeryError(f"Generated invalid HyperGery bridge name: {bridge}")
        return bridge

    def network_ip_address(self, lab_id: str, network_mode: str) -> str:
        return f"192.168.{derive_network_octet(lab_id, network_mode)}.1"

    def network_xml(self, lab_id: str, network_mode: str, ip_address: str | None = None) -> str:
        name = self.network_name(lab_id, network_mode)
        bridge = self.bridge_name(lab_id, network_mode)
        ip_address = ip_address or self.network_ip_address(lab_id, network_mode)
        octet = ip_address.split(".")[2]
        forward = "<forward mode='nat'/>" if network_mode == "nat" else ""
        return f"""<network>
  <name>{name}</name>
  {forward}
  <bridge name='{bridge}' stp='on' delay='0'/>
  <ip address='{ip_address}' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.{octet}.100' end='192.168.{octet}.254'/>
    </dhcp>
  </ip>
</network>
"""

    @staticmethod
    def is_hypergery_network_name(name: str) -> bool:
        return name.startswith("hg-net-")

    @staticmethod
    def network_bridge_from_xml(xml: str) -> str:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise HyperGeryError(f"Cannot parse libvirt network XML: {exc}") from exc
        bridge = root.find("bridge")
        return bridge.attrib.get("name", "") if bridge is not None else ""

    @staticmethod
    def network_ip_from_xml(xml: str) -> str:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise HyperGeryError(f"Cannot parse libvirt network XML: {exc}") from exc
        ip = root.find("ip")
        return ip.attrib.get("address", "") if ip is not None else ""

    def recycle_hypergery_network(self, name: str, reason: str) -> None:
        if not self.is_hypergery_network_name(name):
            raise HyperGeryError(f"Refusing to recycle non-HyperGery network: {name}")
        logging.warning("recycling HyperGery network %s: %s", name, reason)
        info = self.virsh(["net-info", name], check=False)
        if re.search(r"^Active:\s+yes$", info.stdout, re.MULTILINE):
            self.virsh(["net-destroy", name])
        self.virsh(["net-undefine", name])

    @staticmethod
    def _octet_from_ip(ip_address: str) -> int | None:
        match = re.fullmatch(r"192\.168\.(\d{1,3})\.1", ip_address or "")
        if not match:
            return None
        octet = int(match.group(1))
        return octet if octet in HG_NETWORK_OCTETS else None

    def list_hypergery_network_octets(self) -> dict[str, int]:
        """Octeto de cada red hg-net-* definida en libvirt (para HG-BUG-0012)."""
        listing = self.virsh(["net-list", "--all", "--name"], check=False)
        if listing.returncode != 0:
            return {}
        octets: dict[str, int] = {}
        for raw in listing.stdout.splitlines():
            name = raw.strip()
            if not self.is_hypergery_network_name(name):
                continue
            dump = self.virsh(["net-dumpxml", name], check=False)
            if dump.returncode != 0:
                continue
            try:
                octet = self._octet_from_ip(self.network_ip_from_xml(dump.stdout))
            except HyperGeryError:
                continue
            if octet is not None:
                octets[name] = octet
        return octets

    def reconcile_existing_network(
        self,
        name: str,
        expected_bridge: str,
        expected_ip: str,
        *,
        used_octets: set[int] | frozenset[int] = frozenset(),
    ) -> None:
        dump = self.virsh(["net-dumpxml", name], check=False)
        if dump.returncode != 0:
            return
        bridge = self.network_bridge_from_xml(dump.stdout)
        ip_address = self.network_ip_from_xml(dump.stdout)
        invalid_bridge = bridge == "virbr0" or len(bridge) > 15 or not bridge.startswith("hgbr")
        wrong_bridge = bridge and bridge != expected_bridge
        # HG-BUG-0012: una IP existente se conserva si está dentro del espacio
        # HyperGery y no choca con otra red del host (puede venir de una
        # reasignación anti-colisión); solo IPs inválidas o en conflicto
        # fuerzan el reciclado.
        octet = self._octet_from_ip(ip_address) if ip_address else None
        wrong_ip = bool(ip_address) and ip_address != expected_ip and (octet is None or octet in used_octets)
        if invalid_bridge or wrong_bridge or wrong_ip:
            reason = (
                f"bridge {bridge or '<missing>'} / ip {ip_address or '<missing>'} "
                f"does not match expected HyperGery bridge {expected_bridge} / ip {expected_ip}"
            )
            self.recycle_hypergery_network(name, reason)

    def ensure_network(self, lab_id: str, network_mode: str) -> str:
        if network_mode not in {"nat", "isolated"}:
            raise HyperGeryError("Network mode must be nat or isolated.")
        name = self.network_name(lab_id, network_mode)
        expected_bridge = self.bridge_name(lab_id, network_mode)
        # HG-BUG-0012: evitar colisión de octeto con las demás redes del host.
        used_octets = {octet for other, octet in self.list_hypergery_network_octets().items() if other != name}
        expected_ip = f"192.168.{allocate_network_octet(lab_id, network_mode, used_octets)}.1"
        info = self.virsh(["net-info", name], check=False)
        if info.returncode == 0:
            self.reconcile_existing_network(name, expected_bridge, expected_ip, used_octets=used_octets)
            info = self.virsh(["net-info", name], check=False)
        if info.returncode != 0:
            xml = self.network_xml(lab_id, network_mode, expected_ip)
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
                tmp.write(xml)
                xml_path = tmp.name
            try:
                # HG-BUG-0016 (TOCTOU): otro proceso pudo definir la red entre
                # el net-info y este net-define; el fallo es benigno si la red
                # ya existe.
                define = self.virsh(["net-define", xml_path], check=False)
                if define.returncode != 0 and self.virsh(["net-info", name], check=False).returncode != 0:
                    raise HyperGeryError(f"Cannot define network {name}: {define.stderr.strip() or define.stdout.strip()}")
            finally:
                Path(xml_path).unlink(missing_ok=True)
        active = self.virsh(["net-info", name], check=False)
        if not re.search(r"^Active:\s+yes$", active.stdout, re.MULTILINE):
            # HG-BUG-0016 (TOCTOU): "already active" por una carrera benigna
            # con otro proceso no es un error; cualquier otro fallo sí.
            start = self.virsh(["net-start", name], check=False)
            if start.returncode != 0:
                recheck = self.virsh(["net-info", name], check=False)
                if not re.search(r"^Active:\s+yes$", recheck.stdout, re.MULTILINE):
                    raise HyperGeryError(f"Cannot start network {name}: {start.stderr.strip() or start.stdout.strip()}")
        self.virsh(["net-autostart", name], check=False)
        logging.info("network ready: %s", name)
        return name

    def create_vm(
        self,
        *,
        name: str,
        iso_path: str,
        os_type: str,
        ram_mib: int,
        vcpus: int,
        disk_gb: int,
        disk_dir: str | None,
        network_mode: str,
        display_mode: str = "spice",
        lab_id: str = "default-lab",
        profile: str = "",
        migratable_cpu: bool = False,
        accel_3d: bool = False,
    ) -> VmSummary:
        from .vm_profiles import preflight_profile, profile_for, validate_iso

        name = validate_vm_name(name)
        lab_id = validate_lab_id(lab_id)
        # B1/B2: perfil explícito (windows11, linux…) o derivado de os_type.
        vm_profile = profile_for(profile or os_type)
        iso = Path(iso_path).expanduser().resolve()
        if not iso.is_file():
            raise HyperGeryError(f"ISO does not exist: {iso}")
        iso_check = validate_iso(str(iso))
        if not iso_check["ok"]:
            raise HyperGeryError("ISO inválida: " + "; ".join(iso_check["errors"]))
        # B1: dependencias de firmware/TPM ANTES de crear nada (no bypass).
        pf = preflight_profile(vm_profile)
        if not pf.ok:
            hint = (" Ejecuta: " + " && ".join(pf.suggested_commands)) if pf.suggested_commands else ""
            raise HyperGeryError("; ".join(pf.errors) + hint)
        if ram_mib < 256 or vcpus < 1 or disk_gb < 1:
            raise HyperGeryError("RAM, vCPU, and disk size must be positive values.")
        base_dir = Path(disk_dir).expanduser().resolve() if disk_dir else self.vms_dir / name
        if ".." in base_dir.parts:
            raise HyperGeryError("Disk directory is not valid.")
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HyperGeryError(f"Cannot create disk directory {base_dir}: {exc}") from exc
        disk_path = base_dir / f"{name}.qcow2"
        if disk_path.exists():
            raise HyperGeryError(f"Disk already exists: {disk_path}")
        existing = self.virsh(["dominfo", name], check=False)
        if existing.returncode == 0:
            raise HyperGeryError(f"A libvirt domain named {name} already exists.")

        network_id = self.ensure_network(lab_id, network_mode)
        self.qemu_img(["create", "-f", "qcow2", str(disk_path), f"{disk_gb}G"], timeout=600)
        self.grant_libvirt_qemu_access(disk_path, iso)
        logging.info("created qcow2 disk path=%s size_gb=%s", disk_path, disk_gb)
        xml = self.domain_xml(
            name=name,
            iso_path=str(iso),
            os_type=vm_profile.os_type,
            ram_mib=ram_mib,
            vcpus=vcpus,
            disk_path=str(disk_path),
            network_id=network_id,
            lab_id=lab_id,
            display_mode=display_mode,
            profile_key=vm_profile.key,
            migratable_cpu=migratable_cpu,
            accel_3d=accel_3d,
        )
        self.define_domain_xml(xml)
        self.update_lab_for_vm(lab_id, name, str(disk_path), str(iso), network_id)
        logging.info("created vm name=%s disk=%s iso=%s network=%s", name, disk_path, iso, network_id)
        return self.get_vm(name)

    def grant_libvirt_qemu_access(self, *paths: Path) -> None:
        if not shutil.which("setfacl"):
            logging.warning("setfacl is unavailable; cannot grant libvirt-qemu ACLs for VM media")
            return
        if pwd is None:
            logging.info("pwd module is unavailable; skipping libvirt-qemu ACL grant")
            return
        try:
            pwd.getpwnam("libvirt-qemu")
        except KeyError:
            logging.info("libvirt-qemu user does not exist; skipping ACL grant")
            return
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved.exists() and resolved.is_file():
                self.run(["setfacl", "-m", "u:libvirt-qemu:rw-", str(resolved)], check=False)
                parent = resolved.parent
            else:
                parent = resolved if resolved.is_dir() else resolved.parent
            for directory in self.accessible_parent_dirs(parent):
                self.run(["setfacl", "-m", "u:libvirt-qemu:--x", str(directory)], check=False)
            if parent.exists():
                self.run(["setfacl", "-m", "u:libvirt-qemu:rwx", str(parent)], check=False)

    @staticmethod
    def accessible_parent_dirs(path: Path) -> list[Path]:
        path = path.resolve()
        home = Path.home().resolve()
        if path == home or home in path.parents:
            dirs = [home]
            relative = path.relative_to(home)
            current = home
            for part in relative.parts:
                current = current / part
                dirs.append(current)
            return dirs
        return [parent for parent in reversed(path.parents) if parent != Path("/")] + [path]

    def domain_xml(
        self,
        *,
        name: str,
        iso_path: str,
        os_type: str,
        ram_mib: int,
        vcpus: int,
        disk_path: str,
        network_id: str,
        lab_id: str,
        display_mode: str = "spice",
        profile_key: str = "",
        migratable_cpu: bool = False,
        accel_3d: bool = False,
    ) -> str:
        from .vm_profiles import profile_for, resolve_ovmf

        if display_mode not in {"spice", "vnc"}:
            raise HyperGeryError("Display mode must be spice or vnc.")
        vm_profile = profile_for(profile_key or os_type)
        emulator = shutil.which("qemu-system-x86_64") or "/usr/bin/qemu-system-x86_64"
        domain = ET.Element("domain", {"type": "kvm"})
        ET.SubElement(domain, "name").text = name
        ET.SubElement(domain, "uuid").text = str(uuid.uuid4())
        metadata = ET.SubElement(domain, "metadata")
        hg = ET.SubElement(metadata, f"{{{HG_NS}}}hypergery")
        ET.SubElement(hg, f"{{{HG_NS}}}managed").text = "true"
        ET.SubElement(hg, f"{{{HG_NS}}}version").text = "0.1"
        ET.SubElement(hg, f"{{{HG_NS}}}lab_id").text = lab_id
        ET.SubElement(hg, f"{{{HG_NS}}}created_at").text = now_iso()
        ET.SubElement(hg, f"{{{HG_NS}}}os_type").text = os_type
        ET.SubElement(hg, f"{{{HG_NS}}}profile").text = vm_profile.key
        ET.SubElement(hg, f"{{{HG_NS}}}migratable_cpu").text = "true" if migratable_cpu else "false"
        ET.SubElement(hg, f"{{{HG_NS}}}iso_path").text = iso_path
        ET.SubElement(hg, f"{{{HG_NS}}}disk_path").text = disk_path
        ET.SubElement(hg, f"{{{HG_NS}}}network_id").text = network_id
        ET.SubElement(hg, f"{{{HG_NS}}}display_mode").text = display_mode
        ET.SubElement(hg, f"{{{HG_NS}}}accel_3d").text = "true" if accel_3d else "false"
        ET.SubElement(domain, "memory", {"unit": "MiB"}).text = str(ram_mib)
        ET.SubElement(domain, "currentMemory", {"unit": "MiB"}).text = str(ram_mib)
        ET.SubElement(domain, "vcpu", {"placement": "static"}).text = str(vcpus)
        os_el = ET.SubElement(domain, "os")
        ET.SubElement(os_el, "type", {"arch": "x86_64", "machine": vm_profile.machine}).text = "hvm"
        # B1: firmware UEFI (OVMF) + NVMRAM por VM cuando el perfil lo pide.
        if vm_profile.firmware in {"uefi", "uefi-secure"}:
            want_secure = vm_profile.firmware == "uefi-secure"
            ovmf = resolve_ovmf(secure_boot=want_secure)
            secure = ovmf.get("secure_boot") == "yes"
            loader = ET.SubElement(
                os_el,
                "loader",
                {"readonly": "yes", "type": "pflash", "secure": "yes" if secure else "no"},
            )
            if ovmf.get("code"):
                loader.text = ovmf["code"]
            nvram = ET.SubElement(os_el, "nvram")
            nvram.text = str(Path(disk_path).with_suffix(".nvram"))
            if ovmf.get("vars"):
                nvram.attrib["template"] = ovmf["vars"]
        ET.SubElement(os_el, "boot", {"dev": "cdrom"})
        ET.SubElement(os_el, "boot", {"dev": "hd"})
        features = ET.SubElement(domain, "features")
        ET.SubElement(features, "acpi")
        ET.SubElement(features, "apic")
        # Secure Boot requiere SMM activado en q35/OVMF.
        if vm_profile.firmware == "uefi-secure" and resolve_ovmf(secure_boot=True).get("secure_boot") == "yes":
            ET.SubElement(features, "smm", {"state": "on"})
        if migratable_cpu:
            # CPU baseline portable: permite live migration entre equipos con CPU
            # distinta (p. ej. AMD ↔ Intel). Pierde algo de rendimiento frente a
            # host-passthrough, pero es la única forma de migrar en caliente
            # cross-vendor (el invitado no ve features específicas de un fabricante).
            cpu_el = ET.SubElement(domain, "cpu", {"mode": "custom", "match": "exact", "check": "partial"})
            ET.SubElement(cpu_el, "model", {"fallback": "allow"}).text = "qemu64"
            # qemu64 incluye svm (AMD); sin esto, migrar AMD→Intel falla con
            # «la CPU huésped no coincide: ausencia de características: svm»
            # (verificado en el UAT físico).
            ET.SubElement(cpu_el, "feature", {"policy": "disable", "name": "svm"})
        else:
            ET.SubElement(domain, "cpu", {"mode": "host-passthrough", "check": "none"})
        ET.SubElement(domain, "clock", {"offset": "utc"})
        on_poweroff = ET.SubElement(domain, "on_poweroff")
        on_poweroff.text = "destroy"
        ET.SubElement(domain, "on_reboot").text = "restart"
        ET.SubElement(domain, "on_crash").text = "restart"
        devices = ET.SubElement(domain, "devices")
        ET.SubElement(devices, "emulator").text = emulator
        disk = ET.SubElement(devices, "disk", {"type": "file", "device": "disk"})
        ET.SubElement(disk, "driver", {"name": "qemu", "type": "qcow2", "discard": "unmap"})
        ET.SubElement(disk, "source", {"file": disk_path})
        disk_is_sata = vm_profile.disk_bus != "virtio"
        disk_target_dev = "sda" if disk_is_sata else "vda"
        ET.SubElement(disk, "target", {"dev": disk_target_dev, "bus": vm_profile.disk_bus})
        cdrom = ET.SubElement(devices, "disk", {"type": "file", "device": "cdrom"})
        ET.SubElement(cdrom, "driver", {"name": "qemu", "type": "raw"})
        ET.SubElement(cdrom, "source", {"file": iso_path})
        # El CD-ROM va por SATA; si el disco principal ya ocupa 'sda', el CD usa 'sdb'.
        ET.SubElement(cdrom, "target", {"dev": "sdb" if disk_is_sata else "sda", "bus": "sata"})
        ET.SubElement(cdrom, "readonly")
        iface = ET.SubElement(devices, "interface", {"type": "network"})
        ET.SubElement(iface, "source", {"network": network_id})
        ET.SubElement(iface, "model", {"type": vm_profile.net_model})
        ET.SubElement(devices, "input", {"type": "tablet", "bus": "usb"})
        ET.SubElement(devices, "graphics", {"type": display_mode, "autoport": "yes", "listen": "127.0.0.1"})
        video = ET.SubElement(devices, "video")
        if accel_3d:
            # Aceleración 3D compartida (VirGL): la VM recibe una GPU virtio y
            # el host ejecuta su OpenGL — la GPU física se comparte, sin vfio.
            # egl-headless renderiza en el host para que la consola SPICE/VNC
            # normal muestre el contenido acelerado. Una VM así NO puede
            # live-migrarse (el contexto GL vive en el host de origen).
            model = ET.SubElement(video, "model", {"type": "virtio", "heads": "1"})
            ET.SubElement(model, "acceleration", {"accel3d": "yes"})
            egl = ET.SubElement(devices, "graphics", {"type": "egl-headless"})
            render_node = pick_render_node()
            ET.SubElement(egl, "gl", {"rendernode": render_node} if render_node else {})
        else:
            ET.SubElement(video, "model", {"type": "qxl", "ram": "65536", "vram": "65536", "vgamem": "16384", "heads": "1"})
        if display_mode == "spice":
            channel = ET.SubElement(devices, "channel", {"type": "spicevmc"})
            ET.SubElement(channel, "target", {"type": "virtio", "name": "com.redhat.spice.0"})
        ET.SubElement(devices, "memballoon", {"model": "virtio"})
        # B1: vTPM 2.0 (swtpm) — requisito de Windows 11.
        if vm_profile.tpm:
            tpm = ET.SubElement(devices, "tpm", {"model": "tpm-crb"})
            ET.SubElement(tpm, "backend", {"type": "emulator", "version": "2.0"})
        return ET.tostring(domain, encoding="unicode")

    def define_domain_xml(self, xml: str) -> None:
        # VirGL viaja con la ruta del nodo de render del equipo de ORIGEN;
        # al definir (crear, importar del Hub, restaurar…) se adapta al local.
        if "egl-headless" in xml:
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                root = None
            if root is not None and normalize_render_node_for_host(root):
                xml = ET.tostring(root, encoding="unicode")
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
            tmp.write(xml)
            xml_path = tmp.name
        try:
            self.virsh(["define", xml_path])
            logging.info("defined libvirt domain from xml: %s", xml_path)
        finally:
            Path(xml_path).unlink(missing_ok=True)

    def list_vms(self) -> list[VmSummary]:
        if not shutil.which("virsh"):
            raise HyperGeryError("Cannot list VMs because virsh is not installed. Install libvirt-clients.")
        result = self.virsh(["list", "--all", "--name"], check=False, timeout=30)
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or "Cannot list libvirt domains."
            logging.error("cannot list domains: %s", msg)
            raise HyperGeryError(msg)
        manifest_names = self.manifest_vm_names()
        summaries: list[VmSummary] = []
        for name in sorted(line.strip() for line in result.stdout.splitlines() if line.strip()):
            try:
                summary = self.get_vm(name)
            except HyperGeryError:
                continue
            if summary.lab_id or name in manifest_names:
                summaries.append(summary)
        return summaries

    def get_vm(self, name: str) -> VmSummary:
        name = validate_vm_name(name)
        dump = self.virsh(["dumpxml", name], check=False)
        if dump.returncode != 0:
            raise HyperGeryError(f"Cannot read libvirt XML for {name}: {dump.stderr.strip() or dump.stdout.strip()}")
        try:
            root = ET.fromstring(dump.stdout)
        except ET.ParseError as exc:
            raise HyperGeryError(f"Cannot parse libvirt XML for {name}: {exc}") from exc
        managed = root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}managed")
        lab = root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}lab_id")
        if managed is None and name not in self.manifest_vm_names():
            raise HyperGeryError(f"{name} is not managed by HyperGery.")
        state_result = self.virsh(["domstate", name], check=False)
        state = self.normalize_vm_state(state_result.stdout.strip()) if state_result.returncode == 0 else "unknown"
        memory = root.find("./memory")
        vcpu = root.find("./vcpu")
        disk_path = ""
        iso_path = ""
        for disk in root.findall("./devices/disk"):
            source = disk.find("source")
            if source is None:
                continue
            if disk.attrib.get("device") == "disk":
                disk_path = source.attrib.get("file", "")
            elif disk.attrib.get("device") == "cdrom":
                iso_path = source.attrib.get("file", "")
        network = ""
        iface = root.find("./devices/interface/source")
        if iface is not None:
            network = iface.attrib.get("network", "")
        graphics = ""
        gfx = root.find("./devices/graphics")
        if gfx is not None:
            graphics = gfx.attrib.get("type", "")
        virtual, actual = self.disk_sizes(disk_path)
        return VmSummary(
            name=name,
            state=state,
            lab_id=lab.text if lab is not None and lab.text else "",
            ram_mib=self.memory_to_mib(memory.text, memory.attrib.get("unit", "")) if memory is not None else None,
            vcpus=self.optional_int(vcpu.text) if vcpu is not None else None,
            disk_path=disk_path,
            disk_virtual=virtual,
            disk_actual=actual,
            iso_path=iso_path,
            network=network,
            graphics=graphics,
            xml=dump.stdout,
        )

    def disk_sizes(self, disk_path: str) -> tuple[str, str]:
        if not disk_path or not Path(disk_path).exists() or not shutil.which("qemu-img"):
            return "", ""
        result = self.qemu_img(["info", "--output=json", disk_path], check=False)
        if result.returncode != 0:
            return "", ""
        try:
            info = json.loads(result.stdout)
            virtual = self.human_bytes(int(info.get("virtual-size", 0)))
            actual = self.human_bytes(int(info.get("actual-size", 0)))
            return virtual, actual
        except (ValueError, json.JSONDecodeError, TypeError):
            return "", ""

    @staticmethod
    def optional_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value.strip())
        except (AttributeError, ValueError):
            return None

    @classmethod
    def memory_to_mib(cls, value: str | None, unit: str | None) -> int | None:
        parsed = cls.optional_int(value)
        if parsed is None:
            return None
        normalized = (unit or "KiB").strip().lower()
        if normalized in {"mib", "mb"}:
            return parsed
        if normalized in {"kib", "kb"}:
            return parsed // 1024
        if normalized in {"gib", "gb"}:
            return parsed * 1024
        if normalized in {"b", "bytes"}:
            return parsed // (1024 * 1024)
        return parsed

    @staticmethod
    def human_bytes(value: int) -> str:
        size = float(value)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if size < 1024 or unit == "TiB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{value} B"

    def start_vm(self, name: str) -> None:
        name = validate_vm_name(name)
        # HG-BUG-0028: no arrancar una VM con una migración en vuelo sin
        # confirmar (podría estar ya corriendo en el destino → doble-activa).
        try:
            from .migration_journal import MigrationJournal
        except Exception:  # pragma: no cover - defensivo ante import parcial
            MigrationJournal = None  # type: ignore[assignment]
        if MigrationJournal is not None:
            MigrationJournal().assert_startable(name)
        self.virsh(["start", name])
        logging.info("started vm: %s", name)

    def press_boot_key(self, name: str) -> None:
        """Pulsa «espacio» en el guest vía libvirt (independiente del display).

        Caza el «Press any key to boot from CD» del instalador de Windows sin
        necesitar la consola VNC conectada (funciona también con SPICE)."""
        self.virsh(["send-key", validate_vm_name(name), "KEY_SPACE"], check=False, timeout=10)

    def boot_keypress_sweep(self, name: str, *, presses: int = 14, interval_seconds: float = 1.2) -> None:
        """Barrido de pulsaciones durante el arranque (~1.5–18 s tras start).

        El prompt del CD aparece a los ~6–10 s (tras la init de OVMF) y dura
        ~5 s; el instalador no pinta UI hasta pasados ~25 s, así que este rango
        lo caza sin provocar clics fantasma en pantallas posteriores. Pensado
        para ejecutarse en un worker (bloquea ~17 s)."""
        time.sleep(1.5)
        for _ in range(max(1, presses)):
            self.press_boot_key(name)
            time.sleep(interval_seconds)

    def save_vm(self, name: str, state_path: str | Path) -> Path:
        """Freeze a running VM and dump its full RAM+CPU state to a file.

        State-preserving migration: after this the VM is shut off but its exact
        running state lives in `state_path` and can be restored to continue
        where it left off (not a reboot). Requires the VM to be running.
        """
        name = validate_vm_name(name)
        target = Path(state_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        result = self.virsh(["save", name, str(target)], check=False, timeout=600)
        if result.returncode != 0:
            raise HyperGeryError(f"Cannot save state for {name}: {result.stderr.strip() or result.stdout.strip()}")
        logging.info("saved vm state: %s -> %s", name, target)
        return target

    def restore_vm(self, state_path: str | Path, xml_path: str | Path | None = None) -> None:
        """Restore a VM from a saved state file — it CONTINUES from that exact
        state. Optional xml_path overrides the domain XML (e.g. to fix the disk
        path / network on a different host) without losing the RAM state."""
        source = Path(state_path).expanduser()
        if not source.is_file():
            raise HyperGeryError(f"Saved state file not found: {source}")
        args = ["restore", str(source)]
        if xml_path is not None:
            args += ["--xml", str(Path(xml_path).expanduser())]
        result = self.virsh(args, check=False, timeout=600)
        if result.returncode != 0:
            raise HyperGeryError(f"Cannot restore state from {source}: {result.stderr.strip() or result.stdout.strip()}")
        logging.info("restored vm state from: %s", source)

    def vm_state(self, name: str) -> str:
        result = self.virsh(["domstate", validate_vm_name(name)], check=False)
        if result.returncode != 0:
            raise HyperGeryError(result.stderr.strip() or result.stdout.strip() or f"Cannot read state for {name}.")
        return self.normalize_vm_state(result.stdout.strip())

    @staticmethod
    def normalize_vm_state(state: str) -> str:
        value = state.strip().lower()
        localized = {
            "ejecutando": "running",
            "en ejecucion": "running",
            "en ejecución": "running",
            "pausado": "paused",
            "pausada": "paused",
            "apagado": "shut off",
            "apagada": "shut off",
            "cerrado": "shut off",
            "cerrada": "shut off",
        }
        return localized.get(value, state.strip() or "unknown")

    def wait_for_state(self, name: str, desired_states: set[str], *, timeout_seconds: int = 120, interval_seconds: float = 2.0) -> str:
        name = validate_vm_name(name)
        normalized_desired = {state.lower() for state in desired_states}
        deadline = time.monotonic() + timeout_seconds
        last_state = "unknown"
        while time.monotonic() <= deadline:
            last_state = self.vm_state(name)
            if last_state.lower() in normalized_desired:
                logging.info("vm=%s reached state=%s", name, last_state)
                return last_state
            time.sleep(interval_seconds)
        raise HyperGeryError(
            f"Timed out waiting for {name} to reach {', '.join(sorted(desired_states))}; last state was {last_state}."
        )

    def shutdown_vm(self, name: str) -> None:
        self.virsh(["shutdown", validate_vm_name(name)])
        logging.info("requested acpi shutdown vm: %s", name)

    def force_off_vm(self, name: str) -> None:
        self.virsh(["destroy", validate_vm_name(name)])
        logging.info("forced off vm: %s", name)

    def undefine_domain(self, name: str) -> None:
        name = validate_vm_name(name)
        first = self.virsh(["undefine", name, "--snapshots-metadata", "--nvram"], check=False)
        if first.returncode == 0:
            logging.info("undefined libvirt domain with nvram cleanup: %s", name)
            return
        second = self.virsh(["undefine", name, "--snapshots-metadata"], check=False)
        if second.returncode == 0:
            logging.info("undefined libvirt domain: %s", name)
            return
        msg = second.stderr.strip() or second.stdout.strip() or first.stderr.strip() or first.stdout.strip()
        logging.error("failed to undefine vm=%s: %s", name, msg)
        raise HyperGeryError(f"Could not undefine {name}; disk deletion was not attempted: {msg}")

    def delete_vm(self, name: str, *, delete_disks: bool) -> None:
        name = validate_vm_name(name)
        vm = self.get_vm(name)
        if vm.state.lower() in {"running", "paused"}:
            raise HyperGeryError("Stop the VM before deleting it.")
        self.undefine_domain(name)
        if delete_disks and vm.disk_path:
            disk = Path(vm.disk_path).resolve()
            allowed_base = (self.vms_dir / name).resolve()
            manifest_disks = self.manifest_disk_paths()
            is_hypergery_default_disk = allowed_base in disk.parents
            is_manifest_disk = disk in manifest_disks
            if (is_hypergery_default_disk or is_manifest_disk) and disk.exists():
                disk.unlink(missing_ok=True)
                logging.info("deleted disk for vm=%s disk=%s", name, disk)
                if allowed_base.exists():
                    try:
                        allowed_base.rmdir()
                    except OSError:
                        pass
            else:
                raise HyperGeryError(
                    f"Domain was undefined, but disk was kept because it was not recorded as HyperGery-managed: {disk}"
                )
        self.remove_vm_from_labs(name)
        logging.info("deleted vm: %s delete_disks=%s", name, delete_disks)

    def open_console(self, name: str) -> None:
        name = validate_vm_name(name)
        virt_viewer = shutil.which("virt-viewer")
        remote_viewer = shutil.which("remote-viewer")
        if virt_viewer:
            self.launch_viewer([virt_viewer, "--connect", LIBVIRT_URI, name])
            logging.info("opened virt-viewer for vm: %s", name)
            return
        if remote_viewer:
            display = self.virsh(["domdisplay", name])
            uri = display.stdout.strip()
            if not uri:
                raise HyperGeryError("libvirt did not return a graphical display URI for this VM.")
            self.launch_viewer([remote_viewer, uri])
            logging.info("opened remote-viewer for vm: %s uri=%s", name, uri)
            return
        raise HyperGeryError("No console viewer installed. Install virt-viewer or remote-viewer.")

    def get_console_display(self, name: str) -> dict[str, object]:
        name = validate_vm_name(name)
        vm = self.get_vm(name)
        domdisplay = self.virsh(["domdisplay", name], check=False)
        uri = domdisplay.stdout.strip() if domdisplay.returncode == 0 else ""
        return parse_console_display(uri, vm.xml).__dict__

    def launch_viewer(self, args: list[str]) -> None:
        proc = subprocess.Popen(
            args,
            env=self.external_tool_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1)
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            msg = stderr.strip() or stdout.strip() or f"viewer exited with code {proc.returncode}"
            raise HyperGeryError(f"Failed to open VM console: {msg}")

    @staticmethod
    def external_tool_env() -> dict[str, str]:
        env = os.environ.copy()
        for key in list(env):
            if key == "SNAP" or key.startswith("SNAP_") or key in {
                "GTK_PATH",
                "LD_LIBRARY_PATH",
                "LD_PRELOAD",
                "GIO_EXTRA_MODULES",
                "GI_TYPELIB_PATH",
                "PYTHONHOME",
            }:
                env.pop(key, None)
        xdg_data_dirs = env.get("XDG_DATA_DIRS")
        if xdg_data_dirs:
            clean_dirs = [entry for entry in xdg_data_dirs.split(":") if "/snap/code/" not in entry]
            env["XDG_DATA_DIRS"] = ":".join(clean_dirs)
        return env

    def list_snapshots(self, name: str) -> list[str]:
        result = self.virsh(["snapshot-list", "--domain", validate_vm_name(name), "--name"], check=False)
        if result.returncode != 0:
            raise HyperGeryError(result.stderr.strip() or result.stdout.strip() or "Cannot list snapshots.")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def create_snapshot(self, name: str, snapshot_name: str, description: str = "") -> None:
        snap = validate_vm_name(snapshot_name)
        args = ["snapshot-create-as", "--domain", validate_vm_name(name), "--name", snap]
        if description:
            args.extend(["--description", description])
        self.virsh(args, timeout=600)
        logging.info("created snapshot vm=%s snapshot=%s", name, snap)

    def revert_snapshot(self, name: str, snapshot_name: str) -> None:
        self.virsh(["snapshot-revert", "--domain", validate_vm_name(name), "--snapshotname", validate_vm_name(snapshot_name)], timeout=600)
        logging.info("reverted snapshot vm=%s snapshot=%s", name, snapshot_name)

    def branch_snapshot(self, name: str, from_snapshot: str, new_snapshot: str, description: str = "") -> None:
        """v1.3 snapshot branching seguro: vuelve a un snapshot conocido y
        crea ahí una rama nueva. Falla limpio si el origen no existe o el
        destino ya existe (nunca pisa un snapshot)."""
        snapshots = self.list_snapshots(name)
        source = validate_vm_name(from_snapshot)
        branch = validate_vm_name(new_snapshot)
        if source not in snapshots:
            raise HyperGeryError(f"Snapshot does not exist: {source}")
        if branch in snapshots:
            raise HyperGeryError(f"Snapshot already exists: {branch}")
        self.revert_snapshot(name, source)
        self.create_snapshot(name, branch, description or f"branch of {source}")
        logging.info("branched snapshot vm=%s from=%s new=%s", name, source, branch)

    def delete_snapshot(self, name: str, snapshot_name: str) -> None:
        self.virsh(["snapshot-delete", "--domain", validate_vm_name(name), "--snapshotname", validate_vm_name(snapshot_name)], timeout=600)
        logging.info("deleted snapshot vm=%s snapshot=%s", name, snapshot_name)

    def update_settings(
        self,
        name: str,
        *,
        ram_mib: int,
        vcpus: int,
        boot_iso: str,
        network_mode: str,
        display_mode: str,
        lab_id: str,
    ) -> None:
        name = validate_vm_name(name)
        vm = self.get_vm(name)
        if vm.state.lower() != "shut off":
            raise HyperGeryError("Settings can only be changed while the VM is shut off.")
        if ram_mib < 256 or vcpus < 1:
            raise HyperGeryError("RAM and vCPU values must be positive.")
        if display_mode not in {"spice", "vnc"}:
            raise HyperGeryError("Display mode must be spice or vnc.")
        iso = Path(boot_iso).expanduser().resolve() if boot_iso else None
        if iso and not iso.is_file():
            raise HyperGeryError(f"Boot ISO does not exist: {iso}")
        network_id = self.ensure_network(lab_id, network_mode)
        root = ET.fromstring(vm.xml)
        for tag in ("memory", "currentMemory"):
            el = root.find(tag)
            if el is not None:
                el.attrib["unit"] = "MiB"
                el.text = str(ram_mib)
        vcpu_el = root.find("vcpu")
        if vcpu_el is not None:
            vcpu_el.text = str(vcpus)
        devices = root.find("./devices")
        if devices is None:
            devices = ET.SubElement(root, "devices")

        iface = root.find("./devices/interface/source")
        if iface is not None:
            iface.attrib["network"] = network_id
        else:
            interface = root.find("./devices/interface")
            if interface is None:
                interface = ET.SubElement(devices, "interface", {"type": "network"})
            ET.SubElement(interface, "source", {"network": network_id})
            model = interface.find("model")
            if model is None:
                ET.SubElement(interface, "model", {"type": "virtio"})
        normalize_graphics_audio_for_display(root, display_mode)
        cdrom_source = None
        for disk in root.findall("./devices/disk"):
            if disk.attrib.get("device") == "cdrom":
                cdrom_source = disk.find("source")
                break
        if cdrom_source is not None:
            if iso:
                cdrom_source.attrib["file"] = str(iso)
            else:
                cdrom_source.attrib.pop("file", None)
        hg = root.find(f"./metadata/{{{HG_NS}}}hypergery")
        if hg is not None:
            for tag, value in (
                ("iso_path", str(iso) if iso else ""),
                ("network_id", network_id),
                ("lab_id", lab_id),
                ("display_mode", display_mode),
            ):
                child = hg.find(f"{{{HG_NS}}}{tag}")
                if child is None:
                    child = ET.SubElement(hg, f"{{{HG_NS}}}{tag}")
                child.text = value
        self.define_domain_xml(ET.tostring(root, encoding="unicode"))
        self.move_vm_to_lab(vm.lab_id, lab_id, name, vm.disk_path, str(iso) if iso else "", network_id)
        logging.info(
            "updated settings vm=%s ram=%s vcpus=%s iso=%s network=%s display=%s",
            name,
            ram_mib,
            vcpus,
            iso,
            network_id,
            display_mode,
        )

    def clone_vm(self, source_name: str, clone_name: str) -> VmSummary:
        source = self.get_vm(source_name)
        if source.state.lower() != "shut off":
            raise HyperGeryError("Clone is only supported while the source VM is shut off.")
        clone_name = validate_vm_name(clone_name)
        if self.virsh(["dominfo", clone_name], check=False).returncode == 0:
            raise HyperGeryError(f"A libvirt domain named {clone_name} already exists.")
        if not source.disk_path:
            raise HyperGeryError("Source VM has no disk path in libvirt XML.")
        clone_dir = self.vms_dir / clone_name
        clone_dir.mkdir(parents=True, exist_ok=True)
        clone_disk = clone_dir / f"{clone_name}.qcow2"
        # Convertir/copiar el disco completo es una operación larga; usar el
        # timeout extendido y configurable en vez del de 120s por defecto.
        self.qemu_img(["convert", "-O", "qcow2", source.disk_path, str(clone_disk)], timeout=LONG_OPERATION_TIMEOUT)
        self.grant_libvirt_qemu_access(clone_disk)
        root = ET.fromstring(source.xml)
        root.find("name").text = clone_name
        uuid_el = root.find("uuid")
        if uuid_el is not None:
            uuid_el.text = str(uuid.uuid4())
        for mac in root.findall("./devices/interface/mac"):
            parent = root.find("./devices/interface")
            if parent is not None:
                parent.remove(mac)
        for disk in root.findall("./devices/disk"):
            if disk.attrib.get("device") == "disk":
                source_el = disk.find("source")
                if source_el is not None:
                    source_el.attrib["file"] = str(clone_disk)
        hg = root.find(f"./metadata/{{{HG_NS}}}hypergery")
        lab_id = source.lab_id or "default-lab"
        if hg is not None:
            for tag, value in (("created_at", now_iso()), ("disk_path", str(clone_disk)), ("lab_id", lab_id)):
                child = hg.find(f"{{{HG_NS}}}{tag}")
                if child is None:
                    child = ET.SubElement(hg, f"{{{HG_NS}}}{tag}")
                child.text = value
        self.define_domain_xml(ET.tostring(root, encoding="unicode"))
        self.update_lab_for_vm(lab_id, clone_name, str(clone_disk), source.iso_path, source.network)
        logging.info("cloned vm source=%s clone=%s", source_name, clone_name)
        return self.get_vm(clone_name)

    def recent_logs(self, lines: int = 200) -> str:
        if not self.log_file.exists():
            return ""
        data = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])

    def install_commands(self) -> str:
        return "\n".join(
            [
                "sudo apt update",
                "sudo apt install qemu-kvm qemu-system-x86 libvirt-daemon-system libvirt-clients virt-viewer qemu-utils ovmf python3-tk python3-pip python3-venv",
                "cd hypergery-ubuntu && python3 -m pip install -e .",
                "sudo systemctl enable --now libvirtd",
                "sudo usermod -aG kvm,libvirt $USER",
                "# Log out and back in after changing groups.",
            ]
        )
