import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.backend import CommandResult, HyperGeryError, VmSummary
from hypergery_ubuntu.v1.settings import V1Settings
from hypergery_ubuntu.v1.state_migration import (
    export_vm_state_package,
    import_vm_state_package,
    validate_state_package,
)
from hypergery_ubuntu.v1.teleport import TeleportEngine

DOMAIN_XML = """<domain type='kvm'>
  <name>{name}</name>
  <uuid>11111111-2222-3333-4444-555555555555</uuid>
  <memory unit='KiB'>262144</memory>
  <vcpu>1</vcpu>
  <devices>
    <disk type='file' device='disk'>
      <source file='{disk}'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='network'>
      <mac address='52:54:00:11:22:33'/>
      <source network='hg-net-default-lab'/>
    </interface>
  </devices>
</domain>"""


class StateFakeBackend:
    """A fake libvirt backend that records save/restore for state migration."""

    def __init__(self, root: Path, *, state: str = "running", host: str = "host"):
        self.data_dir = root / "data"
        self.vms_dir = self.data_dir / "vms"
        self.vms_dir.mkdir(parents=True)
        self.disk = root / "src-disk.qcow2"
        self.disk.write_bytes(b"DISK-CONTENT" * 100)
        self._state = state
        self.defined = set()
        self.restored_with = None
        self.saved_to = None
        self.lab_updates = []

    def get_vm(self, name):
        return VmSummary(name=name, state=self._state, lab_id="default-lab", ram_mib=256, vcpus=1,
                         disk_path=str(self.disk), network="hg-net-default-lab")

    def virsh(self, args, *, check=True, timeout=120):
        if args[:1] == ["dumpxml"]:
            return CommandResult(["virsh", *args], 0, DOMAIN_XML.format(name=args[1], disk=self.disk), "")
        if args[:1] == ["dominfo"]:
            return CommandResult(["virsh", *args], 0 if args[1] in self.defined else 1, "", "")
        return CommandResult(["virsh", *args], 0, "", "")

    def save_vm(self, name, state_path):
        target = Path(state_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"FAKE-RAM-STATE")
        self.saved_to = target
        self._state = "shut off"
        return target

    def restore_vm(self, state_path, xml_path=None):
        if not Path(state_path).is_file():
            raise HyperGeryError("missing state file")
        self.restored_with = (Path(state_path), Path(xml_path) if xml_path else None)
        self._state = "running"

    def ensure_network(self, lab_id, network_mode):
        return f"hg-net-{lab_id}"

    def grant_libvirt_qemu_access(self, *paths):
        return None

    def update_lab_for_vm(self, *args):
        self.lab_updates.append(args)


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_requires_running_vm(self):
        backend = StateFakeBackend(self.root, state="shut off")
        with self.assertRaises(HyperGeryError) as ctx:
            export_vm_state_package(backend, "vm1", self.root / "out")
        self.assertIn("running", str(ctx.exception))

    def test_export_freezes_and_packages_state_and_disk(self):
        backend = StateFakeBackend(self.root, state="running")
        result = export_vm_state_package(backend, "vm1", self.root / "out")
        package = Path(result["package_dir"])
        self.assertEqual(backend._state, "shut off")  # frozen
        self.assertTrue((package / "memory-state.save").is_file())
        self.assertTrue((package / "domain.xml").is_file())
        self.assertTrue((package / "disks" / "src-disk.qcow2").is_file())
        validation = validate_state_package(package)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual(validation["manifest"]["source_will_be_deleted"], False)

    def test_export_resumes_source_and_cleans_up_when_disk_copy_fails(self):
        # save_vm froze the VM; then the disk copy fails. The source must be
        # resumed from its saved state and no partial package left behind.
        backend = StateFakeBackend(self.root, state="running")
        backend.disk.unlink()  # disk vanishes -> copy step raises after save_vm
        out = self.root / "out"
        with self.assertRaises(HyperGeryError) as ctx:
            export_vm_state_package(backend, "vm1", out)
        self.assertIsNotNone(backend.restored_with)  # restore/resume was called
        self.assertEqual(backend._state, "running")  # continues where it was
        self.assertFalse((out / "state-vm1").exists())  # no partial package
        self.assertIn("resumed locally", str(ctx.exception))

    def test_export_preserves_state_when_resume_also_fails(self):
        # Worst case: packaging fails AND the automatic resume fails too. We must
        # keep the saved RAM state so the user can restore it by hand, and say so.
        backend = StateFakeBackend(self.root, state="running")
        backend.disk.unlink()

        def broken_restore(state_path, xml_path=None):
            raise HyperGeryError("restore exploded")

        backend.restore_vm = broken_restore
        out = self.root / "out"
        with self.assertRaises(HyperGeryError) as ctx:
            export_vm_state_package(backend, "vm1", out)
        self.assertEqual(backend._state, "shut off")  # could not be resumed
        self.assertTrue((out / "state-vm1" / "memory-state.save").is_file())  # preserved
        self.assertIn("state preserved", str(ctx.exception))

    def test_export_failure_before_save_leaves_source_running(self):
        # If we fail before save_vm runs, the source was never frozen by us.
        backend = StateFakeBackend(self.root, state="running")

        def failing_virsh(args, *, check=True, timeout=120):
            if args[:1] == ["dumpxml"]:
                return CommandResult(["virsh", *args], 1, "", "boom")
            return CommandResult(["virsh", *args], 0, "", "")

        backend.virsh = failing_virsh
        out = self.root / "out"
        with self.assertRaises(HyperGeryError):
            export_vm_state_package(backend, "vm1", out)
        self.assertEqual(backend._state, "running")  # never frozen
        self.assertIsNone(backend.restored_with)
        self.assertFalse((out / "state-vm1").exists())  # partial package dropped

    def test_validate_detects_missing_pieces(self):
        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        (package / "memory-state.save").unlink()
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("Memory state" in e for e in validation["errors"]))

    def test_validate_detects_truncated_memory_state(self):
        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        (package / "memory-state.save").write_bytes(b"trunc")  # shorter than original
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("memory-state.save" in e for e in validation["errors"]), validation["errors"])

    def test_validate_detects_corrupt_disk_same_size(self):
        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        disk = package / "disks" / "src-disk.qcow2"
        corrupted = b"X" * disk.stat().st_size  # same size, different bytes
        disk.write_bytes(corrupted)
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("Checksum mismatch" in e for e in validation["errors"]), validation["errors"])

    def test_validate_accepts_legacy_package_without_checksums(self):
        # A package written before v1.0.1 has no sha256/size; it still validates
        # on existence so old staged packages keep working.
        import json

        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        manifest_path = package / "state-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in [k for k in manifest if k.endswith("_sha256") or k.endswith("_size_bytes")]:
            manifest.pop(key)
        for asset in manifest.get("disks", []):
            asset.pop("sha256", None)
            asset.pop("size_bytes", None)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validation = validate_state_package(package)
        self.assertTrue(validation["ok"], validation["errors"])

    def _export_and_patch_manifest(self, **manifest_updates):
        import json

        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        manifest_path = package / "state-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(manifest_updates)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return package

    def test_validate_rejects_absolute_memory_state(self):
        package = self._export_and_patch_manifest(memory_state="/etc/hosts")
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertIn("Absolute package member path", "; ".join(validation["errors"]))

    def test_validate_rejects_absolute_domain_xml(self):
        package = self._export_and_patch_manifest(domain_xml="/etc/passwd")
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertIn("Absolute package member path", "; ".join(validation["errors"]))

    def test_validate_rejects_absolute_asset_relative_path(self):
        package = self._export_and_patch_manifest(
            disks=[{"original": "/x.qcow2", "relative_path": "/etc/hosts"}]
        )
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertIn("Absolute package member path", "; ".join(validation["errors"]))

    def test_validate_rejects_traversal_in_asset_relative_path(self):
        package = self._export_and_patch_manifest(
            disks=[{"original": "/x.qcow2", "relative_path": "../../escape.qcow2"}]
        )
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertIn("Path traversal", "; ".join(validation["errors"]))

    def test_validate_rejects_symlink_member(self):
        backend = StateFakeBackend(self.root, state="running")
        package = Path(export_vm_state_package(backend, "vm1", self.root / "out")["package_dir"])
        outside = self.root / "secret.bin"
        outside.write_bytes(b"top secret")
        link = package / "disks" / "linked.qcow2"
        link.symlink_to(outside)
        import json

        manifest_path = package / "state-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["disks"] = [{"original": str(backend.disk), "relative_path": "disks/linked.qcow2"}]
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validation = validate_state_package(package)
        self.assertFalse(validation["ok"])
        self.assertIn("Symlinks are not allowed", "; ".join(validation["errors"]))

    def test_import_rejects_malicious_state_package(self):
        package = self._export_and_patch_manifest(memory_state="/etc/hosts")
        tgt = StateFakeBackend(self.root / "tgt", state="shut off")
        with self.assertRaises(HyperGeryError):
            import_vm_state_package(tgt, package)
        self.assertIsNone(tgt.restored_with)

    def test_import_restores_preserving_identity_on_fresh_host(self):
        src = StateFakeBackend(self.root / "src", state="running")
        package = export_vm_state_package(src, "vm1", self.root / "out")["package_dir"]
        # Target host: a different backend (own vms_dir), VM not defined there.
        tgt = StateFakeBackend(self.root / "tgt", state="shut off")
        result = import_vm_state_package(tgt, package)
        self.assertTrue(result["state_preserved"])
        self.assertEqual(result["target_vm_name"], "vm1")  # identity preserved
        self.assertEqual(tgt._state, "running")  # continued
        # Restore was called with the state file and a rewritten XML.
        self.assertIsNotNone(tgt.restored_with)
        state_file, xml_file = tgt.restored_with
        self.assertTrue(state_file.name == "memory-state.save")
        self.assertIsNotNone(xml_file)
        # The disk was copied into the target's vms dir.
        self.assertTrue((tgt.vms_dir / "vm1" / "src-disk.qcow2").is_file())

    def test_import_refuses_when_target_already_has_the_vm(self):
        src = StateFakeBackend(self.root / "src", state="running")
        package = export_vm_state_package(src, "vm1", self.root / "out")["package_dir"]
        tgt = StateFakeBackend(self.root / "tgt", state="shut off")
        tgt.defined.add("vm1")  # collision
        with self.assertRaises(HyperGeryError) as ctx:
            import_vm_state_package(tgt, package)
        self.assertIn("already has a VM named vm1", str(ctx.exception))


class SaveRestoreTeleportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_client(self, target_online=True):
        from tests.test_migration import FakeRegistryClient

        client = FakeRegistryClient()
        if not target_online:
            client.hosts["target"]["status"] = "offline"
        client.uploaded = []
        orig = getattr(client, "upload_package", None)

        def upload_package(migration_id, package_dir):
            client.uploaded.append((migration_id, str(package_dir)))
            return {"migration_id": migration_id}

        client.upload_package = upload_package
        return client

    def test_save_restore_freezes_uploads_and_queues_restore(self):
        backend = StateFakeBackend(self.root, state="running")
        # give the backend a hub-transfer staging dir via data_dir
        client = self.make_client()
        engine = TeleportEngine(backend, settings=V1Settings(), hub_client=client, source_host_id="src")
        result = engine.teleport_vm(
            "vm1", mode="save_restore", target_host_id="target", staging_dir=self.root / "stage"
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["state_preserved"])
        self.assertEqual(backend._state, "shut off")  # source frozen
        self.assertEqual(len(client.uploaded), 1)
        queued = client.created_commands[-1]
        self.assertEqual(queued["command_type"], "restore_vm_state_package")
        self.assertEqual(queued["target_host_id"], "target")
        self.assertEqual(queued["payload"]["migration_id"], client.uploaded[0][0])

    def test_save_restore_offline_target_does_not_freeze_source(self):
        backend = StateFakeBackend(self.root, state="running")
        client = self.make_client(target_online=False)
        engine = TeleportEngine(backend, settings=V1Settings(), hub_client=client, source_host_id="src")
        from hypergery_ubuntu.v1.errors import HostOfflineError

        with self.assertRaises(HostOfflineError):
            engine.teleport_vm("vm1", mode="save_restore", target_host_id="target", staging_dir=self.root / "stage")
        # Source must NOT have been frozen if the target was never reachable.
        self.assertEqual(backend._state, "running")

    def test_save_restore_resumes_source_if_shipping_fails(self):
        from hypergery_ubuntu.v1.errors import TeleportError

        backend = StateFakeBackend(self.root, state="running")
        client = self.make_client()

        def broken_upload(migration_id, package_dir):
            raise OSError("hub upload exploded")

        client.upload_package = broken_upload
        engine = TeleportEngine(backend, settings=V1Settings(), hub_client=client, source_host_id="src")
        with self.assertRaises(TeleportError) as ctx:
            engine.teleport_vm("vm1", mode="save_restore", target_host_id="target", staging_dir=self.root / "stage")
        # The VM was frozen, shipping failed, so it must be resumed locally —
        # never left stopped.
        self.assertEqual(backend._state, "running")
        self.assertIn("resumed locally", str(ctx.exception))
        self.assertIsNotNone(backend.restored_with)

    def test_save_restore_unreadable_state_file_resumes_and_explains(self):
        from hypergery_ubuntu.v1.errors import TeleportError

        backend = StateFakeBackend(self.root, state="running")

        # Make the saved state file unreadable to simulate root-owned state.
        original_save = backend.save_vm

        def save_unreadable(name, state_path):
            target = original_save(name, state_path)
            import os

            os.chmod(target, 0o000)
            return target

        backend.save_vm = save_unreadable
        client = self.make_client()
        engine = TeleportEngine(backend, settings=V1Settings(), hub_client=client, source_host_id="src")
        try:
            with self.assertRaises(TeleportError) as ctx:
                engine.teleport_vm("vm1", mode="save_restore", target_host_id="target", staging_dir=self.root / "stage")
            self.assertIn("not readable", str(ctx.exception))
            self.assertEqual(backend._state, "running")  # resumed
            # Nothing was uploaded (we bailed before shipping).
            self.assertEqual(client.uploaded, [])
        finally:
            import os
            for path in self.root.rglob("memory-state.save"):
                try:
                    os.chmod(path, 0o644)
                except OSError:
                    pass

    def test_save_restore_is_an_allowlisted_command(self):
        from hypergery_ubuntu.registry import ALLOWED_COMMAND_TYPES

        self.assertIn("restore_vm_state_package", ALLOWED_COMMAND_TYPES)


class AgentRestoreCommandTests(unittest.TestCase):
    def test_agent_executes_restore_vm_state_package(self):
        from hypergery_ubuntu.agent import AgentConfig, HyperGeryAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Build a real state package on the "source".
            src = StateFakeBackend(root / "src", state="running")
            package = export_vm_state_package(src, "vm1", root / "out")["package_dir"]

            # Target backend the agent restores into.
            tgt = StateFakeBackend(root / "tgt", state="shut off")
            tgt.data_dir = root / "tgt" / "data"  # used for hub_transfer staging

            deleted = []

            class FakeClient:
                def __init__(self):
                    self.reported = None

                def download_package(self, migration_id, destination_dir):
                    import shutil

                    shutil.copytree(package, destination_dir)
                    return Path(destination_dir)

                def delete_package(self, migration_id):
                    deleted.append(migration_id)
                    return {"deleted": True}

                def report_vms(self, host_id, vms):
                    self.reported = (host_id, vms)

            agent = HyperGeryAgent(AgentConfig(host_id="target"), backend=tgt, client=FakeClient())
            # vm_inventory_payload uses backend.list_vms which the fake lacks;
            # patch it to a no-op so the post-restore report doesn't error.
            agent.vm_inventory_payload = lambda: {"vms": []}

            status, result = agent.execute_command(
                {"command_type": "restore_vm_state_package", "payload": {"migration_id": "state-vm1-abc"}}
            )
            self.assertEqual(status, "done")
            self.assertTrue(result["state_preserved"])
            self.assertEqual(tgt._state, "running")
            self.assertTrue(result["hub_package_deleted"])
            self.assertEqual(deleted, ["state-vm1-abc"])

    def test_restore_command_requires_migration_id(self):
        from hypergery_ubuntu.agent import AgentConfig, HyperGeryAgent

        with tempfile.TemporaryDirectory() as tmp:
            tgt = StateFakeBackend(Path(tmp), state="shut off")
            agent = HyperGeryAgent(AgentConfig(host_id="target"), backend=tgt, client=object())
            with self.assertRaises(HyperGeryError):
                agent.execute_command({"command_type": "restore_vm_state_package", "payload": {}})


if __name__ == "__main__":
    unittest.main()
