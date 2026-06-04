from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu import cli
from hypergery_ubuntu.agent import AgentConfig, HyperGeryAgent
from hypergery_ubuntu.backend import HyperGeryError, PreflightItem, VmSummary
from hypergery_ubuntu.migration import export_vm_package
from hypergery_ubuntu.registry import RegistryServer, RegistryStore
from tests.test_migration import FakeBackend as MigrationFakeBackend


class FakeBackend:
    data_dir = Path("/tmp/hypergery-test")

    def list_vms(self):
        return [
            VmSummary(name="running-vm", state="running", lab_id="lab1", ram_mib=1024, vcpus=1, disk_path="/tmp/a.qcow2"),
            VmSummary(name="off-vm", state="shut off", lab_id="lab1", ram_mib=1024, vcpus=1, disk_path="/tmp/b.qcow2"),
        ]

    def virsh(self, args, *, check=True, timeout=120):
        raise AssertionError("virsh should not be needed when list_vms works")

    def preflight(self):
        return [PreflightItem("kvm", "OK", "ready")]


class FakeClient:
    def __init__(self):
        self.results = []
        self.migration_updates = []
        self.commands = [
            {"command_id": "cmd-1", "command_type": "ping", "payload": {}},
            {"command_id": "cmd-2", "command_type": "list_vms", "payload": {}},
        ]

    def register_host(self, payload):
        return dict(payload, status="online")

    def heartbeat(self, payload):
        return dict(payload, status="online")

    def report_vms(self, host_id, vms):
        self.reported_vms = {"host_id": host_id, "vms": vms}
        return {"host_id": host_id, "count": len(vms), "vms": vms}

    def pending_commands(self, host_id):
        return list(self.commands)

    def set_command_result(self, command_id, status, result):
        payload = {"command_id": command_id, "status": status, "result": result}
        self.results.append(payload)
        return payload

    def update_migration_status(self, migration_id, payload):
        update = {"migration_id": migration_id, **payload}
        self.migration_updates.append(update)
        return update


class AgentTests(unittest.TestCase):
    def test_config_loads_json_without_password_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.json"
            path.write_text(
                json.dumps({
                    "registry_url": "http://nas.local:8765",
                    "host_id": "pc-casa",
                    "name": "PC Casa",
                    "nas_staging_path": "/mnt/hypergery-nas/migrations",
                }),
                encoding="utf-8",
            )
            config = AgentConfig.load(path)
        self.assertEqual(config.registry_url, "http://nas.local:8765")
        self.assertEqual(config.host_id, "pc-casa")
        self.assertNotIn("password", config.to_public_dict())

    def test_heartbeat_payload_reports_active_vms_and_capabilities(self):
        config = AgentConfig(host_id="local", name="Local", nas_staging_path="/tmp")
        agent = HyperGeryAgent(config, backend=FakeBackend(), client=FakeClient())
        payload = agent.host_payload()
        self.assertEqual(payload["host_id"], "local")
        self.assertIn("running-vm", payload["active_vms"])
        self.assertNotIn("off-vm", payload["active_vms"])
        self.assertIn("kvm_ok", payload)
        self.assertIn("libvirt_ok", payload)

    def test_heartbeat_reports_vm_inventory_to_hub(self):
        client = FakeClient()
        agent = HyperGeryAgent(AgentConfig(host_id="local", name="Local", nas_staging_path="/tmp"), backend=FakeBackend(), client=client)
        agent.heartbeat()
        self.assertEqual(client.reported_vms["host_id"], "local")
        self.assertEqual(client.reported_vms["vms"][0]["vm_name"], "running-vm")
        self.assertEqual(client.reported_vms["vms"][0]["display"], "unknown")

    def test_config_reads_hub_environment_before_registry_fallback(self):
        with patch.dict(
            os.environ,
            {
                "HYPERGERY_HUB_URL": "http://hub.local:8765",
                "HYPERGERY_REGISTRY_URL": "http://registry.local:8765",
                "HYPERGERY_HOST_ID": "ubuntu-hyperv",
                "HYPERGERY_HOST_NAME": "Ubuntu Hyper-V",
                "HYPERGERY_NAS_STAGING_PATH": "/mnt/hypergery-nas/hypergery",
            },
        ):
            config = AgentConfig()
        self.assertEqual(config.registry_url, "http://hub.local:8765")
        self.assertEqual(config.host_id, "ubuntu-hyperv")
        self.assertEqual(config.name, "Ubuntu Hyper-V")
        self.assertEqual(config.nas_staging_path, "/mnt/hypergery-nas/hypergery")

    def test_agent_allowlist_blocks_arbitrary_command(self):
        agent = HyperGeryAgent(AgentConfig(host_id="local"), backend=FakeBackend(), client=FakeClient())
        with self.assertRaises(HyperGeryError):
            agent.execute_command({"command_type": "shell", "payload": {"cmd": "rm -rf /"}})

    def test_run_once_executes_safe_pending_commands(self):
        client = FakeClient()
        agent = HyperGeryAgent(AgentConfig(host_id="local"), backend=FakeBackend(), client=client)
        result = agent.run_once()
        self.assertEqual(result["host"]["host_id"], "local")
        done_results = [item for item in client.results if item["status"] == "done"]
        self.assertEqual(len(done_results), 2)
        self.assertTrue(done_results[0]["result"]["pong"])
        self.assertEqual(done_results[1]["result"]["vms"][0]["name"], "running-vm")

    def test_agent_vm_migration_preflight_command_blocks_running_vm(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp), state="running")
            config = AgentConfig(host_id="local", nas_staging_path=str(Path(tmp) / "nas"))
            agent = HyperGeryAgent(config, backend=backend, client=FakeClient())
            status, result = agent.execute_command(
                {
                    "command_type": "preflight",
                    "payload": {"vm_name": "hg-source", "target_vm_name": "hg-target"},
                }
            )
        self.assertEqual(status, "failed")
        self.assertFalse(result["source_will_be_deleted"])
        self.assertIn("Running VM migration is blocked", "; ".join(result["errors"]))

    def test_agent_receive_vm_package_validates_only_staged_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = MigrationFakeBackend(root / "source")
            export = export_vm_package(backend, "hg-source", root / "nas", target_vm_name="hg-target")
            agent = HyperGeryAgent(
                AgentConfig(host_id="local", nas_staging_path=str(root / "nas")),
                backend=backend,
                client=FakeClient(),
            )

            status, result = agent.execute_command(
                {
                    "command_type": "receive_vm_package",
                    "payload": {"package_dir": export["package_dir"]},
                }
            )
            self.assertEqual(status, "done")
            self.assertTrue(result["validation"]["ok"])

            with self.assertRaises(HyperGeryError):
                agent.execute_command(
                    {
                        "command_type": "receive_vm_package",
                        "payload": {"package_dir": str(root / "outside")},
                    }
                )

    def test_agent_import_vm_package_uses_migration_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_backend = MigrationFakeBackend(root / "source")
            export = export_vm_package(source_backend, "hg-source", root / "nas", target_vm_name="hg-target")
            target_backend = MigrationFakeBackend(root / "target")
            agent = HyperGeryAgent(
                AgentConfig(host_id="target", nas_staging_path=str(root / "nas")),
                backend=target_backend,
                client=FakeClient(),
            )

            status, result = agent.execute_command(
                {
                    "command_type": "import_vm_package",
                    "payload": {
                        "package_dir": export["package_dir"],
                        "target_vm_name": "hg-target",
                        "target_lab_id": "target-lab",
                    },
                }
            )
            self.assertEqual(status, "done")
            self.assertEqual(result["target_vm_name"], "hg-target")
            self.assertIn("hg-target", target_backend.defined_xml)

    def test_agent_import_vm_package_reports_migration_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_backend = MigrationFakeBackend(root / "source")
            export = export_vm_package(source_backend, "hg-source", root / "nas", target_vm_name="hg-target", migration_id="mig-1")
            target_backend = MigrationFakeBackend(root / "target")
            client = FakeClient()
            agent = HyperGeryAgent(
                AgentConfig(host_id="target", nas_staging_path=str(root / "nas")),
                backend=target_backend,
                client=client,
            )

            status, result = agent.execute_command(
                {
                    "command_type": "import_vm_package",
                    "payload": {
                        "migration_id": "mig-1",
                        "source_host_id": "source",
                        "source_vm_name": "hg-source",
                        "package_dir": export["package_dir"],
                        "target_vm_name": "hg-target",
                    },
                }
            )
            self.assertEqual(status, "done")
            self.assertEqual(result["target_vm_name"], "hg-target")
            self.assertEqual([item["status"] for item in client.migration_updates], ["importing", "defining_vm", "done"])


class AgentCliTests(unittest.TestCase):
    def test_agent_config_show_does_not_require_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-agent.json"
            buf = StringIO()
            with redirect_stdout(buf):
                code = cli.main(["agent", "config", "show", "--config", str(path)])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["exists"])
            self.assertEqual(data["config"]["host_id"], AgentConfig().host_id)

    def test_host_test_queues_ping_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistryStore(Path(tmp) / "registry.sqlite3")
            store.register_host({"host_id": "local", "hostname": "localhost"})
            server = RegistryServer(("127.0.0.1", 0), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                buf = StringIO()
                with redirect_stdout(buf):
                    code = cli.main(["host", "test", "local", "--registry-url", f"http://{host}:{port}"])
                self.assertEqual(code, 0)
                data = json.loads(buf.getvalue())
                self.assertEqual(data["command_type"], "ping")
                self.assertEqual(data["target_host_id"], "local")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
