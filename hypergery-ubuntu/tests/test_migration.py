import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypergery_ubuntu.backend import CommandResult, PreflightItem, VmSummary
from hypergery_ubuntu.labs import LabStore
from hypergery_ubuntu.migration import (
    export_vm_package,
    generate_target_vm_identity,
    import_vm_package,
    list_migration_packages,
    migration_preflight,
    validate_vm_package,
)


DOMAIN_XML = """<domain type="kvm">
  <name>hg-source</name>
  <uuid>11111111-1111-1111-1111-111111111111</uuid>
  <metadata>
    <hg:hypergery xmlns:hg="https://hypergery.local/schema/0.1">
      <hg:managed>true</hg:managed>
      <hg:lab_id>migration-lab</hg:lab_id>
      <hg:disk_path>{disk}</hg:disk_path>
      <hg:iso_path>{iso}</hg:iso_path>
      <hg:network_id>hg-net-migration-lab</hg:network_id>
    </hg:hypergery>
  </metadata>
  <memory unit="MiB">2048</memory>
  <vcpu>2</vcpu>
  <devices>
    <disk type="file" device="disk">
      <driver name="qemu" type="qcow2"/>
      <source file="{disk}"/>
      <target dev="vda" bus="virtio"/>
    </disk>
    <disk type="file" device="cdrom">
      <driver name="qemu" type="raw"/>
      <source file="{iso}"/>
      <target dev="sda" bus="sata"/>
      <readonly/>
    </disk>
    <interface type="network">
      <mac address="52:54:00:11:22:33"/>
      <source network="hg-net-migration-lab"/>
      <model type="virtio"/>
    </interface>
    <graphics type="spice"/>
  </devices>
</domain>"""


class FakeBackend:
    def __init__(self, root: Path, *, state: str = "shut off") -> None:
        self.data_dir = root / "hypergery"
        self.vms_dir = self.data_dir / "vms"
        self.vms_dir.mkdir(parents=True)
        self.disk = root / "source.qcow2"
        self.iso = root / "installer.iso"
        self.disk.write_bytes(b"disk-data")
        self.iso.write_bytes(b"iso-data")
        self.xml = DOMAIN_XML.format(disk=self.disk, iso=self.iso)
        self.state = state
        self.defined_xml = ""
        self.updated_lab_args = None
        LabStore(self.data_dir).create_lab("Migration Lab", lab_id="migration-lab")

    def get_vm(self, name: str) -> VmSummary:
        if name != "hg-source":
            raise AssertionError(f"unexpected VM lookup: {name}")
        return VmSummary(
            name="hg-source",
            state=self.state,
            lab_id="migration-lab",
            ram_mib=2048,
            vcpus=2,
            disk_path=str(self.disk),
            iso_path=str(self.iso),
            network="hg-net-migration-lab",
            graphics="spice",
            xml=self.xml,
        )

    def list_snapshots(self, name: str):
        return []

    def virsh(self, args, *, timeout=120, check=True):
        if args[:1] == ["dominfo"]:
            return CommandResult(["virsh", *args], 1, "", "Domain not found")
        return CommandResult(["virsh", *args], 0, "", "")

    def preflight(self):
        return [PreflightItem("libvirt connection", "OK", "Connected.")]

    def ensure_network(self, lab_id: str, network_mode: str):
        return f"hg-net-{lab_id}"

    def grant_libvirt_qemu_access(self, *paths):
        return None

    def define_domain_xml(self, xml: str):
        self.defined_xml = xml

    def update_lab_for_vm(self, *args):
        self.updated_lab_args = args

    def undefine_domain(self, name: str):
        return None


class MigrationTests(unittest.TestCase):
    def test_preflight_blocks_running_vm(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp), state="running")
            result = migration_preflight(backend, "hg-source")
            self.assertFalse(result["ok"])
            self.assertFalse(result["source_will_be_deleted"])
            self.assertIn("Running VM migration is blocked", "; ".join(result["errors"]))

    def test_preflight_blocks_missing_iso_when_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp))
            backend.iso.unlink()
            result = migration_preflight(backend, "hg-source")
            self.assertFalse(result["ok"])
            self.assertIn("Attached ISO media is missing", "; ".join(result["errors"]))

            without_iso = migration_preflight(backend, "hg-source", include_iso=False)
            self.assertTrue(without_iso["ok"], without_iso)

    def test_export_package_creates_manifest_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            result = export_vm_package(backend, "hg-source", root / "nas", target_vm_name="hg-target")
            package_dir = Path(result["package_dir"])

            self.assertTrue((package_dir / "manifest.json").is_file())
            self.assertTrue((package_dir / "domain.xml").is_file())
            validation = validate_vm_package(package_dir)
            self.assertTrue(validation["ok"], validation)
            manifest = validation["manifest"]
            self.assertEqual(manifest["source_vm_name"], "hg-source")
            self.assertEqual(manifest["target_vm_name"], "hg-target")
            self.assertFalse(manifest["source_will_be_deleted"])
            self.assertEqual(len(list_migration_packages(root / "nas")), 1)

    def test_import_package_rewrites_identity_and_media_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_backend = FakeBackend(root / "source")
            export = export_vm_package(source_backend, "hg-source", root / "nas", target_vm_name="hg-target")

            target_backend = FakeBackend(root / "target")
            imported = import_vm_package(target_backend, export["package_dir"], target_vm_name="hg-target", target_lab_id="target-lab")

            self.assertTrue(imported["imported"])
            self.assertEqual(imported["target_vm_name"], "hg-target")
            self.assertIn("hg-target", target_backend.defined_xml)
            self.assertNotIn(str(source_backend.disk), target_backend.defined_xml)
            root_xml = ET.fromstring(target_backend.defined_xml)
            self.assertEqual(root_xml.findtext("name"), "hg-target")
            self.assertNotEqual(root_xml.findtext("uuid"), "11111111-1111-1111-1111-111111111111")
            self.assertEqual(target_backend.updated_lab_args[0], "target-lab")
            self.assertTrue(Path(imported["disks"][0]).is_file())

    def test_generate_target_vm_identity_changes_name_uuid_and_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp))
            identity = generate_target_vm_identity(backend.xml, "hg-target")
            root = ET.fromstring(identity["xml"])
            self.assertEqual(root.findtext("name"), "hg-target")
            self.assertNotEqual(root.findtext("uuid"), "11111111-1111-1111-1111-111111111111")
            self.assertNotEqual(root.find("./devices/interface/mac").attrib["address"], "52:54:00:11:22:33")

    def test_package_validation_reports_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            result = export_vm_package(backend, "hg-source", root / "nas")
            package_dir = Path(result["package_dir"])
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
            first_asset = next(asset for asset in manifest["assets"] if asset.get("relative_path"))
            (package_dir / first_asset["relative_path"]).write_bytes(b"changed")
            validation = validate_vm_package(package_dir)
            self.assertFalse(validation["ok"])
            self.assertIn("checksum mismatch", "; ".join(validation["errors"]))


if __name__ == "__main__":
    unittest.main()
