import json
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.v1.errors import HyperGeryError, LabValidationError, NasUnavailableError
from hypergery_ubuntu.v1.nas import NasService
from hypergery_ubuntu.v1.settings import V1Settings


def lab_manifest(lab_id="asr-lab", **overrides):
    base = {
        "lab_id": lab_id,
        "name": "ASR Lab",
        "subject": "ASR",
        "subnet": "192.168.30.0/24",
        "vms": ["server-1"],
        "vm_roles": {"server-1": "server"},
    }
    base.update(overrides)
    return base


class NasServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "nas"
        self.root.mkdir()
        self.service = NasService(self.root, settings=V1Settings())

    def tearDown(self):
        self.tmp.cleanup()

    def vms_info(self, disk: Path | None = None):
        vm = {"name": "server-1", "ram_mb": 2048, "status": "shut off"}
        if disk is not None:
            vm["disk_path"] = str(disk)
        return [vm]

    def test_health_reports_writable_root(self):
        health = self.service.health()
        self.assertTrue(health["ok"])
        self.assertTrue(health["writable"])
        self.assertGreater(health["free_mib"], 0)
        self.assertIsNone(health["last_commit"])
        # The dry-run probe file is removed.
        self.assertEqual([item.name for item in self.root.iterdir()], [])

    def test_health_missing_root(self):
        service = NasService(self.root / "missing")
        health = service.health()
        self.assertFalse(health["ok"])
        self.assertFalse(health["exists"])

    def test_commit_dry_run_writes_nothing(self):
        result = self.service.commit_lab("asr-lab", lab=lab_manifest(), vms_info=self.vms_info())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["ok"])
        self.assertEqual({f["path"] for f in result["files"]}, {"lab_manifest.json", "vms/server-1.json"})
        self.assertGreater(result["total_size_bytes"], 0)
        self.assertFalse((self.root / "labs-commits").exists())

    def test_commit_real_packages_and_verifies(self):
        disk = Path(self.tmp.name) / "server-1.qcow2"
        disk.write_bytes(b"\x42" * 4096)
        result = self.service.commit_lab(
            "asr-lab", lab=lab_manifest(), vms_info=self.vms_info(disk), include_disks=True, dry_run=False
        )
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["verified"])
        commit_dir = self.root / "labs-commits" / "asr-lab" / result["commit_id"]
        self.assertTrue((commit_dir / "manifest.json").is_file())
        self.assertTrue((commit_dir / "lab_manifest.json").is_file())
        self.assertTrue((commit_dir / "vms" / "server-1.json").is_file())
        self.assertTrue((commit_dir / "disks" / "server-1.qcow2").is_file())
        self.assertTrue((commit_dir / "checksums.sha256").is_file())
        # Source disk untouched.
        self.assertEqual(disk.stat().st_size, 4096)
        commits = self.service.list_commits("asr-lab")
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["commit_id"], result["commit_id"])
        self.assertTrue(self.service.health()["last_commit"])

    def test_commit_validates_lab_first(self):
        with self.assertRaises(LabValidationError):
            self.service.commit_lab("asr-lab", lab=lab_manifest(subject="MAGIC"), dry_run=False)
        with self.assertRaises(LabValidationError):
            self.service.commit_lab(
                "asr-lab",
                lab=lab_manifest(),
                existing_labs=[lab_manifest(lab_id="par-lab")],  # same subnet → conflict
                dry_run=False,
            )

    def test_commit_to_unavailable_nas_raises(self):
        service = NasService(self.root / "missing")
        with self.assertRaises(NasUnavailableError):
            service.commit_lab("asr-lab", lab=lab_manifest(), dry_run=False)
        # Dry-run still works without the NAS (plan only).
        plan = service.commit_lab("asr-lab", lab=lab_manifest(), dry_run=True)
        self.assertTrue(plan["dry_run"])

    def test_verify_detects_corruption(self):
        result = self.service.commit_lab("asr-lab", lab=lab_manifest(), vms_info=self.vms_info(), dry_run=False)
        commit_dir = self.root / "labs-commits" / "asr-lab" / result["commit_id"]
        (commit_dir / "lab_manifest.json").write_text("{tampered}", encoding="utf-8")
        verification = self.service.verify_commit("asr-lab", result["commit_id"])
        self.assertFalse(verification["ok"])
        self.assertTrue(any("Checksum mismatch" in error for error in verification["errors"]))

    def test_restore_dry_run_and_real(self):
        result = self.service.commit_lab("asr-lab", lab=lab_manifest(), vms_info=self.vms_info(), dry_run=False)
        destination = Path(self.tmp.name) / "restore"
        dry = self.service.restore_commit("asr-lab", result["commit_id"], destination)
        self.assertTrue(dry["dry_run"])
        self.assertFalse(destination.exists())
        real = self.service.restore_commit("asr-lab", result["commit_id"], destination, dry_run=False)
        restored = Path(real["destination"])
        self.assertTrue((restored / "lab_manifest.json").is_file())
        data = json.loads((restored / "lab_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["lab_id"], "asr-lab")
        # Restores never overwrite an existing destination.
        with self.assertRaises(HyperGeryError):
            self.service.restore_commit("asr-lab", result["commit_id"], destination, dry_run=False)

    def test_restore_refuses_corrupt_commit(self):
        result = self.service.commit_lab("asr-lab", lab=lab_manifest(), dry_run=False)
        commit_dir = self.root / "labs-commits" / "asr-lab" / result["commit_id"]
        (commit_dir / "lab_manifest.json").write_bytes(b"corrupted")
        with self.assertRaises(HyperGeryError):
            self.service.restore_commit("asr-lab", result["commit_id"], Path(self.tmp.name) / "x", dry_run=False)

    def test_restore_missing_commit_raises(self):
        with self.assertRaises(HyperGeryError):
            self.service.restore_commit("asr-lab", "commit-ghost", Path(self.tmp.name) / "x")


if __name__ == "__main__":
    unittest.main()
