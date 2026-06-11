"""v1.5 blockers B1/B2: perfiles de VM, firmware Windows 11/Ubuntu, ISO.

Cubre que Windows 11 produce UEFI + Secure Boot (si hay OVMF) + vTPM 2.0, que
las dependencias que faltan se rechazan con error humano + comando sugerido
(sin bypass), y que el perfil Linux por defecto sigue siendo BIOS fiable.
"""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu import vm_profiles as vp
from hypergery_ubuntu.backend import HG_NS, HyperGeryBackend


class _XmlBackend(HyperGeryBackend):
    """Backend solo para generar XML: no toca virsh."""

    def virsh(self, args, *, timeout=120, check=True):
        raise AssertionError("domain_xml no debe llamar a virsh")


class ProfileResolutionTests(unittest.TestCase):
    def test_explicit_keys_and_os_type_fallback(self):
        self.assertEqual(vp.profile_for("windows11").key, "windows11")
        self.assertEqual(vp.profile_for("linux").key, "linux")
        self.assertEqual(vp.profile_for("Linux").key, "linux")
        self.assertEqual(vp.profile_for("Windows").key, "windows-legacy")
        self.assertEqual(vp.profile_for("Otro").key, "other")
        self.assertEqual(vp.profile_for("").key, vp.DEFAULT_PROFILE)

    def test_windows11_profile_requirements(self):
        p = vp.PROFILES["windows11"]
        self.assertEqual(p.firmware, "uefi-secure")
        self.assertTrue(p.tpm)
        self.assertEqual(p.machine, "q35")


class FirmwarePreflightTests(unittest.TestCase):
    def test_windows11_without_ovmf_or_swtpm_is_rejected_with_commands(self):
        with patch.object(vp, "resolve_ovmf", return_value={"code": "", "vars": "", "secure_boot": "no"}), \
             patch.object(vp, "swtpm_available", return_value=False):
            pf = vp.preflight_profile(vp.PROFILES["windows11"])
        self.assertFalse(pf.ok)
        joined = "; ".join(pf.errors)
        self.assertIn("UEFI", joined)
        self.assertIn("TPM 2.0", joined)
        self.assertIn("sudo apt install ovmf", pf.suggested_commands)
        self.assertIn("sudo apt install swtpm swtpm-tools", pf.suggested_commands)

    def test_windows11_with_deps_passes(self):
        with patch.object(vp, "resolve_ovmf", return_value={"code": "/x/CODE.fd", "vars": "/x/VARS.fd", "secure_boot": "yes"}), \
             patch.object(vp, "swtpm_available", return_value=True):
            pf = vp.preflight_profile(vp.PROFILES["windows11"])
        self.assertTrue(pf.ok, pf.errors)

    def test_secure_boot_unavailable_is_a_warning_not_an_error(self):
        with patch.object(vp, "resolve_ovmf", return_value={"code": "/x/CODE.fd", "vars": "/x/VARS.fd", "secure_boot": "no"}), \
             patch.object(vp, "swtpm_available", return_value=True):
            pf = vp.preflight_profile(vp.PROFILES["windows11"])
        self.assertTrue(pf.ok)
        self.assertTrue(any("Secure Boot" in w for w in pf.warnings))

    def test_linux_default_needs_no_firmware_deps(self):
        with patch.object(vp, "resolve_ovmf", return_value={"code": "", "vars": "", "secure_boot": "no"}), \
             patch.object(vp, "swtpm_available", return_value=False):
            pf = vp.preflight_profile(vp.PROFILES["linux"])
        self.assertTrue(pf.ok, pf.errors)


class WindowsXmlTests(unittest.TestCase):
    def _win11_xml(self) -> ET.Element:
        backend = _XmlBackend()
        with patch.object(vp, "resolve_ovmf", return_value={"code": "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "vars": "/usr/share/OVMF/OVMF_VARS_4M.ms.fd", "secure_boot": "yes"}):
            xml = backend.domain_xml(
                name="hgtest-win11",
                iso_path="/isos/win11.iso",
                os_type="Windows",
                ram_mib=4096,
                vcpus=2,
                disk_path="/tmp/hgtest-win11.qcow2",
                network_id="hg-net-default-lab",
                lab_id="default-lab",
                profile_key="windows11",
            )
        return ET.fromstring(xml)

    def test_win11_xml_has_uefi_loader_nvram_smm_and_tpm(self):
        root = self._win11_xml()
        self.assertEqual(root.find("./os/type").attrib["machine"], "q35")
        loader = root.find("./os/loader")
        self.assertIsNotNone(loader)
        self.assertEqual(loader.attrib.get("type"), "pflash")
        self.assertEqual(loader.attrib.get("secure"), "yes")
        self.assertIn("OVMF", loader.text)
        nvram = root.find("./os/nvram")
        self.assertIsNotNone(nvram)
        self.assertTrue(nvram.text.endswith(".nvram"))
        self.assertIn("template", nvram.attrib)
        self.assertIsNotNone(root.find("./features/smm"))
        tpm = root.find("./devices/tpm")
        self.assertIsNotNone(tpm)
        self.assertEqual(tpm.find("backend").attrib["version"], "2.0")
        self.assertEqual(root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}profile").text, "windows11")

    def test_linux_default_xml_has_no_uefi_no_tpm(self):
        backend = _XmlBackend()
        xml = backend.domain_xml(
            name="hgtest-ubuntu",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=2048,
            vcpus=2,
            disk_path="/tmp/hgtest-ubuntu.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
        )
        root = ET.fromstring(xml)
        self.assertIsNone(root.find("./os/loader"))
        self.assertIsNone(root.find("./devices/tpm"))
        # virtio para disco (perfil recomendado).
        self.assertEqual(root.find("./devices/disk[@device='disk']/target").attrib["bus"], "virtio")


class Accel3dTests(unittest.TestCase):
    """Aceleración 3D compartida (VirGL): virtio-gpu + accel3d + egl-headless."""

    def _xml(self, accel: bool) -> ET.Element:
        backend = _XmlBackend()
        xml = backend.domain_xml(
            name="hgtest-virgl",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=2048,
            vcpus=2,
            disk_path="/tmp/hgtest-virgl.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
            accel_3d=accel,
        )
        return ET.fromstring(xml)

    def test_accel_3d_emits_virtio_video_with_virgl(self):
        root = self._xml(True)
        model = root.find("./devices/video/model")
        self.assertEqual(model.attrib["type"], "virtio")
        self.assertEqual(model.find("acceleration").attrib["accel3d"], "yes")
        egl = [g for g in root.findall("./devices/graphics") if g.attrib.get("type") == "egl-headless"]
        self.assertEqual(len(egl), 1)
        self.assertEqual(
            root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}accel_3d").text, "true"
        )

    def test_default_keeps_qxl_and_no_egl(self):
        root = self._xml(False)
        self.assertEqual(root.find("./devices/video/model").attrib["type"], "qxl")
        egl = [g for g in root.findall("./devices/graphics") if g.attrib.get("type") == "egl-headless"]
        self.assertEqual(egl, [])

    def test_pick_render_node_prefers_mesa_driver(self):
        import tempfile
        from pathlib import Path

        from hypergery_ubuntu.backend import pick_render_node

        with tempfile.TemporaryDirectory() as tmp:
            by_path = Path(tmp) / "by-path"
            by_path.mkdir()
            sysfs = Path(tmp) / "devices"
            for address, driver in (("0000:01:00.0", "nvidia"), ("0000:11:00.0", "amdgpu")):
                node = by_path / f"pci-{address}-render"
                node.write_text("")
                driver_dir = Path(tmp) / "drivers" / driver
                driver_dir.mkdir(parents=True, exist_ok=True)
                device = sysfs / address
                device.mkdir(parents=True)
                (device / "driver").symlink_to(driver_dir)
            picked = pick_render_node(by_path, sysfs)
            # La NVIDIA va primero alfabéticamente, pero Mesa (amdgpu) gana:
            # el EGL headless propietario no funciona para libvirt-qemu.
            self.assertTrue(picked.endswith("pci-0000:11:00.0-render"))


class MigratableCpuTests(unittest.TestCase):
    def _xml(self, migratable: bool) -> ET.Element:
        backend = _XmlBackend()
        xml = backend.domain_xml(
            name="hgtest-mig",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=2048,
            vcpus=2,
            disk_path="/tmp/hgtest-mig.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
            migratable_cpu=migratable,
        )
        return ET.fromstring(xml)

    def test_default_uses_host_passthrough(self):
        cpu = self._xml(False).find("./cpu")
        self.assertEqual(cpu.attrib.get("mode"), "host-passthrough")

    def test_migratable_uses_portable_baseline_model(self):
        root = self._xml(True)
        cpu = root.find("./cpu")
        self.assertEqual(cpu.attrib.get("mode"), "custom")
        self.assertEqual(cpu.find("model").text, "qemu64")
        self.assertEqual(
            root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}migratable_cpu").text, "true"
        )


class WindowsDeviceBusTests(unittest.TestCase):
    def _win11_xml(self) -> ET.Element:
        backend = _XmlBackend()
        with patch.object(vp, "resolve_ovmf", return_value={"code": "/x/CODE.fd", "vars": "/x/VARS.fd", "secure_boot": "no"}):
            xml = backend.domain_xml(
                name="hgtest-win",
                iso_path="/isos/win11.iso",
                os_type="Windows",
                ram_mib=4096,
                vcpus=2,
                disk_path="/tmp/hgtest-win.qcow2",
                network_id="hg-net-default-lab",
                lab_id="default-lab",
                profile_key="windows11",
            )
        return ET.fromstring(xml)

    def test_windows_uses_sata_disk_and_e1000_net_no_collision(self):
        root = self._win11_xml()
        disk = root.find("./devices/disk[@device='disk']/target")
        self.assertEqual(disk.attrib["bus"], "sata")
        self.assertEqual(disk.attrib["dev"], "sda")
        cdrom = root.find("./devices/disk[@device='cdrom']/target")
        self.assertEqual(cdrom.attrib["dev"], "sdb")  # sin colisión con el disco
        self.assertEqual(root.find("./devices/interface/model").attrib["type"], "e1000")


class IsoValidationTests(unittest.TestCase):
    def test_missing_iso_fails(self):
        result = vp.validate_iso("/nope/does-not-exist.iso")
        self.assertFalse(result["ok"])
        self.assertTrue(any("no existe" in e for e in result["errors"]))

    def test_tiny_iso_warns_but_can_pass(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".iso", delete=False) as handle:
            handle.write(b"\x00" * 1024)
            path = handle.name
        try:
            result = vp.validate_iso(path)
            self.assertTrue(result["ok"])  # no es error duro, solo aviso
            self.assertTrue(result["warnings"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_real_iso9660_signature_has_no_warning_about_magic(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".iso", delete=False) as handle:
            handle.write(b"\x00" * 0x8001)
            handle.write(b"CD001")
            handle.write(b"\x00" * (20 * 1024 * 1024))
            path = handle.name
        try:
            result = vp.validate_iso(path)
            self.assertTrue(result["ok"])
            self.assertFalse(any("CD001" in w for w in result["warnings"]))
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
