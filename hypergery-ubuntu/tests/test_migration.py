import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypergery_ubuntu.backend import CommandResult, PreflightItem, VmSummary
from hypergery_ubuntu.labs import LabStore
from hypergery_ubuntu.migration import (
    create_remote_import_command,
    export_vm_package,
    generate_target_vm_identity,
    import_vm_package,
    list_migration_packages,
    migration_preflight,
    poll_remote_migration_status,
    start_remote_migration,
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


class FakeRegistryClient:
    def __init__(self):
        self.migrations = {}
        self.commands = {}
        self.created_commands = []
        self.hosts = {
            "target": {
                "host_id": "target",
                "status": "online",
                "kvm_ok": True,
                "libvirt_ok": True,
            }
        }

    def get_host(self, host_id):
        return self.hosts[host_id]

    def create_command(self, target_host_id, command_type, payload):
        command = {
            "command_id": f"cmd-{len(self.commands) + 1}",
            "target_host_id": target_host_id,
            "command_type": command_type,
            "payload": payload,
            "status": "pending",
            "result": {},
        }
        self.commands[command["command_id"]] = command
        self.created_commands.append(command)
        return command

    def update_migration_status(self, migration_id, payload):
        current = self.migrations.get(migration_id, {})
        updated = {**current, **payload, "migration_id": migration_id}
        self.migrations[migration_id] = updated
        return updated

    def migration(self, migration_id):
        return self.migrations[migration_id]

    def command(self, command_id):
        return self.commands[command_id]


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

    def test_create_remote_import_command_queues_import_and_waiting_status(self):
        client = FakeRegistryClient()
        command = create_remote_import_command(
            client,
            migration_id="mig-1",
            source_host_id="source",
            target_host_id="target",
            source_vm_name="hg-source",
            target_vm_name="hg-target",
            package_dir="/mnt/hypergery-nas/migrations/mig-1",
            start_after_import=True,
        )
        self.assertEqual(command["command_type"], "import_vm_package")
        self.assertEqual(command["payload"]["target_vm_name"], "hg-target")
        self.assertTrue(command["payload"]["start_after_import"])
        self.assertEqual(client.migrations["mig-1"]["status"], "waiting_target")

    def test_start_remote_migration_packages_and_never_deletes_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            client = FakeRegistryClient()
            result = start_remote_migration(
                backend,
                client,
                "hg-source",
                root / "nas",
                source_host_id="source",
                target_host_id="target",
                target_vm_name="hg-target",
            )
            self.assertFalse(result["source_will_be_deleted"])
            self.assertTrue(Path(result["package_dir"]).is_dir())
            self.assertEqual(client.created_commands[0]["command_type"], "import_vm_package")
            manifest = json.loads((Path(result["package_dir"]) / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["source_will_be_deleted"])
            self.assertEqual(manifest["migration_id"], result["migration_id"])

    def test_poll_remote_migration_status_maps_command_status(self):
        client = FakeRegistryClient()
        command = client.create_command("target", "import_vm_package", {})
        client.update_migration_status(
            "mig-1",
            {
                "source_host_id": "source",
                "target_host_id": "target",
                "source_vm_name": "hg-source",
                "target_vm_name": "hg-target",
                "strategy": "nas_clone",
                "status": "waiting_target",
                "result": {"command_id": command["command_id"]},
            },
        )
        client.commands[command["command_id"]]["status"] = "running"
        running = poll_remote_migration_status(client, "mig-1")
        self.assertEqual(running["migration"]["status"], "importing")
        client.commands[command["command_id"]]["status"] = "done"
        done = poll_remote_migration_status(client, "mig-1")
        self.assertEqual(done["migration"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
