import unittest
import json
import os
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
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

    def test_lab_cli_create_list_show_delete(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": str(Path(tmp) / "state")}):
            self.assertEqual(self.run_cli(["lab", "create", "Security Lab", "--description", "training"]), 0)
            self.assertEqual(self.run_cli(["lab", "show", "security-lab"]), 0)
            self.assertEqual(self.run_cli(["lab", "list"]), 0)
            self.assertEqual(self.run_cli(["lab", "delete", "security-lab"]), 0)

    def test_template_cli_list_show_delete(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": str(Path(tmp) / "state")}):
            from hypergery_ubuntu.templates import TemplateStore

            store = TemplateStore(Path(tmp) / "hypergery")
            store.create_vm_template("Ubuntu Base")
            self.assertEqual(self.run_cli(["template", "list", "vm"]), 0)
            self.assertEqual(self.run_cli(["template", "show", "vm", "ubuntu-base"]), 0)
            self.assertEqual(self.run_cli(["template", "delete", "vm", "ubuntu-base"]), 0)

    def test_template_update_cli_changes_field(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": str(Path(tmp) / "state")}):
            from hypergery_ubuntu.templates import TemplateStore
            import json
            from io import StringIO

            store = TemplateStore(Path(tmp) / "hypergery")
            store.create_vm_template("Ubuntu Base", ram_mib=2048)
            buf = StringIO()
            with redirect_stdout(buf):
                code = cli.main(["template", "update", "vm", "ubuntu-base", "--set", "ram_mib=8192", "--set", "notes=updated"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["ram_mib"], 8192)
            self.assertEqual(data["notes"], "updated")

    def test_lab_topology_cli_returns_json(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": str(Path(tmp) / "state")}):
            import json
            from io import StringIO
            from unittest.mock import Mock

            with patch("hypergery_ubuntu.cli.HyperGeryBackend") as backend_cls:
                backend = backend_cls.return_value
                backend.data_dir = Path(tmp) / "hypergery"
                backend.list_vms.return_value = []
                from hypergery_ubuntu.labs import LabStore
                LabStore(backend.data_dir).create_lab("Security Lab", lab_id="security-lab")
                buf = StringIO()
                with redirect_stdout(buf):
                    code = cli.main(["lab-topology", "security-lab"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["lab_id"], "security-lab")
            self.assertIn("vms", data)

    def test_lab_instantiate_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": str(Path(tmp) / "state")}):
            import json
            from io import StringIO

            with patch("hypergery_ubuntu.cli.HyperGeryBackend") as backend_cls:
                backend = backend_cls.return_value
                backend.data_dir = Path(tmp) / "hypergery"
                from hypergery_ubuntu.templates import TemplateStore
                from hypergery_ubuntu.labs import LabStore
                store = TemplateStore(backend.data_dir, backend=backend, lab_store=LabStore(backend.data_dir))
                store.create_lab_template("ASR Lab", "asr", "nat", [])
                buf = StringIO()
                with redirect_stdout(buf):
                    code = cli.main(["lab-instantiate", "asr-lab", "ASR Instance", "--dry-run"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["dry_run"])
            self.assertIsNone(data["lab"])

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_migrate_preflight_cli_returns_json(self, backend_cls):
        from hypergery_ubuntu.backend import CommandResult, PreflightItem

        backend = backend_cls.return_value
        backend.get_vm.return_value = VmSummary(
            name="hg-source",
            state="shut off",
            lab_id="default-lab",
            ram_mib=2048,
            vcpus=2,
            disk_path="",
            iso_path="",
            network="hg-net-default-lab",
            graphics="spice",
            xml="<domain><name>hg-source</name><devices/></domain>",
        )
        backend.list_snapshots.return_value = []
        backend.preflight.return_value = [PreflightItem("libvirt connection", "OK", "Connected.")]
        backend.virsh.return_value = CommandResult(["virsh"], 1, "", "not found")
        buf = StringIO()
        with redirect_stdout(buf):
            code = cli.main(["migrate", "preflight", "hg-source", "--target-vm-name", "hg-target"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["target_vm_name"], "hg-target")
        self.assertFalse(data["source_will_be_deleted"])

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_migrate_status_registry_parses_remote_command_status(self, backend_cls):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def migration(self, migration_id):
                return {
                    "migration_id": migration_id,
                    "source_host_id": "source",
                    "target_host_id": "target",
                    "source_vm_name": "hg-source",
                    "target_vm_name": "hg-target",
                    "status": "waiting_target",
                    "result": {"command_id": "cmd-1"},
                    "warnings": [],
                }

            def command(self, command_id):
                return {"command_id": command_id, "status": "running", "result": {}}

            def update_migration_status(self, migration_id, payload):
                return {"migration_id": migration_id, **payload}

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf):
                code = cli.main(["migrate", "status", "--migration-id", "mig-1", "--registry-url", "http://registry:8765"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["migration"]["status"], "importing")

    def test_hub_init_db_cli_creates_store_without_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "hub.sqlite")
            buf = StringIO()
            with redirect_stdout(buf):
                code = cli.main(["hub", "init-db", "--db-path", db_path])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["db_path"], db_path)

    def test_hub_url_env_takes_precedence_for_host_commands(self):
        with patch.dict(os.environ, {"HYPERGERY_HUB_URL": "http://hub.local:8765", "HYPERGERY_REGISTRY_URL": "http://old.local:8765"}):
            parser_default = cli.default_hub_url()
        self.assertEqual(parser_default, "http://hub.local:8765")

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_host_test_wait_polls_for_ping_result(self, backend_cls):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url
                self.reads = [
                    {"command_id": "cmd-1", "status": "pending", "result": {}},
                    {"command_id": "cmd-1", "status": "done", "result": {"pong": True}},
                ]

            def create_command(self, host_id, command_type, payload):
                return {"command_id": "cmd-1", "target_host_id": host_id, "command_type": command_type, "status": "pending", "result": {}}

            def command(self, command_id):
                return self.reads.pop(0)

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient), patch("hypergery_ubuntu.cli.time.sleep"):
            with redirect_stdout(buf):
                code = cli.main(["host", "test", "hg-target", "--hub-url", "http://hub:8765", "--wait", "--interval", "0.01"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "done")
        self.assertTrue(data["result"]["pong"])
        backend_cls.assert_not_called()

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_host_test_without_wait_only_queues_command(self, backend_cls):
        called = {"create": 0}

        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def create_command(self, host_id, command_type, payload):
                called["create"] += 1
                return {"command_id": "cmd-1", "target_host_id": host_id, "command_type": command_type, "status": "pending", "result": {}}

            def command(self, command_id):
                raise AssertionError("default host test must not poll command status")

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient), patch("hypergery_ubuntu.cli.wait_for_command") as wait_mock:
            with redirect_stdout(buf):
                # Even a non-zero --timeout must be ignored without --wait.
                code = cli.main(["host", "test", "hg-target", "--hub-url", "http://hub:8765", "--timeout", "30"])
        self.assertEqual(code, 0)
        self.assertEqual(called["create"], 1)
        wait_mock.assert_not_called()
        data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "pending")
        backend_cls.assert_not_called()

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_host_test_wait_passes_timeout_to_wait_for_command(self, backend_cls):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def create_command(self, host_id, command_type, payload):
                return {"command_id": "cmd-1", "target_host_id": host_id, "command_type": command_type, "status": "pending", "result": {}}

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient), patch(
            "hypergery_ubuntu.cli.wait_for_command",
            return_value={"command_id": "cmd-1", "status": "done", "result": {"pong": True}},
        ) as wait_mock:
            with redirect_stdout(buf):
                code = cli.main(["host", "test", "hg-target", "--hub-url", "http://hub:8765", "--wait", "--timeout", "5"])
        self.assertEqual(code, 0)
        wait_mock.assert_called_once()
        self.assertEqual(wait_mock.call_args.kwargs["timeout_seconds"], 5.0)
        backend_cls.assert_not_called()

    def test_hub_packages_cli_prints_staging_summary(self):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def list_staged_packages(self):
                return {
                    "staging_dir": "/data/staging",
                    "count": 1,
                    "orphan_count": 1,
                    "total_size_bytes": 4096,
                    "packages": [
                        {
                            "migration_id": "mig-orphan",
                            "size_bytes": 4096,
                            "file_count": 2,
                            "age_hours": 48.0,
                            "migration_status": "",
                            "orphan": True,
                        }
                    ],
                }

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf):
                code = cli.main(["hub", "packages", "--hub-url", "http://hub:8765"])
        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("mig-orphan", output)
        self.assertIn("4.0 KiB", output)

    def test_hub_cleanup_staging_without_confirm_is_dry_run(self):
        calls = []

        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def cleanup_staging(self, **kwargs):
                calls.append(kwargs)
                return {
                    "staging_dir": "/data/staging",
                    "dry_run": kwargs["dry_run"],
                    "older_than_hours": kwargs["older_than_hours"],
                    "candidates": [],
                    "total_size_bytes": 0,
                    "deleted_count": 0,
                    "deleted_size_bytes": 0,
                    "skipped": [],
                    "errors": [],
                }

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf):
                code = cli.main(["hub", "cleanup-staging", "--older-than-hours", "24", "--hub-url", "http://hub:8765"])
        self.assertEqual(code, 0)
        self.assertTrue(calls[0]["dry_run"])
        self.assertIn("DRY RUN", buf.getvalue())

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf):
                code = cli.main(
                    ["hub", "cleanup-staging", "--older-than-hours", "24", "--confirm", "--hub-url", "http://hub:8765"]
                )
        self.assertEqual(code, 0)
        self.assertFalse(calls[1]["dry_run"])
        self.assertIn("CLEANUP EXECUTED", buf.getvalue())

    def test_hub_cleanup_staging_real_errors_return_nonzero(self):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def cleanup_staging(self, **kwargs):
                return {
                    "staging_dir": "/data/staging",
                    "dry_run": False,
                    "older_than_hours": 24.0,
                    "candidates": [{"migration_id": "mig-bad", "size_bytes": 10, "reason": "orphan"}],
                    "total_size_bytes": 10,
                    "deleted_count": 0,
                    "deleted_size_bytes": 0,
                    "skipped": [],
                    "errors": [{"migration_id": "mig-bad", "error": "permission denied"}],
                }

        buf = StringIO()
        err = StringIO()
        from contextlib import redirect_stderr

        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf), redirect_stderr(err):
                code = cli.main(["hub", "cleanup-staging", "--confirm", "--hub-url", "http://hub:8765"])
        self.assertEqual(code, 1)
        self.assertIn("permission denied", err.getvalue())

    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_host_test_timeout_zero_only_queues_command(self, backend_cls):
        class FakeRegistryClient:
            def __init__(self, url):
                self.url = url

            def create_command(self, host_id, command_type, payload):
                return {"command_id": "cmd-1", "target_host_id": host_id, "command_type": command_type, "status": "pending", "result": {}}

            def command(self, command_id):
                raise AssertionError("command status should not be polled")

        buf = StringIO()
        with patch("hypergery_ubuntu.registry.RegistryClient", FakeRegistryClient):
            with redirect_stdout(buf):
                code = cli.main(["host", "test", "hg-target", "--hub-url", "http://hub:8765", "--timeout", "0"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "pending")
        backend_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
