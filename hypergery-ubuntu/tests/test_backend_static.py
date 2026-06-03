import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu.backend import CommandResult, HG_NS, HyperGeryBackend, HyperGeryError, VmSummary, validate_vm_name, xdg_data_home


class BackendStaticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = os.environ.get("XDG_DATA_HOME")
        self.old_state = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_DATA_HOME"] = str(Path(self.temp.name) / "data")
        os.environ["XDG_STATE_HOME"] = str(Path(self.temp.name) / "state")
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
        self.temp.cleanup()

    def test_validate_vm_name_rejects_traversal(self):
        with self.assertRaises(HyperGeryError):
            validate_vm_name("../bad")
        with self.assertRaises(HyperGeryError):
            validate_vm_name("bad/name")
        self.assertEqual(validate_vm_name("ubuntu_24.04-lab"), "ubuntu_24.04-lab")

    def test_snap_private_xdg_data_home_is_not_used_for_vm_storage_default(self):
        old_snap = os.environ.get("SNAP")
        old_xdg = os.environ.get("XDG_DATA_HOME")
        old_override = os.environ.get("HYPERGERY_DATA_HOME")
        try:
            os.environ["SNAP"] = "/snap/code/234"
            os.environ["XDG_DATA_HOME"] = str(Path.home() / "snap" / "code" / "234" / ".local" / "share")
            os.environ.pop("HYPERGERY_DATA_HOME", None)
            self.assertEqual(xdg_data_home(), Path.home() / ".local" / "share" / "hypergery")
        finally:
            if old_snap is None:
                os.environ.pop("SNAP", None)
            else:
                os.environ["SNAP"] = old_snap
            if old_xdg is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = old_xdg
            if old_override is None:
                os.environ.pop("HYPERGERY_DATA_HOME", None)
            else:
                os.environ["HYPERGERY_DATA_HOME"] = old_override

    def test_external_tool_env_removes_snap_viewer_contamination(self):
        old_values = {key: os.environ.get(key) for key in ("SNAP", "SNAP_NAME", "GTK_PATH", "XDG_DATA_DIRS")}
        try:
            os.environ["SNAP"] = "/snap/code/234"
            os.environ["SNAP_NAME"] = "code"
            os.environ["GTK_PATH"] = "/snap/code/234/usr/lib/x86_64-linux-gnu/gtk-3.0"
            os.environ["XDG_DATA_DIRS"] = "/snap/code/234/usr/share:/usr/share"
            env = self.backend.external_tool_env()
            self.assertNotIn("SNAP", env)
            self.assertNotIn("SNAP_NAME", env)
            self.assertNotIn("GTK_PATH", env)
            self.assertEqual(env["XDG_DATA_DIRS"], "/usr/share")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_default_lab_manifest_shape(self):
        manifest = self.backend.ensure_default_lab()
        self.assertEqual(manifest["lab_id"], "default-lab")
        self.assertEqual(manifest["name"], "Default Lab")
        self.assertIn("network_id", manifest)
        self.assertIsInstance(manifest["vms"], list)
        self.assertIsInstance(manifest["disks"], list)
        self.assertIsInstance(manifest["iso_references"], list)

    def test_network_xml_uses_requested_modes(self):
        nat = self.backend.network_xml("default-lab", "nat")
        isolated = self.backend.network_xml("default-lab", "isolated")
        self.assertIn("<forward mode='nat'/>", nat)
        self.assertNotIn("<forward mode='nat'/>", isolated)
        self.assertIn("<name>hg-net-default-lab</name>", nat)
        self.assertIn("<name>hg-net-default-lab-isolated</name>", isolated)

    def test_hypergery_network_xml_never_uses_virbr0(self):
        for lab_id in ("default-lab", "lab1", "security_lab", "a-very-long-lab-name"):
            for mode in ("nat", "isolated"):
                xml = self.backend.network_xml(lab_id, mode)
                root = ET.fromstring(xml)
                self.assertNotEqual(root.find("bridge").attrib["name"], "virbr0")

    def test_hypergery_bridge_names_are_valid_linux_ifnames(self):
        for lab_id in ("default-lab", "lab1", "security_lab", "a-very-long-lab-name"):
            for mode in ("nat", "isolated"):
                bridge = self.backend.bridge_name(lab_id, mode)
                self.assertLessEqual(len(bridge), 15)
                self.assertRegex(bridge, r"^hgbr[A-Fa-f0-9]+$")
                self.assertNotEqual(bridge, "virbr0")

    def test_hypergery_networks_do_not_use_default_libvirt_subnet(self):
        for lab_id in ("default-lab", "lab1", "security_lab", "a-very-long-lab-name"):
            for mode in ("nat", "isolated"):
                ip_address = self.backend.network_ip_address(lab_id, mode)
                self.assertNotEqual(ip_address, "192.168.122.1")
                self.assertFalse(ip_address.startswith("192.168.122."))

    def test_reconcile_recycles_hypergery_network_using_virbr0(self):
        calls = []

        class FakeBackend(HyperGeryBackend):
            def virsh(self, args, *, timeout=120, check=True):
                calls.append(args)
                if args[0] == "net-dumpxml":
                    return CommandResult(["virsh", *args], 0, "<network><name>hg-net-default-lab</name><bridge name='virbr0'/></network>", "")
                if args[0] == "net-info":
                    return CommandResult(["virsh", *args], 0, "Active:      yes\n", "")
                return CommandResult(["virsh", *args], 0, "", "")

        fake = FakeBackend()
        fake.reconcile_existing_network(
            "hg-net-default-lab",
            fake.bridge_name("default-lab", "nat"),
            fake.network_ip_address("default-lab", "nat"),
        )
        self.assertIn(["net-destroy", "hg-net-default-lab"], calls)
        self.assertIn(["net-undefine", "hg-net-default-lab"], calls)

    def test_reconcile_recycles_hypergery_network_using_default_libvirt_subnet(self):
        calls = []

        class FakeBackend(HyperGeryBackend):
            def virsh(self, args, *, timeout=120, check=True):
                calls.append(args)
                if args[0] == "net-dumpxml":
                    return CommandResult(
                        ["virsh", *args],
                        0,
                        "<network><name>hg-net-default-lab</name><bridge name='hgbr667618a'/><ip address='192.168.122.1'/></network>",
                        "",
                    )
                if args[0] == "net-info":
                    return CommandResult(["virsh", *args], 0, "Active:      no\n", "")
                return CommandResult(["virsh", *args], 0, "", "")

        fake = FakeBackend()
        fake.reconcile_existing_network(
            "hg-net-default-lab",
            fake.bridge_name("default-lab", "nat"),
            fake.network_ip_address("default-lab", "nat"),
        )
        self.assertNotIn(["net-destroy", "hg-net-default-lab"], calls)
        self.assertIn(["net-undefine", "hg-net-default-lab"], calls)

    def test_recycle_refuses_non_hypergery_network(self):
        with self.assertRaises(HyperGeryError):
            self.backend.recycle_hypergery_network("default", "must not touch default network")

    def test_domain_xml_contains_real_libvirt_devices_and_metadata(self):
        xml = self.backend.domain_xml(
            name="ubuntu2404",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=4096,
            vcpus=2,
            disk_path="/tmp/ubuntu2404.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
        )
        root = ET.fromstring(xml)
        self.assertEqual(root.findtext("name"), "ubuntu2404")
        self.assertEqual(root.findtext("memory"), "4096")
        self.assertEqual(root.findtext("vcpu"), "2")
        self.assertEqual(root.find(f"./metadata/{{{HG_NS}}}hypergery/{{{HG_NS}}}managed").text, "true")
        disks = root.findall("./devices/disk")
        self.assertEqual(len(disks), 2)
        self.assertEqual(root.find("./devices/interface/source").attrib["network"], "hg-net-default-lab")
        self.assertEqual(root.find("./devices/graphics").attrib["type"], "spice")

    def test_domain_xml_uses_os_boot_without_device_boot_order(self):
        xml = self.backend.domain_xml(
            name="ubuntu2404",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=4096,
            vcpus=2,
            disk_path="/tmp/ubuntu2404.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
        )
        root = ET.fromstring(xml)
        self.assertGreaterEqual(len(root.findall("./os/boot")), 2)
        self.assertEqual(root.findall("./devices/disk/boot"), [])

    def test_domain_xml_can_use_vnc_without_spice_channel(self):
        xml = self.backend.domain_xml(
            name="ubuntu2404",
            iso_path="/isos/ubuntu.iso",
            os_type="Linux",
            ram_mib=4096,
            vcpus=2,
            disk_path="/tmp/ubuntu2404.qcow2",
            network_id="hg-net-default-lab",
            lab_id="default-lab",
            display_mode="vnc",
        )
        root = ET.fromstring(xml)
        self.assertEqual(root.find("./devices/graphics").attrib["type"], "vnc")
        self.assertEqual(root.findall("./devices/channel"), [])

    def test_manifest_disk_paths_records_custom_disk_ownership(self):
        disk = Path(self.temp.name) / "custom" / "vm.qcow2"
        self.backend.update_lab_for_vm("default-lab", "vm", str(disk), "/isos/linux.iso", "hg-net-default-lab")
        self.assertIn(disk.resolve(), self.backend.manifest_disk_paths())

    def test_delete_vm_does_not_delete_disk_when_undefine_fails(self):
        disk_dir = self.backend.vms_dir / "broken-delete"
        disk_dir.mkdir(parents=True)
        disk = disk_dir / "broken-delete.qcow2"
        disk.write_text("qcow2-placeholder", encoding="utf-8")

        class FakeBackend(HyperGeryBackend):
            def get_vm(self, name):
                return VmSummary(name=name, state="shut off", lab_id="default-lab", disk_path=str(disk))

            def virsh(self, args, *, timeout=120, check=True):
                if args[0] == "undefine":
                    return CommandResult(["virsh", *args], 1, "", "undefine failed")
                return CommandResult(["virsh", *args], 0, "", "")

        fake = FakeBackend()
        with self.assertRaises(HyperGeryError):
            fake.delete_vm("broken-delete", delete_disks=True)
        self.assertTrue(disk.exists())

    def test_delete_vm_deletes_manifest_owned_custom_disk_after_undefine(self):
        custom_dir = Path(self.temp.name) / "custom-disks"
        custom_dir.mkdir()
        disk = custom_dir / "custom.qcow2"
        disk.write_text("qcow2-placeholder", encoding="utf-8")
        self.backend.update_lab_for_vm("default-lab", "custom-vm", str(disk), "/isos/linux.iso", "hg-net-default-lab")

        class FakeBackend(HyperGeryBackend):
            def get_vm(self, name):
                return VmSummary(name=name, state="shut off", lab_id="default-lab", disk_path=str(disk))

            def virsh(self, args, *, timeout=120, check=True):
                return CommandResult(["virsh", *args], 0, "", "")

        fake = FakeBackend()
        fake.delete_vm("custom-vm", delete_disks=True)
        self.assertFalse(disk.exists())

    def test_wait_for_state_returns_when_target_state_seen(self):
        class FakeBackend(HyperGeryBackend):
            def __init__(self):
                super().__init__()
                self.states = ["paused", "running"]

            def vm_state(self, name):
                return self.states.pop(0)

        fake = FakeBackend()
        self.assertEqual(fake.wait_for_state("vm1", {"running"}, timeout_seconds=2, interval_seconds=0), "running")

    def test_list_vms_errors_when_virsh_is_missing(self):
        with patch("hypergery_ubuntu.backend.shutil.which", return_value=None):
            with self.assertRaises(HyperGeryError):
                self.backend.list_vms()

    def test_parse_bad_memory_and_vcpu_values_without_crashing(self):
        xml = f"""<domain type="kvm">
  <name>bad-values</name>
  <metadata>
    <hg:hypergery xmlns:hg="{HG_NS}">
      <hg:managed>true</hg:managed>
      <hg:lab_id>default-lab</hg:lab_id>
    </hg:hypergery>
  </metadata>
  <memory unit="MiB">not-a-number</memory>
  <vcpu>also-bad</vcpu>
  <devices/>
</domain>"""

        class FakeBackend(HyperGeryBackend):
            def virsh(self, args, *, timeout=120, check=True):
                if args[0] == "dumpxml":
                    return CommandResult(["virsh", *args], 0, xml, "")
                if args[0] == "domstate":
                    return CommandResult(["virsh", *args], 0, "shut off\n", "")
                return CommandResult(["virsh", *args], 0, "", "")

        vm = FakeBackend().get_vm("bad-values")
        self.assertIsNone(vm.ram_mib)
        self.assertIsNone(vm.vcpus)

    def test_update_settings_creates_missing_graphics_and_network_nodes(self):
        source_xml = f"""<domain type="kvm">
  <name>minimal</name>
  <metadata>
    <hg:hypergery xmlns:hg="{HG_NS}">
      <hg:managed>true</hg:managed>
      <hg:lab_id>default-lab</hg:lab_id>
    </hg:hypergery>
  </metadata>
  <memory unit="MiB">1024</memory>
  <currentMemory unit="MiB">1024</currentMemory>
  <vcpu>1</vcpu>
  <devices/>
</domain>"""

        class FakeBackend(HyperGeryBackend):
            def __init__(self):
                super().__init__()
                self.defined_xml = ""

            def get_vm(self, name):
                return VmSummary(name=name, state="shut off", lab_id="default-lab", xml=source_xml)

            def ensure_network(self, lab_id, network_mode):
                return "hg-net-new-lab"

            def define_domain_xml(self, xml):
                self.defined_xml = xml

        fake = FakeBackend()
        fake.update_settings(
            "minimal",
            ram_mib=2048,
            vcpus=2,
            boot_iso="",
            network_mode="nat",
            display_mode="vnc",
            lab_id="new-lab",
        )
        root = ET.fromstring(fake.defined_xml)
        self.assertEqual(root.find("./devices/graphics").attrib["type"], "vnc")
        self.assertEqual(root.find("./devices/interface/source").attrib["network"], "hg-net-new-lab")
        self.assertEqual(root.findtext("memory"), "2048")
        self.assertEqual(root.findtext("vcpu"), "2")


if __name__ == "__main__":
    unittest.main()
