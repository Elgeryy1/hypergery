import json
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.templates import (
    TemplateStore,
    normalize_template_id,
    validate_lab_template,
    validate_template_id,
    validate_vm_template,
)


class TemplateIdPreviewTests(unittest.TestCase):
    def test_normalize_simple_name(self):
        self.assertEqual(normalize_template_id("Ubuntu Base"), "ubuntu-base")

    def test_normalize_with_version(self):
        self.assertEqual(normalize_template_id("HG v03 Ubuntu Template"), "hg-v03-ubuntu-template")

    def test_normalize_asr_name(self):
        self.assertEqual(normalize_template_id("HG v03 ASR Template"), "hg-v03-asr-template")

    def test_normalize_strips_leading_trailing_dashes(self):
        self.assertEqual(normalize_template_id("  lab base  "), "lab-base")

    def test_normalize_collapses_multiple_separators(self):
        self.assertEqual(normalize_template_id("a---b  c"), "a-b-c")

    def test_normalize_rejects_empty_after_clean(self):
        with self.assertRaises(HyperGeryError):
            normalize_template_id("---")

    def test_normalize_rejects_too_short_result(self):
        with self.assertRaises(HyperGeryError):
            normalize_template_id("ab")

    def test_validate_rejects_path_traversal(self):
        for bad in ("../etc/passwd", ".hidden", "bad/id", "bad\\id", "a/b"):
            with self.assertRaises(HyperGeryError, msg=bad):
                validate_template_id(bad)

    def test_validate_rejects_uppercase(self):
        with self.assertRaises(HyperGeryError):
            validate_template_id("Ubuntu-Base")

    def test_validate_rejects_too_long(self):
        with self.assertRaises(HyperGeryError):
            validate_template_id("a" * 65)

    def test_validate_accepts_valid_id(self):
        self.assertEqual(validate_template_id("ubuntu-base"), "ubuntu-base")
        self.assertEqual(validate_template_id("hg-v03-ubuntu-template"), "hg-v03-ubuntu-template")


class VmTemplateCountTests(unittest.TestCase):
    def test_vm_count_empty_lab_template(self):
        tmpl = {
            "template_id": "lab-tmpl",
            "name": "Lab",
            "description": "",
            "network_mode": "nat",
            "vms": [],
        }
        self.assertEqual(len(tmpl["vms"]), 0)

    def test_vm_count_with_vms(self):
        tmpl = {
            "template_id": "classroom",
            "name": "Classroom",
            "description": "training",
            "network_mode": "nat",
            "vms": [
                {"name": "student", "ram_mib": 2048, "vcpus": 2, "disk_gb": 20, "os_type": "linux", "display": "spice"},
                {"name": "teacher", "ram_mib": 4096, "vcpus": 4, "disk_gb": 40, "os_type": "linux", "display": "spice"},
            ],
        }
        self.assertEqual(len(tmpl["vms"]), 2)


class VmTemplateValidationTests(unittest.TestCase):
    def _valid(self, **overrides):
        base = {
            "template_id": "ubuntu-base",
            "name": "Ubuntu Base",
            "os_type": "linux",
            "ram_mib": 2048,
            "vcpus": 2,
            "disk_gb": 20,
            "network_mode": "nat",
            "display": "spice",
        }
        base.update(overrides)
        return base

    def test_validate_accepts_valid_template(self):
        tmpl = validate_vm_template(self._valid())
        self.assertEqual(tmpl["schema_version"], 1)
        self.assertEqual(tmpl["notes"], "")

    def test_validate_missing_field(self):
        with self.assertRaisesRegex(HyperGeryError, "missing"):
            validate_vm_template({"template_id": "ubuntu-base", "name": "Ubuntu Base"})

    def test_validate_bad_os_type(self):
        with self.assertRaisesRegex(HyperGeryError, "os_type"):
            validate_vm_template(self._valid(os_type="freebsd"))

    def test_validate_bad_network_mode(self):
        with self.assertRaisesRegex(HyperGeryError, "network_mode"):
            validate_vm_template(self._valid(network_mode="bridge"))

    def test_validate_bad_display(self):
        with self.assertRaisesRegex(HyperGeryError, "display"):
            validate_vm_template(self._valid(display="rdp"))

    def test_validate_zero_ram(self):
        with self.assertRaisesRegex(HyperGeryError, "positive"):
            validate_vm_template(self._valid(ram_mib=0))


class LabTemplateValidationTests(unittest.TestCase):
    def _valid(self, **overrides):
        base = {
            "template_id": "classroom",
            "name": "Classroom",
            "description": "training",
            "network_mode": "nat",
            "vms": [],
        }
        base.update(overrides)
        return base

    def test_validate_accepts_valid_template(self):
        tmpl = validate_lab_template(self._valid())
        self.assertEqual(tmpl["schema_version"], 1)

    def test_validate_missing_field(self):
        with self.assertRaisesRegex(HyperGeryError, "missing"):
            validate_lab_template({"template_id": "classroom", "name": "Classroom"})

    def test_validate_bad_network_mode(self):
        with self.assertRaisesRegex(HyperGeryError, "network_mode"):
            validate_lab_template(self._valid(network_mode="bridge"))

    def test_validate_vms_not_list(self):
        with self.assertRaisesRegex(HyperGeryError, "list"):
            validate_lab_template(self._valid(vms="not-a-list"))


class TemplateStoreOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TemplateStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_nonexistent_vm_template_raises(self):
        with self.assertRaisesRegex(HyperGeryError, "does not exist"):
            self.store.delete_vm_template("nonexistent-template")

    def test_delete_nonexistent_lab_template_raises(self):
        with self.assertRaisesRegex(HyperGeryError, "does not exist"):
            self.store.delete_lab_template("nonexistent-template")

    def test_import_invalid_vm_template(self):
        path = self.root / "bad.json"
        path.write_text('{"template_id": "bad-template"}', encoding="utf-8")
        with self.assertRaisesRegex(HyperGeryError, "missing"):
            self.store.import_vm_template(path)

    def test_import_invalid_lab_template(self):
        path = self.root / "bad-lab.json"
        path.write_text('{"template_id": "bad-lab-template"}', encoding="utf-8")
        with self.assertRaisesRegex(HyperGeryError, "missing"):
            self.store.import_lab_template(path)

    def test_import_malformed_json(self):
        path = self.root / "malformed.json"
        path.write_text("not json at all", encoding="utf-8")
        with self.assertRaises(HyperGeryError):
            self.store.import_vm_template(path)

    def test_no_overwrite_vm_template_on_import(self):
        self.store.create_vm_template("Ubuntu Base", os_type="linux", ram_mib=2048, vcpus=2, disk_gb=20)
        output = self.root / "ubuntu-base-export.json"
        self.store.export_vm_template("ubuntu-base", output)
        with self.assertRaisesRegex(HyperGeryError, "already exists"):
            self.store.import_vm_template(output)

    def test_no_overwrite_lab_template_on_import(self):
        self.store.create_lab_template("Classroom", "training")
        output = self.root / "classroom-export.json"
        self.store.export_lab_template("classroom", output)
        with self.assertRaisesRegex(HyperGeryError, "already exists"):
            self.store.import_lab_template(output)

    def test_export_import_vm_template_roundtrip(self):
        self.store.create_vm_template(
            "HG v03 Ubuntu Template",
            os_type="linux",
            ram_mib=4096,
            vcpus=2,
            disk_gb=40,
            notes="test template",
        )
        output = self.root / "hg-v03-ubuntu-template.json"
        self.store.export_vm_template("hg-v03-ubuntu-template", output)
        self.store.delete_vm_template("hg-v03-ubuntu-template")
        imported = self.store.import_vm_template(output)
        self.assertEqual(imported["template_id"], "hg-v03-ubuntu-template")
        self.assertEqual(imported["notes"], "test template")

    def test_create_and_export_import_lab_template(self):
        tmpl = self.store.create_lab_template(
            "HG v03 ASR Template",
            "Attack/Simulation/Response lab",
            "isolated",
        )
        self.assertEqual(tmpl["template_id"], "hg-v03-asr-template")
        output = self.root / "hg-v03-asr-template.json"
        self.store.export_lab_template("hg-v03-asr-template", output)
        self.store.delete_lab_template("hg-v03-asr-template")
        imported = self.store.import_lab_template(output)
        self.assertEqual(imported["template_id"], "hg-v03-asr-template")
        self.assertEqual(imported["network_mode"], "isolated")

    def test_template_id_preview_matches_test_name(self):
        tid = normalize_template_id("HG v03 Ubuntu Template")
        self.assertEqual(tid, "hg-v03-ubuntu-template")
        tid2 = normalize_template_id("HG v03 ASR Template")
        self.assertEqual(tid2, "hg-v03-asr-template")

    def test_duplicate_vm_template_raises(self):
        self.store.create_vm_template("Ubuntu Base", os_type="linux", ram_mib=2048, vcpus=2, disk_gb=20)
        with self.assertRaisesRegex(HyperGeryError, "already exists"):
            self.store.create_vm_template("Ubuntu Base", os_type="linux", ram_mib=2048, vcpus=2, disk_gb=20)

    def test_duplicate_lab_template_raises(self):
        self.store.create_lab_template("Classroom", "training")
        with self.assertRaisesRegex(HyperGeryError, "already exists"):
            self.store.create_lab_template("Classroom", "training")


if __name__ == "__main__":
    unittest.main()
