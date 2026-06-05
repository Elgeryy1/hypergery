import shutil
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.backend import CommandResult
from hypergery_ubuntu.v1.errors import HostOfflineError, MemDiffError, TeleportError
from hypergery_ubuntu.v1.memdiff import (
    DEFAULT_BLOCK_SIZE,
    apply_delta,
    compare_snapshots,
    load_delta,
    produce_delta,
    save_delta,
    snapshot_state,
    verify_result,
)
from hypergery_ubuntu.v1.settings import V1Settings
from hypergery_ubuntu.v1.teleport import TeleportEngine
from tests.test_migration import FakeBackend, FakeRegistryClient


class MemDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.block = 1024
        # Base state: 8 blocks of repeating data.
        self.base_path = self.root / "state-a.bin"
        self.base_path.write_bytes(b"".join(bytes([i]) * self.block for i in range(8)))
        # Target: blocks 2 and 5 changed, plus one appended block.
        data = bytearray(self.base_path.read_bytes())
        data[2 * self.block : 3 * self.block] = b"\xaa" * self.block
        data[5 * self.block : 6 * self.block] = b"\xbb" * self.block
        data.extend(b"\xcc" * self.block)
        self.target_path = self.root / "state-b.bin"
        self.target_path.write_bytes(bytes(data))

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_blocks_and_hashes(self):
        snapshot = snapshot_state(self.base_path, block_size=self.block)
        self.assertEqual(len(snapshot.block_hashes), 8)
        self.assertEqual(snapshot.size_bytes, 8 * self.block)
        self.assertTrue(snapshot.snapshot_id.startswith("mds-"))
        with self.assertRaises(MemDiffError):
            snapshot_state(self.root / "missing.bin")
        with self.assertRaises(MemDiffError):
            snapshot_state(self.base_path, block_size=0)

    def test_compare_detects_changed_and_appended_blocks(self):
        base = snapshot_state(self.base_path, block_size=self.block)
        target = snapshot_state(self.target_path, block_size=self.block)
        comparison = compare_snapshots(base, target)
        self.assertEqual(comparison["changed_blocks"], [2, 5, 8])
        self.assertFalse(comparison["identical"])
        identical = compare_snapshots(base, snapshot_state(self.base_path, block_size=self.block))
        self.assertTrue(identical["identical"])
        with self.assertRaises(MemDiffError):
            compare_snapshots(base, snapshot_state(self.target_path, block_size=self.block * 2))

    def test_delta_apply_and_verify_roundtrip(self):
        base = snapshot_state(self.base_path, block_size=self.block)
        delta = produce_delta(base, self.target_path)
        self.assertEqual(sorted(delta.changed_blocks), [2, 5, 8])
        savings = delta.savings_estimate()
        self.assertEqual(savings["delta_size_bytes"], 3 * self.block)
        self.assertGreater(savings["saved_percent"], 50)
        output = self.root / "rebuilt.bin"
        apply_delta(self.base_path, delta, output)
        self.assertEqual(output.read_bytes(), self.target_path.read_bytes())
        self.assertTrue(verify_result(output, delta))

    def test_apply_with_wrong_base_fails_and_removes_output(self):
        base = snapshot_state(self.base_path, block_size=self.block)
        delta = produce_delta(base, self.target_path)
        wrong_base = self.root / "wrong.bin"
        wrong_base.write_bytes(b"\xff" * 8 * self.block)
        output = self.root / "bad.bin"
        with self.assertRaises(MemDiffError):
            apply_delta(wrong_base, delta, output)
        self.assertFalse(output.exists())

    def test_save_and_load_delta_with_corruption_detection(self):
        base = snapshot_state(self.base_path, block_size=self.block)
        delta = produce_delta(base, self.target_path)
        delta_dir = self.root / "delta"
        save_delta(delta, delta_dir)
        loaded = load_delta(delta_dir)
        self.assertEqual(loaded.target_full_hash, delta.target_full_hash)
        output = self.root / "from-disk.bin"
        apply_delta(self.base_path, loaded, output)
        self.assertEqual(output.read_bytes(), self.target_path.read_bytes())
        # Corrupt one block on disk → load refuses it.
        (delta_dir / "blocks" / "2.bin").write_bytes(b"\x00" * self.block)
        with self.assertRaises(MemDiffError):
            load_delta(delta_dir)
        # Missing block file is also detected.
        shutil.rmtree(delta_dir / "blocks")
        with self.assertRaises(MemDiffError):
            load_delta(delta_dir)

    def test_apply_io_error_leaves_no_partial_file(self):
        from unittest.mock import patch

        base = snapshot_state(self.base_path, block_size=self.block)
        delta = produce_delta(base, self.target_path)
        output = self.root / "io-fail.bin"
        with patch("shutil.copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(MemDiffError):
                apply_delta(self.base_path, delta, output)
        self.assertFalse(output.exists())

    def test_default_block_size_sane(self):
        self.assertEqual(DEFAULT_BLOCK_SIZE, 64 * 1024)


class SuspendableBackend(FakeBackend):
    def __init__(self, root: Path, *, state: str = "shut off") -> None:
        super().__init__(root, state=state)
        self.virsh_calls = []
        self.fail_suspend = False

    def vm_state(self, name: str) -> str:
        return self.state

    def virsh(self, args, *, timeout=120, check=True):
        self.virsh_calls.append(list(args))
        if args[:1] == ["suspend"]:
            if self.fail_suspend:
                return CommandResult(["virsh", *args], 1, "", "suspend failed")
            self.state = "paused"
            return CommandResult(["virsh", *args], 0, "", "")
        if args[:1] == ["resume"]:
            self.state = "running"
            return CommandResult(["virsh", *args], 0, "", "")
        return super().virsh(args, timeout=timeout, check=check)


class TeleportEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    _engine_counter = 0

    def make_engine(self, *, state="shut off", client=None, **settings_kwargs):
        TeleportEngineTests._engine_counter += 1
        backend = SuspendableBackend(self.root / f"src-{self._engine_counter}", state=state)
        engine = TeleportEngine(
            backend,
            settings=V1Settings(**settings_kwargs),
            hub_client=client,
            source_host_id="laptop",
        )
        return engine, backend

    def test_unknown_mode_rejected(self):
        engine, _ = self.make_engine()
        with self.assertRaises(TeleportError):
            engine.teleport_vm("hg-source", mode="warp_drive")

    def test_dry_run_validates_without_copying(self):
        engine, _ = self.make_engine()
        result = engine.teleport_vm("hg-source", mode="dry_run")
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["ok"], result["preflight"].get("errors"))
        self.assertEqual(result["mode"], "dry_run")
        self.assertTrue(result["operation_id"].startswith("teleport-"))
        # Nothing staged anywhere.
        self.assertFalse(list(self.root.glob("**/teleport_manifest.json")))

    def test_dry_run_checks_target_host_through_hub(self):
        client = FakeRegistryClient()
        client.hosts["pc-casa"] = {"host_id": "pc-casa", "status": "offline"}
        engine, _ = self.make_engine(client=client)
        result = engine.teleport_vm("hg-source", mode="dry_run", target_host_id="pc-casa")
        self.assertFalse(result["ok"])
        self.assertFalse(result["target_check"]["online"])
        online = engine.teleport_vm("hg-source", mode="dry_run", target_host_id="target")
        self.assertTrue(online["target_check"]["online"])

    def test_local_loopback_full_pipeline(self):
        engine, backend = self.make_engine()
        result = engine.teleport_vm(
            "hg-source", mode="local_loopback", staging_dir=self.root / "staging", target_vm_name="hg-loop"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["target_vm_name"], "hg-loop")
        package_dir = Path(result["package_dir"])
        self.assertTrue((package_dir / "teleport_manifest.json").is_file())
        # The package validates and the import defined the new VM.
        self.assertIn("hg-loop", backend.defined_xml)
        # Source disk untouched.
        self.assertEqual(backend.disk.read_bytes(), b"disk-data")

    def test_local_loopback_requires_staging_dir(self):
        engine, _ = self.make_engine()
        with self.assertRaises(TeleportError):
            engine.teleport_vm("hg-source", mode="local_loopback")

    def test_suspend_copy_start_suspends_running_vm_and_queues_import(self):
        client = FakeRegistryClient()
        engine, backend = self.make_engine(state="running", client=client)
        result = engine.teleport_vm(
            "hg-source",
            mode="suspend_copy_start",
            target_host_id="target",
            staging_dir=self.root / "staging",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["suspended_source"])
        self.assertIn(["suspend", "hg-source"], backend.virsh_calls)
        self.assertEqual(backend.state, "paused")  # stays paused until verified
        self.assertTrue(result["migration"].get("migration_id"))
        self.assertTrue(client.created_commands)
        self.assertEqual(client.created_commands[-1]["command_type"], "import_vm_package")

    def test_suspend_copy_start_offline_target_fails_before_touching_vm(self):
        client = FakeRegistryClient()
        client.hosts["pc-casa"] = {"host_id": "pc-casa", "status": "offline"}
        engine, backend = self.make_engine(state="running", client=client)
        with self.assertRaises(HostOfflineError):
            engine.teleport_vm(
                "hg-source", mode="suspend_copy_start", target_host_id="pc-casa", staging_dir=self.root / "s"
            )
        self.assertEqual(backend.state, "running")
        self.assertNotIn(["suspend", "hg-source"], backend.virsh_calls)

    def test_suspend_copy_start_rollback_resumes_on_failure(self):
        client = FakeRegistryClient()

        def broken_upload(migration_id, package_dir):
            raise OSError("hub upload exploded")

        client.upload_package = broken_upload
        engine, backend = self.make_engine(state="running", client=client)
        with self.assertRaises(TeleportError) as ctx:
            engine.teleport_vm(
                "hg-source", mode="suspend_copy_start", target_host_id="target", staging_dir=self.root / "s"
            )
        self.assertIn("left resumed", str(ctx.exception))
        self.assertIn(["resume", "hg-source"], backend.virsh_calls)
        self.assertEqual(backend.state, "running")
        # Source data intact.
        self.assertEqual(backend.disk.read_bytes(), b"disk-data")

    def test_rollback_reports_truthfully_when_resume_fails(self):
        from hypergery_ubuntu.backend import CommandResult

        client = FakeRegistryClient()

        def broken_upload(migration_id, package_dir):
            raise OSError("hub upload exploded")

        client.upload_package = broken_upload
        engine, backend = self.make_engine(state="running", client=client)

        original_virsh = backend.virsh

        def virsh(args, *, timeout=120, check=True):
            if args[:1] == ["resume"]:
                backend.virsh_calls.append(list(args))
                return CommandResult(["virsh", *args], 1, "", "resume failed")
            return original_virsh(args, timeout=timeout, check=check)

        backend.virsh = virsh
        with self.assertRaises(TeleportError) as ctx:
            engine.teleport_vm(
                "hg-source", mode="suspend_copy_start", target_host_id="target", staging_dir=self.root / "s"
            )
        # The message must NOT claim the VM was resumed when resume failed.
        self.assertIn("still paused", str(ctx.exception))
        self.assertNotIn("left resumed", str(ctx.exception))

    def test_suspend_failure_aborts_cleanly(self):
        client = FakeRegistryClient()
        engine, backend = self.make_engine(state="running", client=client)
        backend.fail_suspend = True
        with self.assertRaises(TeleportError):
            engine.teleport_vm(
                "hg-source", mode="suspend_copy_start", target_host_id="target", staging_dir=self.root / "s"
            )
        self.assertEqual(backend.state, "running")

    def test_experimental_memdiff_requires_flag_and_estimates_savings(self):
        engine, _ = self.make_engine()
        with self.assertRaises(TeleportError):
            engine.teleport_vm("hg-source", mode="experimental_memdiff")
        engine, backend = self.make_engine(experimental_memdiff=True)
        # Base state: previous copy of the disk; current disk then changes.
        base_state = self.root / "base-state.bin"
        base_state.write_bytes(backend.disk.read_bytes())
        result = engine.teleport_vm("hg-source", mode="experimental_memdiff", memdiff_base_state=base_state)
        self.assertTrue(result["memdiff"]["experimental"])
        self.assertTrue(result["memdiff"]["estimate"]["available"])
        # Without a base state the estimate is honestly unavailable.
        no_base = engine.teleport_vm("hg-source", mode="experimental_memdiff")
        self.assertFalse(no_base["memdiff"]["estimate"]["available"])


if __name__ == "__main__":
    unittest.main()
