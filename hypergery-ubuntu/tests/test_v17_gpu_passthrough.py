"""v1.7 GPU passthrough: detección, preflight (PARADA DURA), VFIO bind con
rollback y <hostdev> en el domain XML."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypergery_ubuntu.v1.errors import HyperGeryError
from hypergery_ubuntu.v1.gpu_passthrough import (
    VfioBinder,
    attach_gpu_to_domain_xml,
    domain_uses_uefi,
    hostdev_xml,
    iommu_status,
    list_pci_gpus,
    preflight_gpu_passthrough,
    propose_host_changes,
)

IGPU = "0000:00:02.0"
DGPU = "0000:01:00.0"
DGPU_AUDIO = "0000:01:00.1"


class FakeSysfs:
    """Árbol /sys de mentira con GPUs, drivers y grupos IOMMU."""

    def __init__(self, root: Path):
        self.root = root
        (root / "bus/pci/devices").mkdir(parents=True)
        (root / "bus/pci/drivers").mkdir(parents=True)
        (root / "kernel/iommu_groups").mkdir(parents=True)
        # drivers_probe: al escribir una dirección, simula el probe (vfio si
        # hay override, si no el driver "natural").
        (root / "bus/pci/drivers_probe").write_text("")
        self.natural_driver: dict[str, str] = {}

    def add_device(self, address: str, *, pci_class: str, vendor: str, driver: str = "",
                   boot_vga: bool = False, group: str = ""):
        device = self.root / "bus/pci/devices" / address
        device.mkdir(parents=True)
        (device / "class").write_text(pci_class + "\n")
        (device / "vendor").write_text(vendor + "\n")
        (device / "device").write_text("0x1234\n")
        (device / "driver_override").write_text("")
        if boot_vga:
            (device / "boot_vga").write_text("1\n")
        if driver:
            self.bind(address, driver)
            self.natural_driver[address] = driver
        if group:
            group_dir = self.root / "kernel/iommu_groups" / group / "devices"
            group_dir.mkdir(parents=True, exist_ok=True)
            (group_dir / address).symlink_to(device)
            (device / "iommu_group").symlink_to(self.root / "kernel/iommu_groups" / group)

    def bind(self, address: str, driver: str):
        driver_dir = self.root / "bus/pci/drivers" / driver
        driver_dir.mkdir(parents=True, exist_ok=True)
        device = self.root / "bus/pci/devices" / address
        link = device / "driver"
        if link.is_symlink():
            link.unlink()
        link.symlink_to(driver_dir)
        (driver_dir / "bind").write_text("")
        (device / "driver" / "unbind").parent.mkdir(exist_ok=True)

    def unbind(self, address: str):
        link = self.root / "bus/pci/devices" / address / "driver"
        if link.is_symlink():
            link.unlink()


class _ProbeAwareBinder(VfioBinder):
    """Binder que simula el comportamiento del kernel sobre el FakeSysfs."""

    def __init__(self, fake: FakeSysfs, *, probe_fails: bool = False):
        super().__init__(fake.root)
        self.fake = fake
        self.probe_fails = probe_fails

    def _write(self, path: Path, value: str) -> None:
        device_dir = None
        if path.name == "unbind" and path.parent.name == "driver":
            self.fake.unbind(value)
            return
        if path.name == "drivers_probe":
            if self.probe_fails:
                return  # el kernel "no consigue" bindear nada
            override = (self.fake.root / "bus/pci/devices" / value / "driver_override").read_text().strip()
            self.fake.bind(value, override or self.fake.natural_driver.get(value, "unknown"))
            return
        if path.name == "bind" and path.parent.parent.name == "drivers":
            self.fake.bind(value, path.parent.name)
            return
        super()._write(path, value)


def _make_host(tmp: Path, *, two_gpus: bool = True, dirty_group: bool = False) -> FakeSysfs:
    fake = FakeSysfs(tmp / "sys")
    fake.add_device(IGPU, pci_class="0x030000", vendor="0x8086", driver="i915", boot_vga=True, group="0")
    if two_gpus:
        group = "12"
        fake.add_device(DGPU, pci_class="0x030000", vendor="0x10de", driver="nouveau", group=group)
        fake.add_device(DGPU_AUDIO, pci_class="0x040300", vendor="0x10de", driver="snd_hda_intel", group=group)
        if dirty_group:
            fake.add_device("0000:01:01.0", pci_class="0x020000", vendor="0x8086", driver="e1000e", group=group)
    cmdline = tmp / "cmdline"
    cmdline.write_text("BOOT_IMAGE=/vmlinuz intel_iommu=on iommu=pt\n")
    modules = tmp / "modules"
    modules.write_text("vfio_pci 16384 0 - Live 0x0\n")
    return fake


class DetectionTests(unittest.TestCase):
    def test_lists_gpus_with_groups_and_drivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            gpus = list_pci_gpus(fake.root)
            by_address = {gpu["address"]: gpu for gpu in gpus}
            self.assertEqual(set(by_address), {IGPU, DGPU})
            self.assertTrue(by_address[IGPU]["boot_vga"])
            self.assertEqual(by_address[IGPU]["driver"], "i915")
            self.assertEqual(by_address[DGPU]["iommu_group"], "12")
            self.assertEqual(by_address[DGPU]["iommu_group_devices"], [DGPU, DGPU_AUDIO])

    def test_iommu_status_reads_groups_and_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            status = iommu_status(fake.root, Path(tmp) / "cmdline")
            self.assertTrue(status["enabled"])
            self.assertIn("intel_iommu=on", status["kernel_flags"])

    def test_propose_host_changes_never_applies(self):
        proposal = propose_host_changes("GenuineIntel")
        self.assertFalse(proposal["applied"])
        self.assertTrue(proposal["requires_reboot"])
        self.assertIn("intel_iommu=on", proposal["grub"]["change"])
        self.assertIn("amd_iommu=on", propose_host_changes("AuthenticAMD")["grub"]["change"])


class PreflightTests(unittest.TestCase):
    def _preflight(self, tmp: Path, fake: FakeSysfs, address: str):
        return preflight_gpu_passthrough(
            address,
            sysfs_root=fake.root,
            cmdline_path=tmp / "cmdline",
            modules_path=tmp / "modules",
            lib_modules_root=tmp / "no-such-lib-modules",
        )

    def test_secondary_gpu_passes_with_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            result = self._preflight(Path(tmp), fake, DGPU)
            self.assertTrue(result["ok"], result["errors"])
            self.assertTrue(any("live-migrated" in w for w in result["warnings"]))
            self.assertTrue(any("NVIDIA" in w for w in result["warnings"]))

    def test_desktop_gpu_without_second_gpu_is_hard_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp), two_gpus=False)
            result = self._preflight(Path(tmp), fake, IGPU)
            self.assertFalse(result["ok"])
            self.assertTrue(any("kill the host display" in e for e in result["errors"]))

    def test_dirty_iommu_group_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp), dirty_group=True)
            result = self._preflight(Path(tmp), fake, DGPU)
            self.assertFalse(result["ok"])
            self.assertTrue(any("not clean" in e for e in result["errors"]))

    def test_missing_iommu_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            import shutil as sh

            sh.rmtree(fake.root / "kernel/iommu_groups")
            result = self._preflight(Path(tmp), fake, DGPU)
            self.assertFalse(result["ok"])
            self.assertTrue(any("IOMMU is not active" in e for e in result["errors"]))

    def test_non_gpu_address_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            result = self._preflight(Path(tmp), fake, "0000:99:00.0")
            self.assertFalse(result["ok"])

    def test_invalid_address_raises(self):
        with self.assertRaises(HyperGeryError):
            preflight_gpu_passthrough("not-a-pci-address")


class VfioBindTests(unittest.TestCase):
    def test_bind_requires_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            with self.assertRaises(HyperGeryError):
                _ProbeAwareBinder(fake).bind_to_vfio(DGPU)

    def test_bind_switches_driver_to_vfio(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            binder = _ProbeAwareBinder(fake)
            result = binder.bind_to_vfio(DGPU, confirm=True)
            self.assertTrue(result["changed"])
            self.assertEqual(result["previous_driver"], "nouveau")
            self.assertEqual(binder.current_driver(DGPU), "vfio-pci")

    def test_failed_probe_rolls_back_to_original_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            binder = _ProbeAwareBinder(fake, probe_fails=True)
            with self.assertRaises(HyperGeryError):
                binder.bind_to_vfio(DGPU, confirm=True)
            self.assertEqual(binder.current_driver(DGPU), "nouveau", "rollback al driver original")
            override = (fake.root / "bus/pci/devices" / DGPU / "driver_override").read_text().strip()
            self.assertEqual(override, "")

    def test_unbind_returns_device_to_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _make_host(Path(tmp))
            binder = _ProbeAwareBinder(fake)
            binder.bind_to_vfio(DGPU, confirm=True)
            result = binder.unbind_from_vfio(DGPU, "nouveau")
            self.assertTrue(result["changed"])
            self.assertEqual(binder.current_driver(DGPU), "nouveau")


DOMAIN_XML = """<domain type='kvm'>
  <name>juegos</name>
  <os firmware='efi'><type arch='x86_64'>hvm</type></os>
  <devices><disk type='file' device='disk'/></devices>
</domain>"""


class DomainXmlTests(unittest.TestCase):
    def test_hostdev_xml_encodes_the_address(self):
        xml = hostdev_xml(DGPU)
        element = ET.fromstring(xml)
        address = element.find("./source/address")
        self.assertEqual(address.attrib["bus"], "0x01")
        self.assertEqual(address.attrib["slot"], "0x00")
        self.assertEqual(address.attrib["function"], "0x0")
        self.assertEqual(element.attrib["managed"], "yes")

    def test_attach_adds_hostdev(self):
        new_xml = attach_gpu_to_domain_xml(DOMAIN_XML, DGPU)
        root = ET.fromstring(new_xml)
        self.assertEqual(len(root.findall("./devices/hostdev")), 1)
        self.assertIsNone(root.find("./features/kvm/hidden"))

    def test_nvidia_gpu_hides_the_hypervisor(self):
        new_xml = attach_gpu_to_domain_xml(DOMAIN_XML, DGPU, vendor_id="0x10de")
        root = ET.fromstring(new_xml)
        self.assertEqual(root.find("./features/kvm/hidden").attrib["state"], "on")
        vendor = root.find("./features/hyperv/vendor_id")
        self.assertEqual(vendor.attrib["state"], "on")

    def test_uefi_detection(self):
        self.assertTrue(domain_uses_uefi(DOMAIN_XML))
        self.assertFalse(domain_uses_uefi("<domain><os/></domain>"))


if __name__ == "__main__":
    unittest.main()
