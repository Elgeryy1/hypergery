"""End-to-end flows across the v1 services (goal §20.2 flows 1-5)."""

import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.labs import LabStore
from hypergery_ubuntu.v1.battery import BatteryService, BatteryState
from hypergery_ubuntu.v1.errors import PermissionDeniedError
from hypergery_ubuntu.v1.hglog import StructuredLogger, get_logger
from hypergery_ubuntu.v1.hosts import HostInfo
from hypergery_ubuntu.v1.labsx import validate_lab
from hypergery_ubuntu.v1.memdiff import apply_delta, load_delta, produce_delta, save_delta, snapshot_state, verify_result
from hypergery_ubuntu.v1.nas import NasService
from hypergery_ubuntu.v1.orchestrator import OrchestratorService
from hypergery_ubuntu.v1.providers import SimulatedProvider, VmInfo
from hypergery_ubuntu.v1.rbac import User, check_permission, require_permission
from hypergery_ubuntu.v1.settings import V1Settings
from hypergery_ubuntu.v1.teleport import TeleportEngine
from tests.test_migration import FakeBackend, FakeRegistryClient


def hosts_pair(laptop_free=12000, pc_free=28000, pc_status="online"):
    return [
        HostInfo(id="laptop", role="laptop", status="online", ram_total_mib=16384, ram_free_mib=laptop_free, capabilities=["can_run_vms"]),
        HostInfo(id="home-pc", role="home_pc", status=pc_status, ram_total_mib=32768, ram_free_mib=pc_free, capabilities=["can_run_vms"]),
    ]


def battery_at(percent: int) -> BatteryState:
    service = BatteryService(settings=V1Settings())
    return BatteryState(available=True, percent=percent, status="discharging", charging=False, tier=service.tier_for(percent))


class Flow1CreateValidatePlanTeleportTests(unittest.TestCase):
    """Create lab → validate → orchestrator plan → teleport dry-run."""

    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LabStore(root / "data")
            lab = store.create_lab("Flow Lab", "integration", "isolated")
            store.update_workspace_fields(lab["lab_id"], subject="ASR", tags=["integration"])
            lab = store.get_lab(lab["lab_id"])

            validation = validate_lab(lab, existing_labs=store.list_labs())
            self.assertTrue(validation["ok"], validation["errors"])

            provider = SimulatedProvider(
                [VmInfo(id="flow-vm", ram_mb=6144, status="running", host_id="laptop", lab_id=lab["lab_id"])]
            )
            plans = OrchestratorService(settings=V1Settings()).plan(
                hosts=hosts_pair(),
                vms=provider.list_vms(),
                battery=battery_at(90),
                local_host_id="laptop",
                lab_id=lab["lab_id"],
            )
            self.assertEqual(len(plans), 1)
            plan = plans[0]
            self.assertEqual(plan.target_host, "home-pc")  # heavy → home_pc
            self.assertEqual(plan.actions[0]["kind"], "teleport")

            backend = FakeBackend(root / "vmhost")
            engine = TeleportEngine(backend, settings=V1Settings(), hub_client=FakeRegistryClient(), source_host_id="laptop")
            result = engine.teleport_vm("hg-source", mode="dry_run", target_host_id="target")
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["target_check"]["online"])


class Flow2BatteryOffloadTests(unittest.TestCase):
    """Simulated low battery → offload recommendation → plan generated."""

    def test_full_flow(self):
        settings = V1Settings(battery_mode="recommend_only")
        service = BatteryService(settings=settings)
        state = battery_at(22)  # offload tier
        self.assertEqual(state.tier, "offload")

        actions = service.recommended_actions(state)
        kinds = {action["kind"] for action in actions}
        self.assertIn("prepare_teleport", kinds)
        self.assertIn("recommend_stop_heavy_vms", kinds)

        plans = OrchestratorService(settings=settings).plan(
            hosts=hosts_pair(laptop_free=3000),
            vms=[VmInfo(id="heavy-vm", ram_mb=6144, status="running", host_id="laptop", lab_id="asr-lab")],
            battery=state,
            local_host_id="laptop",
        )
        plan = plans[0]
        self.assertEqual(plan.target_host, "home-pc")
        self.assertIn("22%", plan.reason)
        self.assertIn("offload", plan.reason)


class Flow3NasCommitTests(unittest.TestCase):
    """NAS commit dry-run → package → checksum verification."""

    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nas_root = root / "nas"
            nas_root.mkdir()
            store = LabStore(root / "data")
            lab = store.create_lab("Commit Lab")
            nas = NasService(nas_root, settings=V1Settings(), lab_store=store)

            dry = nas.commit_lab(lab["lab_id"], existing_labs=store.list_labs())
            self.assertTrue(dry["dry_run"])
            self.assertFalse((nas_root / "labs-commits").exists())

            real = nas.commit_lab(lab["lab_id"], existing_labs=store.list_labs(), dry_run=False)
            self.assertTrue(real["verified"])
            verification = nas.verify_commit(lab["lab_id"], real["commit_id"])
            self.assertTrue(verification["ok"])

            restored = nas.restore_commit(lab["lab_id"], real["commit_id"], root / "restore", dry_run=False)
            self.assertTrue((Path(restored["destination"]) / "lab_manifest.json").is_file())


class Flow4MemDiffTests(unittest.TestCase):
    """MemDiff A/B → delta (saved/loaded) → apply → verify."""

    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = 512
            state_a = root / "a.bin"
            state_a.write_bytes(bytes(range(256)) * 8)  # 2048 bytes, 4 blocks
            data = bytearray(state_a.read_bytes())
            data[block : 2 * block] = b"\xee" * block
            state_b = root / "b.bin"
            state_b.write_bytes(bytes(data))

            base = snapshot_state(state_a, block_size=block)
            delta = produce_delta(base, state_b)
            self.assertEqual(sorted(delta.changed_blocks), [1])

            delta_dir = save_delta(delta, root / "delta")
            loaded = load_delta(delta_dir)
            output = apply_delta(state_a, loaded, root / "rebuilt.bin")
            self.assertTrue(verify_result(output, loaded))
            self.assertEqual(output.read_bytes(), state_b.read_bytes())
            savings = loaded.savings_estimate()
            self.assertEqual(savings["delta_size_bytes"], block)
            self.assertGreater(savings["saved_percent"], 70)


class Flow5GuestDeniedTests(unittest.TestCase):
    """Guest attempts offload → denied → audit log records it."""

    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = StructuredLogger(Path(tmp) / "audit.jsonl")
            import hypergery_ubuntu.v1.hglog as hglog

            original = hglog._default_logger
            hglog._default_logger = logger
            try:
                guest = User(id="alumno", role="Guest", assigned_labs=["asr-lab"])
                self.assertFalse(check_permission(guest, "can_use_remote_compute"))
                with self.assertRaises(PermissionDeniedError):
                    require_permission(guest, "can_use_remote_compute")
                # Audit trail captured the denial.
                denied = logger.query(category="guest", contains="DENIED")
                self.assertTrue(denied)
                self.assertIn("can_use_remote_compute", denied[-1]["message"])
                self.assertEqual(denied[-1]["details"]["allowed"], False)

                # And the orchestrator honors the same decision end to end.
                plans = OrchestratorService(settings=V1Settings()).plan(
                    hosts=hosts_pair(),
                    vms=[VmInfo(id="guest-vm", ram_mb=8192, status="running", host_id="laptop", lab_id="asr-lab")],
                    battery=battery_at(15),
                    local_host_id="laptop",
                    allow_remote=check_permission(guest, "can_use_remote_compute"),
                )
                self.assertEqual(plans[0].target_host, "laptop")
            finally:
                hglog._default_logger = original
            self.assertIsNot(get_logger(), logger)


if __name__ == "__main__":
    unittest.main()
