"""GPU passthrough VFIO/PCI (v1.7).

Asignar una GPU física a una VM:
1. Detección de GPUs y grupos IOMMU (solo lectura de sysfs).
2. Preflight: IOMMU activo, grupo IOMMU limpio, vfio-pci disponible y —
   **regla de PARADA DURA** — jamás la GPU del escritorio (boot_vga/en uso)
   sin una segunda GPU presente.
3. Bind a vfio-pci vía sysfs (driver_override) con rollback al driver
   original si algo falla.
4. `<hostdev>` PCI en el domain XML + ocultar el hipervisor si la GPU es
   NVIDIA (vendor 10de) + aviso de OVMF/UEFI.
5. Los cambios de host (GRUB/initramfs) solo se PROPONEN: el agente nunca
   edita grub ni regenera initramfs; eso requiere confirmación humana y
   reinicio.

Una VM con passthrough NO se puede live-migrar: el preflight de migración
(v1.5) ya la bloquea al ver `<hostdev>`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .errors import HyperGeryError
from .hglog import get_logger

PCI_CLASS_DISPLAY_PREFIX = "0x03"
NVIDIA_VENDOR = "0x10de"

# Funciones que es normal encontrar junto a la GPU en su grupo IOMMU (la
# función de audio HDMI y demás funciones del MISMO dispositivo físico).
SAME_SLOT_OK = True


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def connected_displays(sysfs_root: str | Path = "/sys") -> dict[str, list[str]]:
    """Conectores DRM con monitor enchufado, por dirección PCI de su GPU."""
    root = Path(sysfs_root)
    drm = root / "class" / "drm"
    displays: dict[str, list[str]] = {}
    if not drm.is_dir():
        return displays
    for card in sorted(drm.iterdir()):
        if not card.name.startswith("card") or "-" in card.name:
            continue
        device_link = card / "device"
        if not device_link.exists():
            continue
        address = device_link.resolve().name
        for connector in sorted(card.glob(card.name + "-*")):
            if _read(connector / "status") == "connected":
                displays.setdefault(address, []).append(connector.name.split("-", 1)[1])
    return displays


def list_pci_gpus(sysfs_root: str | Path = "/sys") -> list[dict[str, Any]]:
    """GPUs (clase PCI 0x03xxxx) con driver, boot_vga, grupo IOMMU y pantallas."""
    root = Path(sysfs_root)
    devices_dir = root / "bus" / "pci" / "devices"
    gpus: list[dict[str, Any]] = []
    if not devices_dir.is_dir():
        return gpus
    displays = connected_displays(root)
    for device in sorted(devices_dir.iterdir()):
        if not _read(device / "class").startswith(PCI_CLASS_DISPLAY_PREFIX):
            continue
        driver_link = device / "driver"
        driver = driver_link.resolve().name if driver_link.is_symlink() else ""
        group_link = device / "iommu_group"
        group = group_link.resolve().name if group_link.is_symlink() else ""
        group_devices: list[str] = []
        if group:
            group_dir = root / "kernel" / "iommu_groups" / group / "devices"
            if group_dir.is_dir():
                group_devices = sorted(entry.name for entry in group_dir.iterdir())
        gpus.append(
            {
                "address": device.name,
                "vendor_id": _read(device / "vendor"),
                "device_id": _read(device / "device"),
                "class": _read(device / "class"),
                "driver": driver,
                "boot_vga": _read(device / "boot_vga") == "1",
                "iommu_group": group,
                "iommu_group_devices": group_devices,
                "connected_displays": displays.get(device.name, []),
            }
        )
    return gpus


def iommu_group_members(address: str, sysfs_root: str | Path = "/sys") -> list[str]:
    """Todos los dispositivos del grupo IOMMU de ``address`` (él incluido)."""
    address = _validate_address(address)
    root = Path(sysfs_root)
    group_link = root / "bus" / "pci" / "devices" / address / "iommu_group"
    if not group_link.is_symlink():
        return [address]
    group_dir = root / "kernel" / "iommu_groups" / group_link.resolve().name / "devices"
    if not group_dir.is_dir():
        return [address]
    return sorted(entry.name for entry in group_dir.iterdir())


def iommu_status(sysfs_root: str | Path = "/sys", cmdline_path: str | Path = "/proc/cmdline") -> dict[str, Any]:
    root = Path(sysfs_root)
    groups_dir = root / "kernel" / "iommu_groups"
    groups = sorted(entry.name for entry in groups_dir.iterdir()) if groups_dir.is_dir() else []
    cmdline = _read(Path(cmdline_path))
    flags = [flag for flag in ("intel_iommu=on", "amd_iommu=on", "iommu=pt") if flag in cmdline]
    return {
        "enabled": bool(groups),
        "groups_count": len(groups),
        "kernel_flags": flags,
        "cmdline": cmdline,
    }


def propose_host_changes(cpu_vendor: str = "") -> dict[str, Any]:
    """Cambios de host que el usuario debe aplicar a mano (+ reinicio).

    El agente NUNCA los aplica: editar GRUB/initramfs sin confirmación podría
    dejar el equipo sin arrancar o sin pantalla.
    """
    vendor = (cpu_vendor or _read(Path("/proc/cpuinfo")).split("vendor_id", 1)[-1][:60]).lower()
    iommu_flag = "amd_iommu=on" if "amd" in vendor else "intel_iommu=on"
    return {
        "applied": False,
        "requires_reboot": True,
        "grub": {
            "file": "/etc/default/grub",
            "change": f'añadir "{iommu_flag} iommu=pt" a GRUB_CMDLINE_LINUX_DEFAULT',
            "after": "sudo update-grub && sudo reboot",
        },
        "initramfs": {
            "file": "/etc/initramfs-tools/modules",
            "change": "añadir: vfio vfio_iommu_type1 vfio_pci",
            "after": "sudo update-initramfs -u",
        },
        "warning": "Cambios de arranque del HOST: aplicar manualmente, revisar y reiniciar. El agente solo los propone.",
    }


def _validate_address(address: str) -> str:
    import re

    clean = str(address or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", clean):
        raise HyperGeryError(f"Invalid PCI address: {address!r} (expected dddd:bb:dd.f)")
    return clean


def preflight_gpu_passthrough(
    gpu_address: str,
    *,
    sysfs_root: str | Path = "/sys",
    cmdline_path: str | Path = "/proc/cmdline",
    modules_path: str | Path = "/proc/modules",
    lib_modules_root: str | Path = "/lib/modules",
) -> dict[str, Any]:
    """Comprobaciones previas. NO modifica nada."""
    gpu_address = _validate_address(gpu_address)
    errors: list[str] = []
    warnings: list[str] = []

    iommu = iommu_status(sysfs_root, cmdline_path)
    if not iommu["enabled"]:
        errors.append(
            "IOMMU is not active (no /sys/kernel/iommu_groups). Apply the proposed GRUB change "
            "(intel_iommu=on/amd_iommu=on + iommu=pt) and reboot."
        )

    gpus = list_pci_gpus(sysfs_root)
    gpu = next((entry for entry in gpus if entry["address"] == gpu_address), None)
    if gpu is None:
        errors.append(f"PCI device {gpu_address} is not a display controller on this host.")
        return {"ok": False, "errors": errors, "warnings": warnings, "iommu": iommu, "gpu": None}

    # PARADA DURA: nunca la GPU del escritorio sin una segunda GPU.
    others = [entry for entry in gpus if entry["address"] != gpu_address]
    if gpu["boot_vga"] or gpu["driver"] in DISPLAY_DRIVERS:
        if not others:
            errors.append(
                f"{gpu_address} is the host display GPU (driver {gpu['driver'] or '?'}, "
                f"boot_vga={gpu['boot_vga']}) and there is NO second GPU: unbinding it would "
                "kill the host display. Refusing."
            )
        else:
            warnings.append(
                f"{gpu_address} currently drives a display ({gpu['driver']}); make sure the desktop "
                f"runs on another GPU ({', '.join(o['address'] for o in others)}) before binding."
            )

    # PARADA DURA 2: si el ÚNICO monitor conectado cuelga de esta GPU, soltar
    # su driver mataría la sesión gráfica aunque exista otra GPU instalada.
    if gpu.get("connected_displays"):
        others_with_display = [entry for entry in others if entry.get("connected_displays")]
        if not others_with_display:
            errors.append(
                f"{gpu_address} drives the only connected display(s) "
                f"({', '.join(gpu['connected_displays'])}). Move the monitor cable to another GPU "
                "(e.g. the motherboard video output) and log in again before passing this GPU through."
            )
        else:
            warnings.append(
                f"{gpu_address} has a display connected ({', '.join(gpu['connected_displays'])}); "
                "it will go dark when the GPU is detached from the host."
            )

    # Grupo IOMMU limpio: solo funciones del mismo slot (GPU + su audio HDMI).
    if gpu["iommu_group"]:
        slot = gpu_address.rsplit(".", 1)[0]
        foreign = [dev for dev in gpu["iommu_group_devices"] if not dev.startswith(slot)]
        if foreign:
            errors.append(
                f"IOMMU group {gpu['iommu_group']} is not clean: it also contains {', '.join(foreign)}. "
                "Everything in the group must be passed together (or use a different slot/ACS)."
            )
    elif iommu["enabled"]:
        errors.append(f"{gpu_address} has no IOMMU group; passthrough is impossible for it.")

    # vfio-pci disponible (cargado o disponible como módulo).
    modules = _read(Path(modules_path))
    vfio_loaded = any(line.split()[0] in {"vfio_pci", "vfio-pci"} for line in modules.splitlines() if line)
    vfio_available = vfio_loaded or bool(
        list(Path(lib_modules_root).glob("*/kernel/drivers/vfio/pci/vfio-pci.ko*"))
    )
    if not vfio_available:
        errors.append("vfio-pci kernel module is not loaded nor available.")

    if gpu["vendor_id"] == NVIDIA_VENDOR:
        warnings.append(
            "NVIDIA GPU: the domain XML will hide the hypervisor (kvm hidden + vendor_id) to avoid "
            "the legacy Code 43 driver check."
        )
    warnings.append("The VM should use UEFI/OVMF firmware for reliable GPU passthrough.")
    warnings.append("A VM with GPU passthrough cannot be live-migrated (the migration preflight blocks it).")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "iommu": iommu, "gpu": gpu}


DISPLAY_DRIVERS = {"i915", "amdgpu", "nouveau", "nvidia", "radeon"}


def ensure_safe_to_detach(address: str, sysfs_root: str | Path = "/sys") -> None:
    """PARADA DURA también en el camino de bind directo (HG-BUG-0025).

    Antes solo ``attach_gpu_to_vm`` pasaba por el preflight; ``v1 gpu bind``
    podía desvincular la GPU del escritorio directamente. Esta comprobación
    corre SIEMPRE antes de tocar el driver: si el dispositivo es la única
    GPU de display del host, se rechaza sin opción de bypass.
    """
    address = _validate_address(address)
    gpus = list_pci_gpus(sysfs_root)
    gpu = next((entry for entry in gpus if entry["address"] == address), None)
    if gpu is None:
        return  # no es una GPU (p. ej. una NIC para pruebas): sin restricción extra
    others = [entry for entry in gpus if entry["address"] != address]
    if (gpu["boot_vga"] or gpu["driver"] in DISPLAY_DRIVERS) and not others:
        raise HyperGeryError(
            f"{address} is the host display GPU (driver {gpu['driver'] or '?'}, boot_vga={gpu['boot_vga']}) "
            "and there is no second GPU: detaching it would kill the host display. Refusing."
        )
    if gpu.get("connected_displays") and not any(entry.get("connected_displays") for entry in others):
        raise HyperGeryError(
            f"{address} drives the only connected display(s) ({', '.join(gpu['connected_displays'])}): "
            "detaching it would kill the host display. Move the monitor to another GPU first. Refusing."
        )


class VfioBinder:
    """Bind/unbind de un dispositivo PCI a vfio-pci vía sysfs, con rollback.

    Operaciones de escritura en sysfs (normalmente requieren root). Todas las
    rutas cuelgan de ``sysfs_root`` para poder probarse sobre un árbol falso.
    """

    def __init__(self, sysfs_root: str | Path = "/sys") -> None:
        self.root = Path(sysfs_root)

    def _device_dir(self, address: str) -> Path:
        device = self.root / "bus" / "pci" / "devices" / address
        if not device.is_dir():
            raise HyperGeryError(f"PCI device not found: {address}")
        return device

    def current_driver(self, address: str) -> str:
        link = self._device_dir(address) / "driver"
        return link.resolve().name if link.is_symlink() else ""

    def _write(self, path: Path, value: str) -> None:
        try:
            path.write_text(value, encoding="utf-8")
        except OSError as exc:
            raise HyperGeryError(f"sysfs write failed ({path}): {exc}") from exc

    def bind_to_vfio(self, address: str, *, confirm: bool = False) -> dict[str, Any]:
        """driver_override=vfio-pci → unbind del driver actual → probe.

        Si el paso final falla se restaura el driver original (rollback).
        """
        address = _validate_address(address)
        if not confirm:
            raise HyperGeryError("Binding a GPU to vfio-pci requires confirm=True (it detaches it from the host).")
        ensure_safe_to_detach(address, self.root)
        device = self._device_dir(address)
        original = self.current_driver(address)
        if original in {"vfio-pci", "vfio_pci"}:
            return {"address": address, "driver": "vfio-pci", "changed": False}
        log = get_logger()
        self._write(device / "driver_override", "vfio-pci")
        try:
            if original:
                self._write(device / "driver" / "unbind", address)
            self._write(self.root / "bus" / "pci" / "drivers_probe", address)
            bound = self.current_driver(address)
            if bound not in {"vfio-pci", "vfio_pci"}:
                raise HyperGeryError(f"Device did not bind to vfio-pci (driver now: {bound or 'none'}).")
        except HyperGeryError:
            # Rollback: quitar el override y devolver el driver original.
            try:
                self._write(device / "driver_override", "")
                if original:
                    self._write(self.root / "bus" / "pci" / "drivers" / original / "bind", address)
            except HyperGeryError as rollback_exc:
                log.error("hosts", f"vfio rollback failed for {address}: {rollback_exc}")
            raise
        log.info("hosts", f"{address} bound to vfio-pci (was: {original or 'none'})")
        return {"address": address, "driver": "vfio-pci", "previous_driver": original, "changed": True}

    def bind_group_to_vfio(self, address: str, *, confirm: bool = False) -> dict[str, Any]:
        """Bind a vfio-pci de TODO el grupo IOMMU de ``address``.

        VFIO exige que ningún miembro del grupo conserve su driver de host
        (qemu falla con «group is not viable» si, p. ej., la función de audio
        HDMI sigue en snd_hda_intel). Si un miembro falla, se devuelven a su
        driver original los ya bindeados.
        """
        address = _validate_address(address)
        if not confirm:
            raise HyperGeryError("Binding a GPU to vfio-pci requires confirm=True (it detaches it from the host).")
        members = iommu_group_members(address, self.root)
        done: list[dict[str, Any]] = []
        log = get_logger()
        try:
            for member in members:
                done.append(self.bind_to_vfio(member, confirm=True))
        except HyperGeryError:
            for entry in reversed(done):
                if not entry.get("changed"):
                    continue
                try:
                    self.unbind_from_vfio(entry["address"], entry.get("previous_driver", ""))
                except HyperGeryError as rollback_exc:
                    log.error("hosts", f"vfio group rollback failed for {entry['address']}: {rollback_exc}")
            raise
        return {"address": address, "group_devices": done}

    def unbind_group_from_vfio(self, address: str) -> dict[str, Any]:
        """Devuelve al host todo el grupo IOMMU (drivers_probe restaura el nativo)."""
        address = _validate_address(address)
        members = iommu_group_members(address, self.root)
        return {"address": address, "group_devices": [self.unbind_from_vfio(member) for member in members]}

    def unbind_from_vfio(self, address: str, original_driver: str = "") -> dict[str, Any]:
        """Devuelve el dispositivo al host (driver original o drivers_probe)."""
        address = _validate_address(address)
        device = self._device_dir(address)
        current = self.current_driver(address)
        if current not in {"vfio-pci", "vfio_pci"}:
            return {"address": address, "driver": current, "changed": False}
        self._write(device / "driver_override", "")
        self._write(device / "driver" / "unbind", address)
        if original_driver:
            self._write(self.root / "bus" / "pci" / "drivers" / original_driver / "bind", address)
        else:
            self._write(self.root / "bus" / "pci" / "drivers_probe", address)
        return {"address": address, "driver": self.current_driver(address), "changed": True}


def hostdev_xml(address: str) -> str:
    address = _validate_address(address)
    domain, bus, rest = address.split(":")
    slot, function = rest.split(".")
    return (
        "<hostdev mode='subsystem' type='pci' managed='yes'>\n"
        "  <source>\n"
        f"    <address domain='0x{domain}' bus='0x{bus}' slot='0x{slot}' function='0x{function}'/>\n"
        "  </source>\n"
        "</hostdev>"
    )


def attach_gpu_to_domain_xml(
    domain_xml: str, address: str, *, vendor_id: str = "", extra_addresses: tuple[str, ...] = ()
) -> str:
    """Añade los <hostdev> al XML del dominio (+ ocultar hipervisor si NVIDIA).

    ``extra_addresses``: resto de funciones del mismo slot (audio HDMI, USB…);
    deben viajar con la GPU porque comparten grupo IOMMU.
    """
    address = _validate_address(address)
    root = ET.fromstring(domain_xml)
    devices = root.find("./devices")
    if devices is None:
        devices = ET.SubElement(root, "devices")
    devices.append(ET.fromstring(hostdev_xml(address)))
    for extra in extra_addresses:
        devices.append(ET.fromstring(hostdev_xml(extra)))

    if vendor_id == NVIDIA_VENDOR:
        features = root.find("./features")
        if features is None:
            features = ET.SubElement(root, "features")
        kvm = features.find("kvm")
        if kvm is None:
            kvm = ET.SubElement(features, "kvm")
        hidden = kvm.find("hidden")
        if hidden is None:
            hidden = ET.SubElement(kvm, "hidden")
        hidden.set("state", "on")
        hyperv = features.find("hyperv")
        if hyperv is None:
            hyperv = ET.SubElement(features, "hyperv")
        vendor = hyperv.find("vendor_id")
        if vendor is None:
            vendor = ET.SubElement(hyperv, "vendor_id")
        vendor.set("state", "on")
        vendor.set("value", "HyperGeryKVM")
    return ET.tostring(root, encoding="unicode")


def attach_gpu_to_vm(backend: Any, vm_name: str, gpu_address: str, *, confirm: bool = False,
                     sysfs_root: str | Path = "/sys") -> dict[str, Any]:
    """Añade la GPU al XML de la VM (apagada) tras un preflight limpio."""
    if not confirm:
        raise HyperGeryError("Attaching a GPU requires confirm=True.")
    preflight = preflight_gpu_passthrough(gpu_address, sysfs_root=sysfs_root)
    if not preflight["ok"]:
        raise HyperGeryError("GPU passthrough preflight failed: " + "; ".join(preflight["errors"]))
    vm = backend.get_vm(vm_name)
    if vm.state.lower() not in {"shut off", "shutoff"}:
        raise HyperGeryError("The VM must be shut off to attach a GPU.")
    # El resto de funciones del slot (audio HDMI, USB-C…) comparten grupo
    # IOMMU y deben pasarse junto a la GPU.
    companions = tuple(
        dev for dev in preflight["gpu"]["iommu_group_devices"] if dev != gpu_address
    )
    new_xml = attach_gpu_to_domain_xml(
        vm.xml, gpu_address, vendor_id=preflight["gpu"]["vendor_id"], extra_addresses=companions
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as handle:
        handle.write(new_xml)
        xml_path = handle.name
    try:
        backend.virsh(["define", xml_path])
    finally:
        Path(xml_path).unlink(missing_ok=True)
    if not domain_uses_uefi(new_xml):
        preflight["warnings"].append(
            f"{vm_name} boots with legacy BIOS; switch it to UEFI/OVMF for reliable passthrough."
        )
    return {
        "vm_name": vm_name,
        "gpu": preflight["gpu"],
        "warnings": preflight["warnings"],
        "live_migration_blocked": True,
    }


def domain_uses_uefi(domain_xml: str) -> bool:
    try:
        root = ET.fromstring(domain_xml)
    except ET.ParseError:
        return False
    loader = root.find("./os/loader")
    firmware = root.find("./os")
    return (loader is not None and "OVMF" in (loader.text or "")) or (
        firmware is not None and firmware.attrib.get("firmware") == "efi"
    )
