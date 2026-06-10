"""v1.3: políticas de backup NAS, Backup Verifier, snapshot branching,
tags por VM y presupuesto de lab."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu.backend import CommandResult, HyperGeryBackend, HyperGeryError, VmSummary
from hypergery_ubuntu.labs import LabStore, check_lab_budget
from hypergery_ubuntu.v1.backups import (
    BackupPolicy,
    BackupPolicyStore,
    list_policy_backups,
    new_policy,
    prune_policy_backups,
    run_due,
    run_policy,
)

from .test_migration import FakeBackend


class BackupPolicyTests(unittest.TestCase):
    def test_policy_validation(self):
        with self.assertRaises(HyperGeryError):
            new_policy("vm1", "")
        with self.assertRaises(HyperGeryError):
            new_policy("vm1", "/nas", interval_hours=0)
        with self.assertRaises(HyperGeryError):
            new_policy("vm1", "/nas", retention=0)
        with self.assertRaises(HyperGeryError):
            new_policy("../evil", "/nas")

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BackupPolicyStore(Path(tmp) / "policies.json")
            policy = store.add(new_policy("vm1", "/nas/backups"))
            self.assertEqual([p.id for p in store.list()], [policy.id])
            self.assertEqual(store.get(policy.id).vm_name, "vm1")
            self.assertTrue(store.remove(policy.id))
            self.assertEqual(store.list(), [])
            with self.assertRaises(HyperGeryError):
                store.get(policy.id)

    def test_is_due_logic(self):
        policy = new_policy("vm1", "/nas", interval_hours=24)
        self.assertTrue(policy.is_due())  # nunca ejecutada
        now = datetime.now(UTC)
        policy.last_run_at = (now - timedelta(hours=1)).isoformat()
        self.assertFalse(policy.is_due(now))
        policy.last_run_at = (now - timedelta(hours=25)).isoformat()
        self.assertTrue(policy.is_due(now))
        policy.enabled = False
        self.assertFalse(policy.is_due(now))


def _fake_package(root: Path, migration_id: str, vm_name: str, *, mtime: float | None = None) -> Path:
    package = root / "migrations" / migration_id
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps({"source_vm_name": vm_name, "migration_id": migration_id}), encoding="utf-8"
    )
    if mtime is not None:
        import os

        os.utime(package, (mtime, mtime))
    return package


class RetentionTests(unittest.TestCase):
    def test_prune_keeps_newest_and_only_own_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = new_policy("vm1", str(root), retention=2)
            base = 1_700_000_000
            old = _fake_package(root, "vm1-b1", "vm1", mtime=base)
            mid = _fake_package(root, "vm1-b2", "vm1", mtime=base + 100)
            new = _fake_package(root, "vm1-b3", "vm1", mtime=base + 200)
            other = _fake_package(root, "vm2-b1", "vm2", mtime=base)
            not_package = root / "migrations" / "loose-dir"
            not_package.mkdir()

            self.assertEqual([p.name for p in list_policy_backups(policy)], ["vm1-b3", "vm1-b2", "vm1-b1"])
            removed = prune_policy_backups(policy)
            self.assertEqual(removed, [str(old.resolve())])
            self.assertTrue(mid.exists() and new.exists())
            self.assertTrue(other.exists(), "los paquetes de otras VMs no se tocan")
            self.assertTrue(not_package.exists(), "los directorios sin manifest no se tocan")


class RunPolicyTests(unittest.TestCase):
    def test_run_policy_exports_prunes_and_updates_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            store = BackupPolicyStore(root / "policies.json")
            policy = store.add(
                BackupPolicy(id="bkp-test", vm_name="hg-source", target_dir=str(root / "nas"), retention=1)
            )
            result = run_policy(backend, policy, store)
            self.assertTrue(result["ok"], result)
            self.assertTrue(Path(result["package_dir"]).is_dir())
            saved = store.get("bkp-test")
            self.assertEqual(saved.last_result, "ok")
            self.assertTrue(saved.last_run_at)
            # Segunda ejecución: retención 1 → poda el paquete anterior.
            second = run_policy(backend, store.get("bkp-test"), store)
            self.assertTrue(second["ok"])
            self.assertEqual(second["pruned"], [str(Path(result["package_dir"]).resolve())])

    def test_run_due_skips_fresh_policies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            store = BackupPolicyStore(root / "policies.json")
            store.add(BackupPolicy(id="bkp-due", vm_name="hg-source", target_dir=str(root / "nas")))
            results = run_due(backend, store)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["ok"])
            # Justo después no toca: nada due.
            self.assertEqual(run_due(backend, store), [])

    def test_failed_export_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root, state="running")  # preflight falla con VM encendida
            store = BackupPolicyStore(root / "policies.json")
            policy = store.add(BackupPolicy(id="bkp-bad", vm_name="hg-source", target_dir=str(root / "nas")))
            result = run_policy(backend, policy, store)
            self.assertFalse(result["ok"])
            self.assertIn("error", result)
            self.assertIn("error", store.get("bkp-bad").last_result)


class _VerifyBackend:
    def __init__(self):
        self.calls = []
        self.boot_state = "running"

    def start_vm(self, name):
        self.calls.append(("start", name))

    def wait_for_state(self, name, states, *, timeout_seconds=120, interval_seconds=2.0):
        self.calls.append(("wait", name))
        return self.boot_state

    def virsh(self, args, *, timeout=120, check=True):
        self.calls.append(("virsh", tuple(args)))
        return CommandResult(["virsh", *args], 0, "", "")

    def delete_vm(self, name, *, delete_disks):
        self.calls.append(("delete", name, delete_disks))


class BackupVerifierTests(unittest.TestCase):
    def _verify(self, backend, *, valid=True, import_error=None, keep_vm=False):
        from hypergery_ubuntu.v1 import backup_verifier

        validation = {"ok": valid, "errors": [] if valid else ["broken checksum"], "manifest": {}}

        def fake_import(b, package_dir, *, target_vm_name="", target_lab_id=""):
            if import_error:
                raise HyperGeryError(import_error)
            backend.calls.append(("import", target_vm_name, target_lab_id))
            return {"vm_name": target_vm_name}

        with (
            patch.object(backup_verifier, "validate_vm_package", return_value=validation),
            patch.object(backup_verifier, "import_vm_package", side_effect=fake_import),
        ):
            return backup_verifier.verify_backup(backend, "/fake/package", keep_vm=keep_vm)

    def test_happy_path_boots_and_cleans_up(self):
        backend = _VerifyBackend()
        result = self._verify(backend)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["booted"])
        self.assertTrue(result["verified_vm"].startswith("hgtest-verify-"))
        kinds = [call[0] for call in backend.calls]
        self.assertEqual(kinds, ["import", "start", "wait", "virsh", "delete"])
        self.assertEqual(backend.calls[-1][2], True)  # delete_disks=True

    def test_boot_failure_still_cleans_up(self):
        backend = _VerifyBackend()
        backend.boot_state = "shut off"
        result = self._verify(backend)
        self.assertFalse(result["ok"])
        self.assertFalse(result["booted"])
        self.assertIn("delete", [call[0] for call in backend.calls])

    def test_invalid_package_never_imports(self):
        backend = _VerifyBackend()
        result = self._verify(backend, valid=False)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checksums_ok"])
        self.assertEqual(backend.calls, [])

    def test_import_failure_reports_and_no_cleanup_needed(self):
        backend = _VerifyBackend()
        result = self._verify(backend, import_error="target exists")
        self.assertFalse(result["ok"])
        self.assertEqual([call[0] for call in backend.calls], [])

    def test_keep_vm_skips_cleanup(self):
        backend = _VerifyBackend()
        result = self._verify(backend, keep_vm=True)
        self.assertTrue(result["ok"])
        self.assertNotIn("delete", [call[0] for call in backend.calls])

    def test_cleanup_refuses_foreign_vm_names(self):
        from hypergery_ubuntu.v1.backup_verifier import _cleanup_verify_vm

        with self.assertRaises(HyperGeryError):
            _cleanup_verify_vm(_VerifyBackend(), "ubuntu-prod", lambda *a: None)


class SnapshotBranchingTests(unittest.TestCase):
    class _SnapBackend(HyperGeryBackend):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.snapshots = ["base", "clean-install"]

        def virsh(self, args, *, timeout=120, check=True):
            self.calls.append(list(args))
            if args[0] == "snapshot-list":
                return CommandResult(["virsh", *args], 0, "\n".join(self.snapshots) + "\n", "")
            return CommandResult(["virsh", *args], 0, "", "")

    def test_branch_reverts_then_creates(self):
        backend = self._SnapBackend()
        backend.branch_snapshot("vm1", "clean-install", "exp-1")
        ops = [call[0] for call in backend.calls]
        self.assertEqual(ops, ["snapshot-list", "snapshot-revert", "snapshot-create-as"])

    def test_branch_requires_existing_source(self):
        backend = self._SnapBackend()
        with self.assertRaises(HyperGeryError):
            backend.branch_snapshot("vm1", "no-such-snap", "exp-1")

    def test_branch_never_overwrites_target(self):
        backend = self._SnapBackend()
        with self.assertRaises(HyperGeryError):
            backend.branch_snapshot("vm1", "base", "clean-install")


class VmTagsAndBudgetTests(unittest.TestCase):
    def _store(self, tmp: str) -> LabStore:
        return LabStore(Path(tmp) / "hypergery")

    def test_vm_tags_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.create_lab("Lab", lab_id="tags-lab")
            lab = store.set_vm_tags("tags-lab", "dc01", ["windows", "Produccion", "windows", " "])
            self.assertEqual(lab["vm_tags"], {"dc01": ["Produccion", "windows"]})
            lab = store.set_vm_tags("tags-lab", "dc01", [])
            self.assertEqual(lab["vm_tags"], {})

    def test_tags_survive_manifest_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.create_lab("Lab", lab_id="tags-lab")
            store.set_vm_tags("tags-lab", "dc01", ["x"])
            self.assertEqual(store.get_lab("tags-lab")["vm_tags"], {"dc01": ["x"]})

    def test_budget_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.create_lab("Lab", lab_id="b-lab")
            lab = store.set_budget("b-lab", max_ram_mib=4096, max_vms=2)
            self.assertEqual(lab["budget"], {"max_ram_mib": 4096, "max_vms": 2})
            with self.assertRaises(HyperGeryError):
                store.set_budget("b-lab", max_ram_mib=-1)

    def test_check_lab_budget_reports_violations(self):
        manifest = {"lab_id": "b-lab", "budget": {"max_ram_mib": 4096, "max_vcpus": 4, "max_vms": 2}}
        vms = [
            VmSummary(name="a", state="running", lab_id="b-lab", ram_mib=2048, vcpus=2),
            VmSummary(name="b", state="running", lab_id="b-lab", ram_mib=2048, vcpus=2),
            VmSummary(name="c", state="shut off", lab_id="b-lab", ram_mib=1024, vcpus=1),
            VmSummary(name="other", state="running", lab_id="z-lab", ram_mib=8192, vcpus=8),
        ]
        violations = check_lab_budget(manifest, vms)
        self.assertEqual(len(violations), 3, violations)
        self.assertTrue(any("max_vms=2" in v for v in violations))
        self.assertTrue(any("max_ram_mib=4096" in v for v in violations))
        self.assertTrue(any("max_vcpus=4" in v for v in violations))
        self.assertEqual(check_lab_budget({"lab_id": "b-lab", "budget": {}}, vms), [])


if __name__ == "__main__":
    unittest.main()
