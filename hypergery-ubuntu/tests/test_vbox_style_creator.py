"""Diálogo de creación de VM estilo VirtualBox (secciones plegables + sliders).

Verifica que produce el mismo contrato `values()` que el wizard clásico, que
el perfil/firmware se deriva correctamente (Windows 11 → UEFI+SecureBoot+TPM,
Linux con/sin EFI), y que las secciones son plegables.
"""

from __future__ import annotations

import os
import unittest

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.ui_qt.dialogs import VBoxStyleVMCreator  # noqa: E402


class VBoxStyleCreatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        d = VBoxStyleVMCreator()
        d.name_edit.setText("hgtest-vm")
        d.iso_edit.setText("/tmp/x.iso")
        return d

    def test_values_contract_matches_create_vm(self):
        d = self._dialog()
        v = d.values()
        for key in (
            "name", "iso_path", "os_type", "profile", "ram_mib", "vcpus",
            "disk_gb", "disk_dir", "network_mode", "display_mode", "lab_id",
            "migratable_cpu",
        ):
            self.assertIn(key, v)

    def test_windows11_profile_with_firmware_and_tpm(self):
        d = self._dialog()
        d.os_combo.setCurrentIndex(d.os_combo.findData("windows11"))
        v = d.values()
        self.assertEqual(v["profile"], "windows11")
        self.assertEqual(v["os_type"], "Windows")
        self.assertIn("TPM 2.0", d.secure_tpm_info.text())
        self.assertIn("Secure Boot", d.secure_tpm_info.text())
        # EFI bloqueado a ON para Windows.
        self.assertTrue(d.use_efi.isChecked())
        self.assertFalse(d.use_efi.isEnabled())

    def test_linux_efi_toggle_switches_profile(self):
        d = self._dialog()
        d.os_combo.setCurrentIndex(d.os_combo.findData("linux"))
        d.use_efi.setChecked(False)
        self.assertEqual(d.values()["profile"], "linux")
        d.use_efi.setChecked(True)
        self.assertEqual(d.values()["profile"], "linux-uefi")

    def test_recommended_values_bumped_for_windows11(self):
        d = self._dialog()
        d.os_combo.setCurrentIndex(d.os_combo.findData("windows11"))
        self.assertGreaterEqual(d.values()["ram_mib"], 4096)
        self.assertGreaterEqual(d.values()["disk_gb"], 64)

    def test_migratable_cpu_option_present(self):
        d = self._dialog()
        d.migratable_cpu.setChecked(True)
        self.assertTrue(d.values()["migratable_cpu"])

    def test_accel_3d_in_values_and_excludes_migratable(self):
        d = self._dialog()
        self.assertFalse(d.values()["accel_3d"])
        d.migratable_cpu.setChecked(True)
        d.accel_3d.setChecked(True)
        # Acelerada O migrable en vivo: nunca ambas.
        self.assertTrue(d.values()["accel_3d"])
        self.assertFalse(d.values()["migratable_cpu"])
        self.assertFalse(d.migratable_cpu.isEnabled())
        self.assertIn("no puede migrarse", d.accel_info.text())
        d.accel_3d.setChecked(False)
        self.assertTrue(d.migratable_cpu.isEnabled())
        self.assertEqual(d.accel_info.text(), "")

    def test_sections_are_collapsible(self):
        d = self._dialog()
        # En offscreen isVisible() siempre es False; isHidden() refleja el
        # estado explícito de plegado/desplegado.
        section = d.sec_hw
        section.toggle.setChecked(False)
        self.assertTrue(section.body.isHidden())
        section.toggle.setChecked(True)
        self.assertFalse(section.body.isHidden())

    def test_accept_requires_name_and_iso(self):
        d = VBoxStyleVMCreator()
        d._accept_if_valid()
        self.assertIn("nombre", d.error_label.text().lower())
        d.name_edit.setText("hgtest-vm")
        d._accept_if_valid()
        self.assertIn("ISO", d.error_label.text())


if __name__ == "__main__":
    unittest.main()
