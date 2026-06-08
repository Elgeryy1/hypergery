"""Regression tests for the v1.1 backend bug fixes.

Covers:
* config.hub_is_configured / HUB_URL_PLACEHOLDER (task 1)
* labs.allocate_lab_subnet full-range + clear exhaustion error (task 2)
* backend per-operation timeout plumbing + LONG_OPERATION_TIMEOUT (task 3)
* migration.export_vm_package atomic cleanup + progress_callback (task 4)

All tests use mocking for subprocess/filesystem and never require a real
libvirt/virsh/qemu install.
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu import backend as backend_mod
from hypergery_ubuntu import config as config_mod
from hypergery_ubuntu.backend import (
    CommandResult,
    DEFAULT_COMMAND_TIMEOUT,
    LONG_OPERATION_TIMEOUT,
    HyperGeryBackend,
    PreflightItem,
    VmSummary,
)
from hypergery_ubuntu.config import HUB_URL_PLACEHOLDER, HyperGeryConfig, hub_is_configured
from hypergery_ubuntu.labs import (
    LAB_SUBNET_OCTET_RANGE,
    RESERVED_LAB_SUBNET_OCTETS,
    allocate_lab_subnet,
)
from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.migration import export_vm_package
from hypergery_ubuntu.labs import LabStore


# --------------------------------------------------------------------------- #
# Task 1 - config hub_url placeholder / "sin configurar" detection
# --------------------------------------------------------------------------- #
class ConfigHubConfiguredTests(unittest.TestCase):
    def _clean_env(self, **extra):
        # Keep HOME/USERPROFILE so Path.home() still resolves on Windows when
        # default_config_values() is evaluated.
        keep = {
            k: v
            for k, v in os.environ.items()
            if k in {"HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "TEMP", "TMP"}
        }
        keep.update(extra)
        return keep

    def test_placeholder_is_used_as_default_and_flagged_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with patch.dict(os.environ, self._clean_env(), clear=True):
                values = config_mod.effective_config(missing)
                self.assertEqual(values["hub_url"].value, HUB_URL_PLACEHOLDER)
                self.assertEqual(values["hub_url"].source, "default")
                self.assertFalse(hub_is_configured(missing))

    def test_hub_is_configured_when_set_in_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            HyperGeryConfig(hub_url="http://hub.local:8765").save(path)
            with patch.dict(os.environ, self._clean_env(), clear=True):
                self.assertTrue(hub_is_configured(path))
                self.assertEqual(config_mod.effective_config(path)["hub_url"].source, "config")

    def test_hub_is_configured_when_set_via_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            env = self._clean_env(HYPERGERY_HUB_URL="http://env.local:8765")
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(hub_is_configured(missing))
                self.assertEqual(
                    config_mod.effective_config(missing)["hub_url"].source,
                    "env:HYPERGERY_HUB_URL",
                )


# --------------------------------------------------------------------------- #
# Task 2 - lab subnet allocation full range + clear exhaustion error
# --------------------------------------------------------------------------- #
class AllocateLabSubnetTests(unittest.TestCase):
    def test_skips_reserved_122_and_existing(self):
        # Force the seed to land on 122 first; allocation must skip it.
        existing = {"192.168.10.0/24"}
        subnet = allocate_lab_subnet("alpha-lab", existing)
        self.assertNotIn(subnet, existing)
        self.assertNotEqual(subnet, "192.168.122.0/24")
        self.assertTrue(subnet.startswith("192.168."))
        self.assertTrue(subnet.endswith(".0/24"))

    def test_can_allocate_beyond_old_180_cap(self):
        # The old implementation only used octets 20..199. Occupy everything in
        # that legacy window and confirm allocation still succeeds using an
        # octet outside it (proving the full 0..255 range is now iterated).
        legacy = {f"192.168.{octet}.0/24" for octet in range(20, 200)}
        subnet = allocate_lab_subnet("beyond-lab", legacy)
        octet = int(subnet.split(".")[2])
        self.assertNotIn(octet, range(20, 200))
        self.assertNotIn(octet, RESERVED_LAB_SUBNET_OCTETS)

    def test_exhaustion_raises_clear_spanish_error(self):
        # Occupy every assignable subnet (all octets except reserved ones).
        full = {
            f"192.168.{octet}.0/24"
            for octet in LAB_SUBNET_OCTET_RANGE
            if octet not in RESERVED_LAB_SUBNET_OCTETS
        }
        with self.assertRaises(HyperGeryError) as ctx:
            allocate_lab_subnet("crowded-lab", full)
        message = str(ctx.exception)
        self.assertIn("subredes", message)
        self.assertIn("libera", message.lower())

    def test_unique_subnets_across_many_labs(self):
        # 250 labs must each get a distinct subnet without silent wrap-around.
        assigned: set[str] = set()
        for index in range(250):
            subnet = allocate_lab_subnet(f"lab-{index:03d}", assigned)
            self.assertNotIn(subnet, assigned)
            assigned.add(subnet)
        self.assertEqual(len(assigned), 250)


# --------------------------------------------------------------------------- #
# Task 3 - backend per-operation timeout
# --------------------------------------------------------------------------- #
class BackendTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._safe_cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "XDG_DATA_HOME": str(Path(self.tmp.name) / "data"),
                "XDG_STATE_HOME": str(Path(self.tmp.name) / "state"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.backend = HyperGeryBackend()

    def _safe_cleanup(self):
        # Windows can hold file handles briefly; ignore cleanup errors.
        try:
            self.tmp.cleanup()
        except (PermissionError, OSError):
            pass

    def test_default_timeout_constant(self):
        self.assertEqual(DEFAULT_COMMAND_TIMEOUT, 120)
        self.assertGreaterEqual(LONG_OPERATION_TIMEOUT, 1800)

    def test_run_uses_default_timeout(self):
        captured = {}

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_subprocess_run(args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return FakeProc()

        with patch.object(backend_mod.subprocess, "run", side_effect=fake_subprocess_run):
            self.backend.run(["echo", "hi"])
        self.assertEqual(captured["timeout"], DEFAULT_COMMAND_TIMEOUT)

    def test_qemu_img_passes_custom_timeout_through_to_run(self):
        captured = {}

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_subprocess_run(args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return FakeProc()

        with patch.object(backend_mod.subprocess, "run", side_effect=fake_subprocess_run):
            self.backend.qemu_img(["convert", "a", "b"], timeout=LONG_OPERATION_TIMEOUT)
        self.assertEqual(captured["timeout"], LONG_OPERATION_TIMEOUT)

    def test_clone_vm_uses_long_timeout_for_disk_convert(self):
        captured = {}

        source = VmSummary(
            name="src",
            state="shut off",
            lab_id="default-lab",
            ram_mib=2048,
            vcpus=2,
            disk_path="/tmp/src.qcow2",
            iso_path="",
            network="hg-net-default-lab",
            graphics="spice",
            xml="<domain type='kvm'><name>src</name><uuid>u</uuid>"
            "<metadata></metadata><devices>"
            "<disk device='disk'><source file='/tmp/src.qcow2'/></disk>"
            "</devices></domain>",
        )

        def fake_qemu_img(args, *, timeout=DEFAULT_COMMAND_TIMEOUT, check=True):
            captured["timeout"] = timeout
            return CommandResult(["qemu-img", *args], 0, "", "")

        def fake_virsh(args, *, timeout=DEFAULT_COMMAND_TIMEOUT, check=True):
            # dominfo lookup for the clone name: report "not found".
            return CommandResult(["virsh", *args], 1, "", "")

        with patch.object(self.backend, "get_vm", return_value=source), patch.object(
            self.backend, "qemu_img", side_effect=fake_qemu_img
        ), patch.object(self.backend, "virsh", side_effect=fake_virsh), patch.object(
            self.backend, "grant_libvirt_qemu_access"
        ), patch.object(
            self.backend, "define_domain_xml"
        ), patch.object(
            self.backend, "update_lab_for_vm"
        ):
            # get_vm is patched to always return the source summary, so the final
            # get_vm(clone) call also returns it; that's fine for this assertion.
            self.backend.clone_vm("src", "clone-target")
        self.assertEqual(captured["timeout"], LONG_OPERATION_TIMEOUT)


# --------------------------------------------------------------------------- #
# Task 4 - migration export atomic cleanup + progress callback
# --------------------------------------------------------------------------- #
DOMAIN_XML = """<domain type="kvm">
  <name>hg-source</name>
  <uuid>11111111-1111-1111-1111-111111111111</uuid>
  <metadata>
    <hg:hypergery xmlns:hg="https://hypergery.local/schema/0.1">
      <hg:managed>true</hg:managed>
      <hg:lab_id>migration-lab</hg:lab_id>
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
    <graphics type="spice"/>
  </devices>
</domain>"""


class FakeExportBackend:
    def __init__(self, root: Path) -> None:
        self.data_dir = root / "hypergery"
        self.vms_dir = self.data_dir / "vms"
        self.vms_dir.mkdir(parents=True)
        self.disk = root / "source.qcow2"
        self.iso = root / "installer.iso"
        self.disk.write_bytes(b"disk-data")
        self.iso.write_bytes(b"iso-data")
        self.xml = DOMAIN_XML.format(disk=self.disk, iso=self.iso)
        self.state = "shut off"
        LabStore(self.data_dir).create_lab("Migration Lab", lab_id="migration-lab")

    def get_vm(self, name: str) -> VmSummary:
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


class MigrationExportFixesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._safe_cleanup)
        self.root = Path(self.tmp.name)
        self.backend = FakeExportBackend(self.root)

    def _safe_cleanup(self):
        try:
            self.tmp.cleanup()
        except (PermissionError, OSError):
            pass

    def test_progress_callback_invoked_per_asset(self):
        calls = []

        def progress(message, current, total):
            calls.append((message, current, total))

        export_vm_package(
            self.backend,
            "hg-source",
            self.root / "nas",
            target_vm_name="hg-target",
            progress_callback=progress,
        )
        # Two assets exist (disk + iso); callback fires once per asset.
        self.assertEqual(len(calls), 2)
        self.assertEqual([c[1] for c in calls], [1, 2])
        self.assertTrue(all(c[2] == 2 for c in calls))
        self.assertTrue(any("disk" in c[0] for c in calls))
        self.assertTrue(any("iso" in c[0] for c in calls))

    def test_export_remains_backward_compatible_without_callback(self):
        result = export_vm_package(
            self.backend,
            "hg-source",
            self.root / "nas",
            target_vm_name="hg-target",
        )
        self.assertTrue(Path(result["package_dir"]).is_dir())
        self.assertTrue((Path(result["package_dir"]) / "manifest.json").is_file())

    def test_partial_package_cleaned_up_on_copy_failure(self):
        boom = RuntimeError("disco lleno")

        def progress(message, current, total):
            # Fail while copying the second asset, after the first was written.
            if current == 2:
                raise boom

        nas = self.root / "nas"
        with self.assertRaises(RuntimeError) as ctx:
            export_vm_package(
                self.backend,
                "hg-source",
                nas,
                target_vm_name="hg-target",
                progress_callback=progress,
            )
        # Original error is re-raised unchanged.
        self.assertIs(ctx.exception, boom)
        # No partial package directory is left behind.
        packages_root = nas / "migrations"
        leftovers = list(packages_root.glob("*")) if packages_root.exists() else []
        self.assertEqual(leftovers, [], f"partial package left behind: {leftovers}")

    def test_cleanup_swallows_rmtree_errors_and_reraises_original(self):
        boom = RuntimeError("fallo de copia")

        def progress(message, current, total):
            if current == 1:
                raise boom

        with patch.object(
            __import__("hypergery_ubuntu.migration", fromlist=["shutil"]).shutil,
            "rmtree",
            side_effect=OSError("no se puede borrar"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                export_vm_package(
                    self.backend,
                    "hg-source",
                    self.root / "nas2",
                    target_vm_name="hg-target",
                    progress_callback=progress,
                )
        # Cleanup failure must not mask the original copy error.
        self.assertIs(ctx.exception, boom)


if __name__ == "__main__":
    unittest.main()
