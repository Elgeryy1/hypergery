import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from hypergery_ubuntu import cli
from hypergery_ubuntu.backend import VmSummary


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        with redirect_stdout(StringIO()):
            return cli.main(args)

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_create_vm_command_uses_real_backend_arguments(self, backend_cls):
        backend = backend_cls.return_value
        backend.create_vm.return_value = VmSummary(
            name="hg-test",
            state="shut off",
            lab_id="default-lab",
            disk_path="/tmp/hg-test.qcow2",
            network="hg-net-default-lab",
            graphics="spice",
        )
        code = self.run_cli(
            [
                "create-vm",
                "--name",
                "hg-test",
                "--iso",
                "/tmp/linux.iso",
                "--ram-mib",
                "4096",
                "--vcpus",
                "2",
                "--disk-gb",
                "40",
                "--network",
                "nat",
                "--display",
                "spice",
                "--lab-id",
                "default-lab",
            ]
        )
        self.assertEqual(code, 0)
        backend.create_vm.assert_called_once_with(
            name="hg-test",
            iso_path="/tmp/linux.iso",
            os_type="Linux",
            ram_mib=4096,
            vcpus=2,
            disk_gb=40,
            disk_dir=None,
            network_mode="nat",
            display_mode="spice",
            lab_id="default-lab",
        )

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_delete_vm_requires_explicit_delete_disks_flag(self, backend_cls):
        backend = backend_cls.return_value
        self.assertEqual(self.run_cli(["delete-vm", "hg-test"]), 0)
        backend.delete_vm.assert_called_once_with("hg-test", delete_disks=False)

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_snapshot_create_calls_backend(self, backend_cls):
        backend = backend_cls.return_value
        self.assertEqual(self.run_cli(["snapshot", "create", "hg-test", "snap1", "--description", "before install"]), 0)
        backend.create_snapshot.assert_called_once_with("hg-test", "snap1", "before install")

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_lifecycle_command_calls_backend(self, backend_cls):
        backend = backend_cls.return_value
        backend.start_vm = Mock()
        self.assertEqual(self.run_cli(["start", "hg-test"]), 0)
        backend.start_vm.assert_called_once_with("hg-test")

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_wait_state_command_calls_backend(self, backend_cls):
        backend = backend_cls.return_value
        backend.wait_for_state.return_value = "running"
        self.assertEqual(self.run_cli(["wait-state", "hg-test", "running", "--timeout", "5", "--interval", "0.5"]), 0)
        backend.wait_for_state.assert_called_once_with(
            "hg-test",
            {"running"},
            timeout_seconds=5,
            interval_seconds=0.5,
        )

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_list_vms_command_calls_backend(self, backend_cls):
        backend = backend_cls.return_value
        backend.list_vms.return_value = [
            VmSummary(name="hg-test", state="shut off", lab_id="default-lab", disk_path="/tmp/hg-test.qcow2")
        ]
        self.assertEqual(self.run_cli(["list-vms"]), 0)
        backend.list_vms.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
