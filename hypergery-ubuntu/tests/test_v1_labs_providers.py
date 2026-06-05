import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hypergery_ubuntu.backend import HyperGeryError, VmSummary
from hypergery_ubuntu.labs import LAB_SUBJECTS, LabStore
from hypergery_ubuntu.v1.errors import LabValidationError
from hypergery_ubuntu.v1.labsx import filter_labs, require_valid_lab, validate_lab
from hypergery_ubuntu.v1.providers import AgentProvider, LocalProvider, SimulatedProvider, VmInfo


class LabWorkspaceFieldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LabStore(Path(self.tmp.name))
        self.lab = self.store.create_lab("ASR Lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_labs_get_v09_defaults(self):
        self.assertEqual(self.lab["subject"], "CUSTOM")
        self.assertEqual(self.lab["tags"], [])
        self.assertFalse(self.lab["favorite"])
        self.assertFalse(self.lab["archived"])
        self.assertEqual(self.lab["last_started_at"], "")

    def test_update_workspace_fields(self):
        updated = self.store.update_workspace_fields(
            "asr-lab", subject="asr", tags=["red", "blue", "red"], favorite=True, owner="gerard"
        )
        self.assertEqual(updated["subject"], "ASR")
        self.assertEqual(updated["tags"], ["blue", "red"])
        self.assertTrue(updated["favorite"])
        self.assertEqual(updated["owner"], "gerard")
        # Survives a read roundtrip (manifest migration keeps the fields).
        again = self.store.get_lab("asr-lab")
        self.assertEqual(again["subject"], "ASR")
        self.assertTrue(again["favorite"])

    def test_unknown_field_or_subject_rejected(self):
        with self.assertRaises(HyperGeryError):
            self.store.update_workspace_fields("asr-lab", color="red")
        with self.assertRaises(HyperGeryError):
            self.store.update_workspace_fields("asr-lab", subject="KNITTING")

    def test_archive_and_touch_started(self):
        archived = self.store.update_workspace_fields("asr-lab", archived=True)
        self.assertTrue(archived["archived"])
        started = self.store.touch_started("asr-lab")
        self.assertNotEqual(started["last_started_at"], "")

    def test_old_manifest_without_v09_fields_migrates(self):
        import json

        path = self.store.lab_path("asr-lab")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for key in ("subject", "owner", "tags", "favorite", "archived", "last_started_at"):
            manifest.pop(key, None)
        manifest["subject"] = "NOT-A-SUBJECT"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        migrated = self.store.get_lab("asr-lab")
        self.assertEqual(migrated["subject"], "CUSTOM")
        self.assertFalse(migrated["archived"])


class ValidateLabTests(unittest.TestCase):
    def manifest(self, **overrides):
        base = {
            "lab_id": "asr-lab",
            "subject": "ASR",
            "subnet": "192.168.30.0/24",
            "vms": ["server-1", "client-1"],
            "vm_roles": {"server-1": "server"},
        }
        base.update(overrides)
        return base

    def test_valid_lab_passes(self):
        result = validate_lab(self.manifest())
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_duplicate_and_invalid_vm_names(self):
        result = validate_lab(self.manifest(vms=["a-vm", "a-vm", "bad name!"]))
        self.assertFalse(result["ok"])
        self.assertTrue(any("Duplicate" in error for error in result["errors"]))
        self.assertTrue(any("bad name!" in error for error in result["errors"]))

    def test_subnet_conflict_against_existing_labs(self):
        other = {"lab_id": "par-lab", "subnet": "192.168.30.0/24"}
        result = validate_lab(self.manifest(), existing_labs=[other])
        self.assertFalse(result["ok"])
        self.assertTrue(any("overlaps" in error for error in result["errors"]))
        # The same lab id does not conflict with itself.
        same = validate_lab(self.manifest(), existing_labs=[self.manifest()])
        self.assertTrue(same["ok"])

    def test_invalid_subnet_subject_and_role(self):
        result = validate_lab(self.manifest(subnet="999.0.0.0/24", subject="MAGIC", vm_roles={"server-1": "boss"}))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("Invalid subnet", joined)
        self.assertIn("Unknown subject", joined)
        self.assertIn("unknown role", joined)

    def test_storage_check(self):
        result = validate_lab(self.manifest(), min_free_disk_mib=10000, free_disk_mib=512)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Not enough storage" in error for error in result["errors"]))

    def test_require_valid_lab_raises(self):
        with self.assertRaises(LabValidationError):
            require_valid_lab(self.manifest(subject="MAGIC"))

    def test_filter_labs(self):
        labs = [
            {"lab_id": "a", "subject": "ASR", "favorite": True, "archived": False, "tags": ["net"]},
            {"lab_id": "b", "subject": "DB", "favorite": False, "archived": False, "tags": []},
            {"lab_id": "c", "subject": "ASR", "favorite": False, "archived": True, "tags": ["net"]},
        ]
        self.assertEqual([lab["lab_id"] for lab in filter_labs(labs)], ["a", "b"])
        self.assertEqual([lab["lab_id"] for lab in filter_labs(labs, subject="asr")], ["a"])
        self.assertEqual([lab["lab_id"] for lab in filter_labs(labs, favorites_only=True)], ["a"])
        self.assertEqual([lab["lab_id"] for lab in filter_labs(labs, include_archived=True)], ["a", "b", "c"])
        self.assertEqual([lab["lab_id"] for lab in filter_labs(labs, tag="net")], ["a"])
        self.assertIn("ASR", LAB_SUBJECTS)


class SimulatedProviderTests(unittest.TestCase):
    def make_provider(self):
        return SimulatedProvider(
            [
                VmInfo(id="web-1", status="shut off", ram_mb=2048, lab_id="asr-lab"),
                VmInfo(id="db-1", status="running", ram_mb=4096, lab_id="asr-lab"),
            ]
        )

    def test_lifecycle_transitions(self):
        provider = self.make_provider()
        result = provider.start_vm("web-1")
        self.assertEqual((result["previous_state"], result["new_state"]), ("shut off", "running"))
        provider.pause_vm("web-1")
        self.assertEqual(provider.get_vm("web-1").status, "paused")
        provider.resume_vm("web-1")
        provider.stop_vm("web-1")
        self.assertEqual(provider.get_vm("web-1").status, "shut off")

    def test_invalid_transitions_raise(self):
        provider = self.make_provider()
        with self.assertRaises(HyperGeryError):
            provider.start_vm("db-1")  # already running
        with self.assertRaises(HyperGeryError):
            provider.resume_vm("db-1")  # not paused
        with self.assertRaises(HyperGeryError):
            provider.pause_vm("web-1")  # shut off
        with self.assertRaises(HyperGeryError):
            provider.get_vm("ghost")

    def test_snapshot_metadata(self):
        provider = self.make_provider()
        provider.snapshot_vm("db-1", "before-upgrade")
        self.assertEqual(provider.get_vm("db-1").snapshots, ["before-upgrade"])
        with self.assertRaises(HyperGeryError):
            provider.snapshot_vm("db-1", "before-upgrade")
        provider.restore_snapshot("db-1", "before-upgrade")
        with self.assertRaises(HyperGeryError):
            provider.restore_snapshot("db-1", "missing")


class LocalProviderTests(unittest.TestCase):
    def make_backend(self):
        backend = Mock()
        backend.list_vms.return_value = [
            VmSummary(name="vm1", state="running", lab_id="asr-lab", ram_mib=2048, vcpus=2, disk_path="/d/vm1.qcow2", network="hg-net-asr-lab"),
        ]
        backend.get_vm.return_value = backend.list_vms.return_value[0]
        backend.list_snapshots.return_value = ["snap1"]
        return backend

    def test_maps_backend_summaries_to_vminfo(self):
        backend = self.make_backend()
        provider = LocalProvider(backend, host_id="laptop")
        vms = provider.list_vms()
        self.assertEqual(vms[0].id, "vm1")
        self.assertEqual(vms[0].host_id, "laptop")
        self.assertEqual(vms[0].network_ids, ["hg-net-asr-lab"])
        info = provider.get_vm("vm1")
        self.assertEqual(info.snapshots, ["snap1"])

    def test_actions_delegate_to_backend(self):
        backend = self.make_backend()
        provider = LocalProvider(backend, host_id="laptop")
        provider.start_vm("vm1")
        backend.start_vm.assert_called_once_with("vm1")
        provider.stop_vm("vm1")
        backend.shutdown_vm.assert_called_once_with("vm1")
        provider.snapshot_vm("vm1", "s1")
        backend.create_snapshot.assert_called_once_with("vm1", "s1", "")
        provider.restore_snapshot("vm1", "s1")
        backend.revert_snapshot.assert_called_once_with("vm1", "s1")

    def test_pause_resume_use_virsh_and_surface_errors(self):
        backend = self.make_backend()
        ok = Mock(returncode=0, stdout="", stderr="")
        backend.virsh.return_value = ok
        provider = LocalProvider(backend, host_id="laptop")
        provider.pause_vm("vm1")
        backend.virsh.assert_called_with(["suspend", "vm1"], check=False)
        provider.resume_vm("vm1")
        backend.virsh.assert_called_with(["resume", "vm1"], check=False)
        backend.virsh.return_value = Mock(returncode=1, stdout="", stderr="domain not running")
        with self.assertRaises(HyperGeryError):
            provider.pause_vm("vm1")


class AgentProviderTests(unittest.TestCase):
    def make_client(self):
        client = Mock()
        client.list_vms.return_value = [
            {"vm_name": "remote-1", "state": "shutoff", "lab_id": "asr-lab", "ram_mib": 2048, "vcpus": 2, "networks": ["hg-net-asr-lab"], "updated_at": "t"},
        ]
        client.queue_vm_power_command.return_value = {"command_id": "cmd-1"}
        return client

    def test_inventory_and_queueing(self):
        client = self.make_client()
        provider = AgentProvider(client, "pc-casa")
        vms = provider.list_vms()
        self.assertEqual(vms[0].id, "remote-1")
        self.assertEqual(vms[0].host_id, "pc-casa")
        result = provider.start_vm("remote-1")
        client.queue_vm_power_command.assert_called_once_with("pc-casa", "remote-1", "start")
        self.assertTrue(result["queued"])
        self.assertEqual(result["command_id"], "cmd-1")
        provider.stop_vm("remote-1")
        client.queue_vm_power_command.assert_called_with("pc-casa", "remote-1", "shutdown")

    def test_non_allowlisted_remote_actions_raise(self):
        provider = AgentProvider(self.make_client(), "pc-casa")
        for action in (provider.pause_vm, provider.resume_vm):
            with self.assertRaises(HyperGeryError):
                action("remote-1")
        with self.assertRaises(HyperGeryError):
            provider.snapshot_vm("remote-1", "s")
        with self.assertRaises(HyperGeryError):
            provider.restore_snapshot("remote-1", "s")

    def test_get_vm_missing_raises(self):
        provider = AgentProvider(self.make_client(), "pc-casa")
        with self.assertRaises(HyperGeryError):
            provider.get_vm("ghost")


if __name__ == "__main__":
    unittest.main()
