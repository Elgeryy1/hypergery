"""Suite needsRealLibvirt (HG-BUG-0011): smoke tests contra libvirt REAL.

Reglas de seguridad:
- Solo se crean/tocan VMs con prefijo ``hgtest-`` y labs ``hgtest-lab-*``.
- Los datos viven en un HYPERGERY_DATA_HOME temporal, nunca en el real.
- Ninguna operación destructiva sobre dominios que no haya creado la suite.

Ejecutar: ``HYPERGERY_REAL_LIBVIRT=1 pytest -m needsRealLibvirt -q``
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import unittest
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.needsRealLibvirt

LAB_ID = "hgtest-lab-real"


def _new_name(suffix: str = "") -> str:
    return f"hgtest-{uuid.uuid4().hex[:10]}{suffix}"


class RealLibvirtTestCase(unittest.TestCase):
    """Backend real + limpieza garantizada de todo lo hgtest-*."""

    @classmethod
    def setUpClass(cls):
        from hypergery_ubuntu.backend import HyperGeryBackend

        cls._data_root = Path("/var/tmp") / f"hypergery-realtest-{uuid.uuid4().hex[:8]}"
        cls._data_root.mkdir(parents=True)
        # qemu:///system: el usuario qemu necesita atravesar los directorios.
        cls._data_root.chmod(0o755)
        cls._old_env = os.environ.get("HYPERGERY_DATA_HOME")
        os.environ["HYPERGERY_DATA_HOME"] = str(cls._data_root)
        cls.backend = HyperGeryBackend()
        for directory in (cls.backend.data_dir, cls.backend.vms_dir, cls.backend.labs_dir):
            directory.chmod(0o755)
        cls._created: list[str] = []

    @classmethod
    def tearDownClass(cls):
        for name in list(cls._created):
            cls._destroy_and_delete(name)
        try:
            cls.backend.recycle_hypergery_network(cls.backend.network_name(LAB_ID, "nat"), "test cleanup")
        except Exception:
            pass
        if cls._old_env is None:
            os.environ.pop("HYPERGERY_DATA_HOME", None)
        else:
            os.environ["HYPERGERY_DATA_HOME"] = cls._old_env
        shutil.rmtree(cls._data_root, ignore_errors=True)

    @classmethod
    def _destroy_and_delete(cls, name: str) -> None:
        assert name.startswith("hgtest-"), f"refusing to touch non-test VM: {name}"
        try:
            if cls.backend.virsh(["dominfo", name], check=False).returncode != 0:
                return
            cls.backend.virsh(["destroy", name], check=False)
            cls.backend.delete_vm(name, delete_disks=True)
        except Exception:
            # Último recurso: undefine directo, siempre solo hgtest-*.
            cls.backend.virsh(["undefine", name, "--nvram"], check=False)
        finally:
            if name in cls._created:
                cls._created.remove(name)

    def _create_vm(self, name: str | None = None) -> str:
        name = name or _new_name()
        iso = self.backend.data_dir / "isos" / "hgtest-dummy.iso"
        iso.parent.mkdir(parents=True, exist_ok=True)
        if not iso.is_file():
            iso.write_bytes(b"HGTEST-NOT-BOOTABLE" * 64)
            # Solo al crearlo: tras arrancar una VM, libvirt puede haber
            # cambiado el propietario del ISO (dynamic ownership) y un chmod
            # posterior fallaría con EPERM.
            iso.chmod(0o644)
        self._created.append(name)
        self.backend.create_vm(
            name=name,
            iso_path=str(iso),
            os_type="Linux",
            ram_mib=512,
            vcpus=1,
            disk_gb=1,
            disk_dir=None,
            network_mode="nat",
            display_mode="vnc",
            lab_id=LAB_ID,
        )
        return name

    def _wait_state(self, name: str, states: set[str], timeout: float = 30.0) -> str:
        deadline = time.monotonic() + timeout
        state = ""
        while time.monotonic() < deadline:
            state = self.backend.get_vm(name).state.lower()
            if state in states:
                return state
            time.sleep(1.0)
        return state


class RealVmLifecycleTests(RealLibvirtTestCase):
    def test_1_create_trivial_vm_dominfo(self):
        name = self._create_vm()
        info = self.backend.virsh(["dominfo", name])
        self.assertIn(name, info.stdout)
        vm = self.backend.get_vm(name)
        self.assertEqual(vm.lab_id, LAB_ID)
        self.assertIn(vm.state.lower(), {"shut off", "shutoff"})
        self._destroy_and_delete(name)

    def test_2_export_package_has_valid_checksums(self):
        from hypergery_ubuntu.migration import export_vm_package

        name = self._create_vm()
        export = export_vm_package(self.backend, name, self.backend.data_dir / "nas", include_iso=False)
        package_dir = Path(export["package_dir"])
        manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
        copied = [asset for asset in manifest.get("assets", []) if asset.get("relative_path")]
        self.assertTrue(copied, manifest)
        for asset in copied:
            payload = (package_dir / asset["relative_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), asset["sha256"])
        self._destroy_and_delete(name)

    def test_3_import_with_new_name_regenerates_uuid_and_mac(self):
        from hypergery_ubuntu.migration import export_vm_package, import_vm_package

        source = self._create_vm()
        target = _new_name("-b")
        export = export_vm_package(
            self.backend, source, self.backend.data_dir / "nas", target_vm_name=target, include_iso=False
        )
        self._created.append(target)
        import_vm_package(self.backend, export["package_dir"], target_vm_name=target)

        uuid_a = self.backend.virsh(["domuuid", source]).stdout.strip()
        uuid_b = self.backend.virsh(["domuuid", target]).stdout.strip()
        self.assertNotEqual(uuid_a, uuid_b)
        xml_a = self.backend.virsh(["dumpxml", source]).stdout
        xml_b = self.backend.virsh(["dumpxml", target]).stdout
        import re

        macs_a = set(re.findall(r"mac address='([^']+)'", xml_a))
        macs_b = set(re.findall(r"mac address='([^']+)'", xml_b))
        self.assertTrue(macs_a and macs_b)
        self.assertFalse(macs_a & macs_b, (macs_a, macs_b))
        self._destroy_and_delete(target)
        self._destroy_and_delete(source)

    def test_4_start_acpi_force_off_states(self):
        name = self._create_vm()
        self.backend.start_vm(name)
        self.assertEqual(self._wait_state(name, {"running"}), "running")
        # ACPI: la VM trivial no tiene SO que atienda el evento; la petición
        # debe aceptarse sin error y la VM seguir definida.
        self.backend.shutdown_vm(name)
        self.assertEqual(self.backend.virsh(["dominfo", name]).returncode, 0)
        self.backend.force_off_vm(name)
        self.assertIn(self._wait_state(name, {"shut off", "shutoff"}), {"shut off", "shutoff"})
        self._destroy_and_delete(name)

    def test_5_corrupted_package_import_fails_and_source_stays_intact(self):
        from hypergery_ubuntu.backend import HyperGeryError
        from hypergery_ubuntu.migration import export_vm_package, import_vm_package

        source = self._create_vm()
        target = _new_name("-c")
        export = export_vm_package(
            self.backend, source, self.backend.data_dir / "nas", target_vm_name=target, include_iso=False
        )
        package_dir = Path(export["package_dir"])
        manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
        disk_rel = next(
            asset["relative_path"]
            for asset in manifest["assets"]
            if asset["type"] == "disk" and asset.get("relative_path")
        )
        with (package_dir / disk_rel).open("r+b") as handle:
            handle.seek(0)
            handle.write(b"CORRUPTED!")
        with self.assertRaises(HyperGeryError):
            import_vm_package(self.backend, package_dir, target_vm_name=target)
        # Rollback: el destino no existe y el origen sigue definido e intacto.
        self.assertNotEqual(self.backend.virsh(["dominfo", target], check=False).returncode, 0)
        self.assertEqual(self.backend.virsh(["dominfo", source]).returncode, 0)
        self.assertFalse((self.backend.vms_dir / target).exists())
        self._destroy_and_delete(source)

    def test_7_backup_verifier_restores_boots_and_cleans_up(self):
        from hypergery_ubuntu.migration import export_vm_package
        from hypergery_ubuntu.v1.backup_verifier import verify_backup

        name = self._create_vm()
        export = export_vm_package(self.backend, name, self.backend.data_dir / "nas", include_iso=False)
        result = verify_backup(self.backend, export["package_dir"], boot_timeout_seconds=60)
        self.assertTrue(result["checksums_ok"], result)
        self.assertTrue(result["booted"], result)
        self.assertTrue(result["ok"], result)
        # La VM temporal de verificación ya no existe.
        self.assertNotEqual(
            self.backend.virsh(["dominfo", result["verified_vm"]], check=False).returncode, 0
        )
        self._destroy_and_delete(name)

    def test_8_gpu_detection_and_desktop_gpu_hard_stop(self):
        """§5.8 (solo lectura): detección IOMMU/GPU real y garantía de que el
        preflight NUNCA permite pasar la GPU del escritorio sin segunda GPU.
        No se hace bind/unbind real (este host solo tiene la iGPU)."""
        from hypergery_ubuntu.v1.gpu_passthrough import (
            iommu_status,
            list_pci_gpus,
            preflight_gpu_passthrough,
        )

        status = iommu_status()
        gpus = list_pci_gpus()
        self.assertTrue(gpus, "el host debe tener al menos una GPU detectable")
        boot_gpu = next((gpu for gpu in gpus if gpu["boot_vga"]), None)
        if boot_gpu is None:
            self.skipTest("no boot_vga GPU on this host")
        result = preflight_gpu_passthrough(boot_gpu["address"])
        if len(gpus) == 1:
            self.assertFalse(result["ok"], result)
            self.assertTrue(
                any("kill the host display" in error for error in result["errors"])
                or any("IOMMU" in error for error in result["errors"]),
                result["errors"],
            )
        self.assertIn("enabled", status)

    def test_6_delete_disks_removes_only_the_test_vm(self):
        name = self._create_vm()
        disk_path = Path(self.backend.get_vm(name).disk_path)
        self.assertTrue(disk_path.is_file())
        others_before = {
            line.strip()
            for line in self.backend.virsh(["list", "--all", "--name"]).stdout.splitlines()
            if line.strip() and not line.strip().startswith("hgtest-")
        }
        self.backend.delete_vm(name, delete_disks=True)
        self._created.remove(name)
        self.assertNotEqual(self.backend.virsh(["dominfo", name], check=False).returncode, 0)
        self.assertFalse(disk_path.exists())
        others_after = {
            line.strip()
            for line in self.backend.virsh(["list", "--all", "--name"]).stdout.splitlines()
            if line.strip() and not line.strip().startswith("hgtest-")
        }
        self.assertEqual(others_before, others_after)


if __name__ == "__main__":
    unittest.main()
