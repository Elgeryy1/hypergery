import json
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.labs import (
    LabStore,
    allocate_lab_subnet,
    generate_lab_bridge_name,
    normalize_lab_id,
    validate_lab_id,
)
from hypergery_ubuntu.templates import TemplateStore


class LabStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LabStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lab_id_valid_and_invalid(self):
        self.assertEqual(validate_lab_id("security-lab"), "security-lab")
        for value in ("ab", "Security", "security lab", "../bad", ".hidden", "default", "root", "bad_name"):
            with self.assertRaises(HyperGeryError, msg=value):
                validate_lab_id(value)

    def test_normalize_lab_id(self):
        self.assertEqual(normalize_lab_id("Security Lab 01"), "security-lab-01")

    def test_create_and_list_labs(self):
        lab = self.store.create_lab("Security Lab", "training", "isolated")
        self.assertEqual(lab["schema_version"], 2)
        self.assertEqual(lab["lab_id"], "security-lab")
        self.assertEqual(lab["network_mode"], "isolated")
        self.assertIn("subnet", lab)
        self.assertEqual([item["lab_id"] for item in self.store.list_labs()], ["security-lab"])

    def test_rename_lab(self):
        self.store.create_lab("Security Lab")
        renamed = self.store.rename_lab("security-lab", "Blue Team Lab")
        self.assertEqual(renamed["lab_id"], "blue-team-lab")
        self.assertFalse((self.root / "labs" / "security-lab").exists())
        self.assertTrue((self.root / "labs" / "blue-team-lab" / "lab.json").exists())

    def test_delete_lab_does_not_delete_vms_by_default(self):
        lab = self.store.create_lab("Security Lab")
        lab["vms"].append("vm1")
        self.store.write_lab(lab)
        self.store.delete_lab("security-lab")
        self.assertFalse((self.root / "labs" / "security-lab").exists())

    def test_delete_lab_with_vms_requires_callback(self):
        lab = self.store.create_lab("Security Lab")
        lab["vms"].append("vm1")
        self.store.write_lab(lab)
        with self.assertRaisesRegex(HyperGeryError, "requires a VM deletion"):
            self.store.delete_lab("security-lab", delete_vms=True)

    def test_migrate_old_lab(self):
        path = self.root / "labs" / "old_lab" / "lab.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "lab_id": "old_lab",
                    "name": "Old Lab",
                    "network_id": "hg-net-old-lab",
                    "vms": ["vm1"],
                    "disks": ["/private/vm1.qcow2"],
                    "iso_references": ["/private/install.iso"],
                }
            ),
            encoding="utf-8",
        )
        lab = self.store.list_labs()[0]
        self.assertEqual(lab["schema_version"], 2)
        self.assertEqual(lab["lab_id"], "old-lab")
        self.assertEqual(lab["vms"], ["vm1"])
        self.assertEqual(lab["disks"], ["/private/vm1.qcow2"])
        self.assertIn("bridge_name", lab)

    def test_export_import_lab_portable(self):
        lab = self.store.create_lab("Security Lab")
        lab["disks"].append("/private/vm.qcow2")
        lab["iso_references"].append("/private/install.iso")
        self.store.write_lab(lab)
        output = self.root / "exported-lab.json"
        self.store.export_lab("security-lab", output)
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exported["disks"], [])
        self.assertEqual(exported["iso_references"], [])
        self.store.delete_lab("security-lab")
        imported = self.store.import_lab(output, new_lab_id="imported-lab")
        self.assertEqual(imported["lab_id"], "imported-lab")

    def test_import_invalid_lab_fails_clearly(self):
        path = self.root / "invalid.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(HyperGeryError, "missing lab_id"):
            self.store.import_lab(path)

    def test_bridge_and_subnet_rules(self):
        bridge = generate_lab_bridge_name("security-lab")
        self.assertLessEqual(len(bridge), 15)
        self.assertNotEqual(bridge, "virbr0")
        subnet = allocate_lab_subnet("security-lab", {"192.168.122.0/24"})
        self.assertNotEqual(subnet, "192.168.122.0/24")
        second = allocate_lab_subnet("security-lab", {subnet})
        self.assertNotEqual(second, subnet)

    def test_duplicate_lab_blocks_running_vm_clone(self):
        lab = self.store.create_lab("Security Lab")
        lab["vms"].append("vm1")
        self.store.write_lab(lab)
        store = LabStore(self.root, clone_vm_callback=lambda *_args: None, vm_state_callback=lambda _name: "running")
        with self.assertRaisesRegex(HyperGeryError, "running VM"):
            store.duplicate_lab("security-lab", "Copy Lab", clone_vms=True)


class TemplateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TemplateStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_list_delete_vm_template(self):
        template = self.store.create_vm_template("Ubuntu Base", os_type="linux", ram_mib=2048, vcpus=2, disk_gb=20)
        self.assertEqual(template["template_id"], "ubuntu-base")
        self.assertEqual([item["template_id"] for item in self.store.list_vm_templates()], ["ubuntu-base"])
        self.assertEqual(self.store.get_vm_template("ubuntu-base")["ram_mib"], 2048)
        self.store.delete_vm_template("ubuntu-base")
        self.assertEqual(self.store.list_vm_templates(), [])

    def test_create_list_delete_lab_template(self):
        template = self.store.create_lab_template(
            "Classroom",
            "training",
            "nat",
            [
                {
                    "name": "student",
                    "template_id": "ubuntu-base",
                    "ram_mib": 2048,
                    "vcpus": 2,
                    "disk_gb": 20,
                    "os_type": "linux",
                    "display": "spice",
                }
            ],
        )
        self.assertEqual(template["template_id"], "classroom")
        self.assertEqual([item["template_id"] for item in self.store.list_lab_templates()], ["classroom"])
        self.store.delete_lab_template("classroom")
        self.assertEqual(self.store.list_lab_templates(), [])

    def test_import_invalid_lab_template_fails_clearly(self):
        path = self.root / "invalid-template.json"
        path.write_text(json.dumps({"template_id": "bad-template"}), encoding="utf-8")
        with self.assertRaisesRegex(HyperGeryError, "missing"):
            self.store.import_lab_template(path)

    def test_export_import_lab_template(self):
        self.store.create_lab_template("Classroom", "training")
        output = self.root / "classroom-export.json"
        self.store.export_lab_template("classroom", output)
        self.store.delete_lab_template("classroom")
        imported = self.store.import_lab_template(output)
        self.assertEqual(imported["template_id"], "classroom")


if __name__ == "__main__":
    unittest.main()
