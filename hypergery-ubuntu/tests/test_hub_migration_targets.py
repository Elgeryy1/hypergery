"""B5: los destinos de la migración mediada por el Hub salen del registro del
Hub, sin exigir que origen y destino «se vean» entre sí.

- Dos hosts online en el Hub → el otro es candidato válido aunque no haya SSH
  directo (el Hub coordina).
- El host de origen se excluye como destino (por host_id o por hostname).
- Un host online sin KVM/libvirt queda no-listo con una razón concreta.
- El modo Hub no llama a ningún preflight qemu+ssh; el modo live sí valida URI.
"""

from __future__ import annotations

import os
import unittest

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.backend import VmSummary  # noqa: E402
from hypergery_ubuntu.ui_qt.dialogs import (  # noqa: E402
    LiveMigrationDialog,
    hub_target_candidates,
)


PC = {"host_id": "gerard-MS-7E26", "hostname": "gerard-MS-7E26", "status": "online", "kvm_ok": True, "libvirt_ok": True, "address": "192.168.1.44"}
LAPTOP = {"host_id": "gery-Lenovo", "hostname": "gery-Lenovo", "status": "online", "kvm_ok": True, "libvirt_ok": True, "address": "192.168.1.73"}


class HubTargetCandidateTests(unittest.TestCase):
    def test_both_online_other_host_is_a_valid_target_without_direct_ssh(self):
        cands = hub_target_candidates([PC, LAPTOP], source_host_id="gerard-MS-7E26")
        ids = [c["host_id"] for c in cands]
        self.assertEqual(ids, ["gery-Lenovo"])  # el origen queda excluido
        self.assertTrue(cands[0]["ready"])
        self.assertEqual(cands[0]["reason"], "")

    def test_source_excluded_by_hostname_when_host_id_unknown(self):
        cands = hub_target_candidates([PC, LAPTOP], source_host_id="", source_hostname="gerard-MS-7E26")
        self.assertEqual([c["host_id"] for c in cands], ["gery-Lenovo"])

    def test_no_duplicate_host_ids(self):
        cands = hub_target_candidates([LAPTOP, dict(LAPTOP), PC], source_host_id="gerard-MS-7E26")
        self.assertEqual(len([c for c in cands if c["host_id"] == "gery-Lenovo"]), 1)

    def test_online_without_kvm_is_not_ready_with_reason(self):
        no_kvm = {**LAPTOP, "kvm_ok": False}
        cands = hub_target_candidates([PC, no_kvm], source_host_id="gerard-MS-7E26")
        self.assertFalse(cands[0]["ready"])
        self.assertIn("KVM", cands[0]["reason"])

    def test_offline_target_is_not_ready_with_reason(self):
        offline = {**LAPTOP, "status": "offline"}
        cands = hub_target_candidates([PC, offline], source_host_id="gerard-MS-7E26")
        self.assertFalse(cands[0]["ready"])
        self.assertIn("sin conexión", cands[0]["reason"])

    def test_only_source_registered_yields_no_candidates(self):
        self.assertEqual(hub_target_candidates([PC], source_host_id="gerard-MS-7E26"), [])


class _Vm:
    @staticmethod
    def off():
        return VmSummary(name="hgtest-hub", state="shut off", lab_id="lab", ram_mib=512, vcpus=1, graphics="vnc")

    @staticmethod
    def running():
        return VmSummary(name="hgtest-live", state="running", lab_id="lab", ram_mib=512, vcpus=1, graphics="vnc")


class DialogTargetGatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, vm):
        from unittest.mock import MagicMock

        dialog = LiveMigrationDialog(MagicMock(), vm)
        dialog.source_host_id.setText("gerard-MS-7E26")
        # Inyecta hosts del Hub sin red: simula refresh_hosts.
        dialog.hosts = [PC, LAPTOP]
        dialog.target_host.clear()
        for cand in hub_target_candidates([PC, LAPTOP], "gerard-MS-7E26"):
            dialog.target_host.addItem(cand["host_id"], cand["host_id"])
        return dialog

    def test_hub_mode_target_ready_for_online_other_host(self):
        dialog = self._dialog(_Vm.off())
        try:
            idx = dialog.transfer_mode.findData("hub")
            dialog.transfer_mode.setCurrentIndex(idx)
            # destino = el portátil (único candidato)
            self.assertEqual(dialog.target_host.currentData(), "gery-Lenovo")
            self.assertTrue(dialog._target_ready())
        finally:
            dialog.deleteLater()

    def test_hub_preflight_does_not_call_qemu_ssh(self):
        dialog = self._dialog(_Vm.off())
        try:
            idx = dialog.transfer_mode.findData("hub")
            dialog.transfer_mode.setCurrentIndex(idx)
            import hypergery_ubuntu.v1.live_migration as livemod
            from unittest.mock import patch

            dialog.target_name.setText("hgtest-hub-moved")
            with patch.object(livemod, "LiveMigrator") as fake_migrator, \
                 patch("hypergery_ubuntu.migration.migration_preflight", return_value={"ok": True, "errors": [], "warnings": [], "assets": []}):
                dialog.run_preflight()
            fake_migrator.assert_not_called()  # el modo Hub NO usa migración directa
        finally:
            dialog.deleteLater()

    def test_live_mode_validates_uri_and_running_state(self):
        dialog = self._dialog(_Vm.running())
        try:
            idx = dialog.transfer_mode.findData("live")
            dialog.transfer_mode.setCurrentIndex(idx)
            dialog.live_uri.setText("qemu+ssh://gery@portatil/system")
            dialog.run_preflight()
            self.assertTrue(dialog.preflight_result["ok"])
            self.assertTrue(dialog.preflight_result.get("live"))
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
