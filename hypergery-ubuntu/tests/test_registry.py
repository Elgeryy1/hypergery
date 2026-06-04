from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.registry import RegistryServer, RegistryStore


class RegistryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3", offline_timeout_seconds=0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_host_register_and_heartbeat(self):
        host = self.store.register_host({
            "host_id": "pc-casa",
            "name": "PC Casa",
            "hostname": "pc-casa.local",
            "kvm_ok": True,
            "libvirt_ok": True,
            "active_vms": ["vm1"],
        })
        self.assertEqual(host["host_id"], "pc-casa")
        self.assertTrue(host["kvm_ok"])
        self.assertEqual(host["active_vms"], ["vm1"])

        updated = self.store.heartbeat({
            "host_id": "pc-casa",
            "name": "PC Casa",
            "hostname": "pc-casa.local",
            "active_vms": ["vm1", "vm2"],
        })
        self.assertEqual(updated["active_vms"], ["vm1", "vm2"])

    def test_offline_detection_does_not_delete_host(self):
        self.store.register_host({"host_id": "slow-host", "hostname": "slow-host"})
        time.sleep(0.01)
        host = self.store.get_host("slow-host")
        self.assertEqual(host["status"], "offline")
        self.assertEqual(len(self.store.list_hosts()), 1)

    def test_command_queue_allowlist_and_result(self):
        self.store.register_host({"host_id": "target", "hostname": "target"})
        command = self.store.create_command({
            "target_host_id": "target",
            "command_type": "ping",
            "payload": {"hello": "world"},
        })
        self.assertEqual(command["status"], "pending")
        pending = self.store.pending_commands_for_host("target")
        self.assertEqual([item["command_id"] for item in pending], [command["command_id"]])

        done = self.store.set_command_result(command["command_id"], {"status": "done", "result": {"pong": True}})
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"], {"pong": True})
        self.assertEqual(self.store.pending_commands_for_host("target"), [])

        with self.assertRaises(HyperGeryError):
            self.store.create_command({"target_host_id": "target", "command_type": "shell", "payload": {}})

    def test_migration_status_lifecycle_accepts_remote_progress_states(self):
        payload = {
            "source_host_id": "source",
            "target_host_id": "target",
            "source_vm_name": "hg-source",
            "target_vm_name": "hg-target",
            "strategy": "nas_clone",
        }
        for status in ("preflight", "packaging", "uploaded", "waiting_target", "importing", "defining_vm", "done"):
            migration = self.store.update_migration_status("mig-1", {**payload, "status": status})
            self.assertEqual(migration["status"], status)
        failed = self.store.update_migration_status("mig-1", {**payload, "status": "failed", "errors": ["boom"]})
        self.assertEqual(failed["errors"], ["boom"])


class RegistryHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(("127.0.0.1", 0), store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request_json(self, method: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.base_url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_host_endpoints(self):
        status, health = self.request_json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"ok": True})

        status, host = self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        self.assertEqual(status, 200)
        self.assertEqual(host["host_id"], "local")

        status, hosts = self.request_json("GET", "/hosts")
        self.assertEqual(status, 200)
        self.assertEqual(hosts["hosts"][0]["host_id"], "local")

    def test_command_endpoints(self):
        self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        status, command = self.request_json("POST", "/commands", {
            "target_host_id": "local",
            "command_type": "ping",
            "payload": {},
        })
        self.assertEqual(status, 201)

        status, queued = self.request_json("GET", "/commands/local")
        self.assertEqual(status, 200)
        self.assertEqual(queued["commands"][0]["command_id"], command["command_id"])

        status, result = self.request_json("POST", f"/commands/{command['command_id']}/result", {
            "status": "done",
            "result": {"pong": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], {"pong": True})


if __name__ == "__main__":
    unittest.main()
