"""Evacuación por batería: histéresis del monitor, bloqueos por VM,
migración en lote con rollback por VM, diálogo y consola remota."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.ui_qt.evacuation import (  # noqa: E402
    EvacuationDialog,
    EvacuationMonitor,
    evacuate_running_vms,
    vm_evacuation_blockers,
)


def _state(percent=25, tier="offload", charging=False, available=True):
    return {"available": available, "percent": percent, "tier": tier, "charging": charging}


class MonitorTests(unittest.TestCase):
    def test_offers_once_when_entering_offload(self):
        monitor = EvacuationMonitor()
        self.assertFalse(monitor.should_offer(_state(45, "eco")))
        self.assertTrue(monitor.should_offer(_state(30, "offload")))
        # No insiste mientras sigue baja.
        self.assertFalse(monitor.should_offer(_state(28, "offload")))
        self.assertFalse(monitor.should_offer(_state(15, "emergency")))

    def test_rearms_after_charging(self):
        monitor = EvacuationMonitor()
        self.assertTrue(monitor.should_offer(_state(30, "offload")))
        self.assertFalse(monitor.should_offer(_state(31, "offload", charging=True)))
        self.assertTrue(monitor.should_offer(_state(29, "offload")))

    def test_rearms_after_recovering_level(self):
        monitor = EvacuationMonitor()
        self.assertTrue(monitor.should_offer(_state(30, "offload")))
        self.assertFalse(monitor.should_offer(_state(60, "normal")))
        self.assertTrue(monitor.should_offer(_state(30, "offload")))

    def test_never_offers_charging_or_unavailable(self):
        monitor = EvacuationMonitor()
        self.assertFalse(monitor.should_offer(_state(10, "critical", charging=True)))
        self.assertFalse(monitor.should_offer(_state(None, "normal", available=False)))


class BlockerTests(unittest.TestCase):
    def test_clean_vm_has_no_blockers(self):
        self.assertEqual(vm_evacuation_blockers("<domain><devices/></domain>"), [])

    def test_hostdev_blocks(self):
        xml = "<domain><devices><hostdev mode='subsystem' type='pci'/></devices></domain>"
        self.assertIn("GPU/dispositivo físico conectado", vm_evacuation_blockers(xml))

    def test_virgl_blocks(self):
        xml = (
            "<domain><devices><video><model type='virtio'>"
            "<acceleration accel3d='yes'/></model></video></devices></domain>"
        )
        self.assertIn("aceleración 3D (VirGL)", vm_evacuation_blockers(xml))


class _FakeVm:
    def __init__(self, xml):
        self.xml = xml


class _FakeBackend:
    def __init__(self, cdrom=False):
        iso = "<disk device='cdrom'><source file='/x.iso'/><target dev='sdb'/></disk>" if cdrom else ""
        self._xml = f"<domain><devices>{iso}</devices></domain>"
        self.ejected = []

    def get_vm(self, name):
        return _FakeVm(self._xml)

    def virsh(self, args, check=True):
        if args[0] == "change-media":
            self.ejected.append(args[1])

            class R:
                returncode = 0

            return R()
        raise AssertionError(f"virsh inesperado: {args}")


class _FakeMigrator:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def factory(self, plan):
        self.calls.append(plan)
        outcome = self.results[len(self.calls) - 1]

        class Runner:
            def __init__(self, result):
                self._result = result

            def run(self):
                if isinstance(self._result, Exception):
                    raise self._result
                return self._result

        return Runner(outcome)


class EvacuateTests(unittest.TestCase):
    def test_migrates_each_vm_and_reports(self):
        fake = _FakeMigrator([
            {"ok": True, "measured_downtime_ms": 120, "status": "done"},
            {"ok": False, "error": "mkdir denied", "status": "failed"},
        ])
        log = []
        result = evacuate_running_vms(
            _FakeBackend(), ["vm-a", "vm-b"], "qemu+ssh://gery@portatil/system",
            migrator_factory=fake.factory, progress=log.append,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["migrated"], ["vm-a"])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0].vm_name, "vm-a")
        self.assertEqual(result["results"][1]["error"], "mkdir denied")
        self.assertTrue(any("Migrando en vivo vm-a" in line for line in log))

    def test_one_crash_does_not_stop_the_rest(self):
        fake = _FakeMigrator([RuntimeError("boom"), {"ok": True, "status": "done"}])
        result = evacuate_running_vms(
            _FakeBackend(), ["vm-a", "vm-b"], "qemu+ssh://gery@p/system",
            migrator_factory=fake.factory,
        )
        self.assertEqual(result["migrated"], ["vm-b"])
        self.assertIn("boom", result["results"][0]["error"])

    def test_cdroms_are_ejected_before_migrating(self):
        backend = _FakeBackend(cdrom=True)
        fake = _FakeMigrator([{"ok": True, "status": "done"}])
        evacuate_running_vms(backend, ["vm-a"], "qemu+ssh://g@p/system", migrator_factory=fake.factory)
        self.assertEqual(backend.ejected, ["vm-a"])


CANDIDATES = [
    {"host": {"host_id": "portatil", "ssh_user": "gery", "ssh_address": "192.168.1.73"},
     "host_id": "portatil", "hostname": "portatil", "ready": True, "reason": ""},
    {"host": {"host_id": "nas"}, "host_id": "nas", "hostname": "nas",
     "ready": False, "reason": "sin conexión con el Hub"},
]


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lists_vms_with_verdict_and_picks_target(self):
        vms = [{"name": "win11", "blockers": []}, {"name": "gamer", "blockers": ["aceleración 3D (VirGL)"]}]
        dialog = EvacuationDialog(28, CANDIDATES, vms)
        self.assertEqual(dialog.evacuable_names(), ["win11"])
        self.assertEqual(dialog.vm_list.count(), 2)
        self.assertIn("se queda aquí", dialog.vm_list.item(1).text())
        target = dialog.selected_target()
        self.assertIsNotNone(target)
        self.assertEqual(target["host_id"], "portatil")
        self.assertTrue(dialog.go_button.isEnabled())

    def test_disabled_without_evacuable_vms(self):
        vms = [{"name": "gamer", "blockers": ["GPU/dispositivo físico conectado"]}]
        dialog = EvacuationDialog(28, CANDIDATES, vms)
        self.assertFalse(dialog.go_button.isEnabled())


class RemoteConsoleTests(unittest.TestCase):
    def test_rejects_insecure_uri_and_launches_secure(self):
        from hypergery_ubuntu.backend import HyperGeryBackend, HyperGeryError

        backend = HyperGeryBackend()
        with self.assertRaises(HyperGeryError):
            backend.open_remote_console("vm-a", "qemu+tcp://host/system")
        with mock.patch("shutil.which", return_value="/usr/bin/virt-viewer"), \
             mock.patch.object(backend, "launch_viewer") as launcher:
            backend.open_remote_console("vm-a", "qemu+ssh://gery@portatil/system")
        launcher.assert_called_once_with(
            ["/usr/bin/virt-viewer", "--connect", "qemu+ssh://gery@portatil/system", "vm-a"]
        )


if __name__ == "__main__":
    unittest.main()
