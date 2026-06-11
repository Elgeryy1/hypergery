"""Diálogo de GPU passthrough: solo GPUs aptas elegibles, VM apagada
obligatoria, attach/detach con confirmación y filas testables sin Qt."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.backend import VmSummary  # noqa: E402
from hypergery_ubuntu.ui_qt.dialogs import GpuPassthroughDialog, gpu_choice_rows  # noqa: E402

DGPU = {
    "address": "0000:01:00.0",
    "vendor_id": "0x10de",
    "device_id": "0x1f07",
    "driver": "nvidia",
    "boot_vga": True,
    "iommu_group": "13",
    "iommu_group_devices": ["0000:01:00.0", "0000:01:00.1"],
    "connected_displays": [],
}
IGPU = {
    "address": "0000:11:00.0",
    "vendor_id": "0x1002",
    "device_id": "0x164e",
    "driver": "amdgpu",
    "boot_vga": False,
    "iommu_group": "28",
    "iommu_group_devices": ["0000:11:00.0"],
    "connected_displays": ["HDMI-A-1"],
}

PRE_OK = {"ok": True, "errors": [], "warnings": ["aviso de prueba"]}
PRE_BAD = {"ok": False, "errors": ["pantalla única conectada"], "warnings": []}


class _FakeVm:
    def __init__(self, xml: str) -> None:
        self.state = "shut off"
        self.xml = xml


class _FakeBackend:
    def __init__(self, xml: str = "<domain><devices/></domain>") -> None:
        self._xml = xml

    def get_vm(self, name):
        return _FakeVm(self._xml)


def _preflights(mapping):
    return lambda address: mapping[address]


class GpuChoiceRowTests(unittest.TestCase):
    def test_rows_carry_eligibility_and_reason(self):
        rows = gpu_choice_rows([DGPU, IGPU], {DGPU["address"]: PRE_OK, IGPU["address"]: PRE_BAD})
        by_address = {row["address"]: row for row in rows}
        self.assertTrue(by_address[DGPU["address"]]["ok"])
        self.assertEqual(by_address[DGPU["address"]]["group_size"], 2)
        self.assertFalse(by_address[IGPU["address"]]["ok"])
        self.assertIn("pantalla", by_address[IGPU["address"]]["reason"])


class GpuDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, state="shut off", xml="<domain><devices/></domain>"):
        vm = VmSummary(name="hgtest-gpu", state=state, lab_id="default-lab")
        backend = _FakeBackend(xml)
        return GpuPassthroughDialog(
            backend, vm, gpus=[DGPU, IGPU],
            preflight_fn=_preflights({DGPU["address"]: PRE_OK, IGPU["address"]: PRE_BAD}),
        )

    def test_only_eligible_gpus_are_selectable(self):
        dialog = self._dialog()
        items = [dialog.gpu_list.item(i) for i in range(dialog.gpu_list.count())]
        self.assertEqual(len(items), 2)
        from PySide6.QtCore import Qt

        enabled = [item for item in items if item.flags() & Qt.ItemFlag.ItemIsEnabled]
        self.assertEqual(len(enabled), 1)
        self.assertIn(DGPU["address"], enabled[0].text())

    def test_attach_disabled_until_eligible_selection(self):
        dialog = self._dialog()
        self.assertFalse(dialog.attach_button.isEnabled())
        dialog.gpu_list.setCurrentRow(0)  # la apta
        self.assertTrue(dialog.attach_button.isEnabled())

    def test_running_vm_cannot_attach(self):
        dialog = self._dialog(state="running")
        dialog.gpu_list.setCurrentRow(0)
        self.assertFalse(dialog.attach_button.isEnabled())

    def test_attach_sets_action_after_confirm(self):
        dialog = self._dialog()
        dialog.gpu_list.setCurrentRow(0)
        with mock.patch("hypergery_ubuntu.ui_qt.dialogs.confirm", return_value=True):
            dialog._accept_attach()
        self.assertEqual(dialog.action, "attach")
        self.assertEqual(dialog.selected_row()["address"], DGPU["address"])

    def test_attach_aborts_without_confirm(self):
        dialog = self._dialog()
        dialog.gpu_list.setCurrentRow(0)
        with mock.patch("hypergery_ubuntu.ui_qt.dialogs.confirm", return_value=False):
            dialog._accept_attach()
        self.assertEqual(dialog.action, "")

    def test_detach_button_only_with_attached_gpus(self):
        dialog = self._dialog()
        self.assertFalse(dialog.detach_button.isVisible() and True)
        xml = (
            "<domain><devices><hostdev mode='subsystem' type='pci' managed='yes'>"
            "<source><address domain='0x0000' bus='0x01' slot='0x00' function='0x0'/></source>"
            "</hostdev></devices></domain>"
        )
        dialog = self._dialog(xml=xml)
        self.assertEqual(dialog.attached, ["0000:01:00.0"])
        self.assertTrue(dialog.detach_button.isEnabled())
        with mock.patch("hypergery_ubuntu.ui_qt.dialogs.confirm", return_value=True):
            dialog._accept_detach()
        self.assertEqual(dialog.action, "detach")


if __name__ == "__main__":
    unittest.main()
