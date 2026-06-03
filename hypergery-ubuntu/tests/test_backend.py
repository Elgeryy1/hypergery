import os
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.backend import HG_NS, HyperGeryBackend, HyperGeryError, validate_vm_name


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = os.environ.get("XDG_DATA_HOME")
        self.old_state = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_DATA_HOME"] = str(Path(self.tmp.name) / "data")
        os.environ["XDG_STATE_HOME"] = str(Path(self.tmp.name) / "state")
        self.backend = HyperGeryBackend()

    def tearDown(self):
        if self.old_data is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self.old_data
        if self.old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old_state
        self.tmp.cleanup()

    def test_default_lab_manifest(self):
        lab = self.backend.load_labs()[0]
        self.assertEqual(lab["lab_id"], "default-lab")
        self.assertEqual(lab["network_id"], "hg-net-default-lab")
        self.assertTrue((self.backend.labs_dir / "default-lab" / "lab.json").exists())

    def test_rejects_unsafe_names(self):
        for value in ("../bad", "bad/name", "bad\\name", "", ".bad"):
            with self.assertRaises(HyperGeryError):
                validate_vm_name(value)

    def test_domain_xml_contains_real_devices_and_metadata(self):
        xml = self.backend.domain_xml(
            name="ubuntu-test",
            iso_path="/tmp/ubuntu.iso",
            os_type="Linux",
            ram_mib=4096,
            vcpus=2,
            disk_path="/tmp/ubuntu-test.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
        )
        self.assertIn(HG_NS, xml)
        self.assertIn("ubuntu-test.qcow2", xml)
        self.assertIn("spice", xml)
        self.assertIn("hg-net-default-lab", xml)

    def test_network_xml_modes(self):
        nat = self.backend.network_xml("default-lab", "nat")
        isolated = self.backend.network_xml("lab1", "isolated")
        self.assertIn("<forward mode='nat'/>", nat)
        self.assertNotIn("<forward mode='nat'/>", isolated)
        self.assertIn("<name>hg-net-lab1-isolated</name>", isolated)

    def test_move_vm_between_labs_updates_manifests(self):
        self.backend.update_lab_for_vm(
            "default-lab",
            "ubuntu-test",
            "/tmp/ubuntu-test.qcow2",
            "/tmp/ubuntu.iso",
            "hg-net-default-lab",
        )
        self.backend.move_vm_to_lab(
            "default-lab",
            "lab-two",
            "ubuntu-test",
            "/tmp/ubuntu-test.qcow2",
            "/tmp/ubuntu.iso",
            "hg-net-lab-two",
        )
        default_lab = self.backend.ensure_lab("default-lab", "Default Lab")
        lab_two = self.backend.ensure_lab("lab-two", "lab-two")
        self.assertNotIn("ubuntu-test", default_lab["vms"])
        self.assertIn("ubuntu-test", lab_two["vms"])
        self.assertEqual(lab_two["network_id"], "hg-net-lab-two")

    def test_domain_xml_supports_vnc_display_mode(self):
        xml = self.backend.domain_xml(
            name="debian-test",
            iso_path="/tmp/debian.iso",
            os_type="Linux",
            ram_mib=2048,
            vcpus=1,
            disk_path="/tmp/debian-test.qcow2",
            network_id="hg-net-lab-two",
            lab_id="lab-two",
            display_mode="vnc",
        )
        self.assertIn('type="vnc"', xml)
        self.assertNotIn("spicevmc", xml)


if __name__ == "__main__":
    unittest.main()
