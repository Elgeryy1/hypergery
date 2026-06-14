"""B3: el Migration Wizard ofrece el modo B (live directa) en la UI.

Verifica que el wizard tiene el modo en vivo, que su preflight ligero exige VM
encendida + URI segura (rechaza qemu+tcp y VM apagada), y el helper puro que
deriva la URI del registro de un host del Hub.
"""

from __future__ import annotations

import os
import unittest

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.backend import VmSummary  # noqa: E402
from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog, live_uri_for_host  # noqa: E402


class LiveUriHelperTests(unittest.TestCase):
    def test_derives_qemu_ssh_from_address_and_user(self):
        self.assertEqual(
            live_uri_for_host({"address": "192.168.1.73", "ssh_user": "gery"}),
            "qemu+ssh://gery@192.168.1.73/system",
        )

    def test_strips_scheme_and_port_from_agent_url(self):
        self.assertEqual(
            live_uri_for_host({"agent_url": "http://portatil.local:8799"}),
            "qemu+ssh://portatil.local/system",
        )

    def test_empty_when_no_address(self):
        self.assertEqual(live_uri_for_host({}), "")

    def test_built_from_agent_reported_ssh_user_and_ip(self):
        # El agente reporta ssh_user/ssh_address; el URI sale solo, sin teclear.
        self.assertEqual(
            live_uri_for_host({"ssh_user": "gery", "ssh_address": "192.168.1.73", "hostname": "lenovo"}),
            "qemu+ssh://gery@192.168.1.73/system",
        )

    def test_falls_back_to_hostname_when_no_ip(self):
        self.assertEqual(
            live_uri_for_host({"ssh_user": "gery", "hostname": "lenovo", "host_id": "lenovo"}),
            "qemu+ssh://gery@lenovo/system",
        )


class _Vm:
    @staticmethod
    def running():
        return VmSummary(name="hgtest-live", state="running", lab_id="lab", ram_mib=512, vcpus=1, graphics="vnc")

    @staticmethod
    def off():
        return VmSummary(name="hgtest-off", state="shut off", lab_id="lab", ram_mib=512, vcpus=1, graphics="vnc")


class MigrationWizardLiveModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, vm):
        from unittest.mock import MagicMock

        backend = MagicMock()
        dialog = LiveMigrationDialog(backend, vm)
        # Selecciona el modo "live" en el combo.
        idx = dialog.transfer_mode.findData("live")
        self.assertGreaterEqual(idx, 0, "el wizard debe ofrecer el modo live")
        dialog.transfer_mode.setCurrentIndex(idx)
        return dialog

    def test_wizard_offers_live_mode(self):
        dialog = self._dialog(_Vm.running())
        try:
            self.assertGreaterEqual(dialog.transfer_mode.findData("live"), 0)
            self.assertTrue(dialog.live_uri.isEnabled())
        finally:
            dialog.deleteLater()

    def test_live_preflight_requires_running_vm(self):
        dialog = self._dialog(_Vm.off())
        try:
            dialog.live_uri.setText("qemu+ssh://gery@portatil/system")
            dialog._run_live_preflight(dialog.values())
            self.assertFalse(dialog.preflight_result["ok"])
            self.assertTrue(any("ENCENDIDA" in e for e in dialog.preflight_result["errors"]))
        finally:
            dialog.deleteLater()

    def test_live_preflight_rejects_insecure_uri(self):
        dialog = self._dialog(_Vm.running())
        try:
            dialog.live_uri.setText("qemu+tcp://portatil/system")
            dialog._run_live_preflight(dialog.values())
            self.assertFalse(dialog.preflight_result["ok"])
            self.assertTrue(any("qemu+tcp" in e or "seguras" in e for e in dialog.preflight_result["errors"]))
        finally:
            dialog.deleteLater()

    def test_live_preflight_passes_for_running_vm_with_secure_uri(self):
        dialog = self._dialog(_Vm.running())
        try:
            dialog.live_uri.setText("qemu+ssh://gery@portatil/system")
            dialog._run_live_preflight(dialog.values())
            self.assertTrue(dialog.preflight_result["ok"], dialog.preflight_result.get("errors"))
            self.assertTrue(dialog.preflight_result.get("live"))
            self.assertTrue(dialog.package_button.isEnabled())
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
