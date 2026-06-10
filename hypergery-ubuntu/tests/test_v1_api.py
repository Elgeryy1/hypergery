import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.labs import LabStore
from hypergery_ubuntu.v1.api import ApiContext, ApiServer
from hypergery_ubuntu.v1.battery import BatteryService
from hypergery_ubuntu.v1.external_nodes import ExternalNode, ExternalNodeStore
from hypergery_ubuntu.v1.hosts import HostRegistry
from hypergery_ubuntu.v1.nas import NasService
from hypergery_ubuntu.v1.providers import VmInfo
from hypergery_ubuntu.v1.rbac import User, UserStore
from hypergery_ubuntu.v1.settings import V1Settings
from hypergery_ubuntu.v1.telemetry import TelemetryService
from hypergery_ubuntu.v1.teleport import TeleportEngine
from tests.test_migration import FakeBackend, FakeRegistryClient


def fake_battery_dir(tmp: Path, percent: int = 64) -> Path:
    battery = tmp / "BAT0"
    battery.mkdir(parents=True)
    (battery / "capacity").write_text(f"{percent}\n", encoding="utf-8")
    (battery / "status").write_text("Discharging\n", encoding="utf-8")
    return tmp


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        settings = V1Settings()
        telemetry = TelemetryService(
            settings=settings,
            history_path=root / "history.json",
            host_id="laptop",
            power_supply_dir=fake_battery_dir(root / "power"),
        )
        nas_root = root / "nas"
        nas_root.mkdir()
        lab_store = LabStore(root / "data")
        lab = lab_store.create_lab("ASR Lab")
        lab_store.update_workspace_fields(lab["lab_id"], subject="ASR", favorite=True)
        user_store = UserStore(root / "users.json")
        user_store.add_user(User(id="gerard", role="SuperAdmin"))
        user_store.add_user(User(id="alumno", role="Guest", assigned_labs=["asr-lab"]))
        node_store = ExternalNodeStore(root / "nodes.json")
        node_store.add_node(ExternalNode(id="loop-node", type="loopback", ram_mib=4096))
        backend = FakeBackend(root / "vmhost")
        hub_client = FakeRegistryClient()
        hub_client.list_hosts = lambda: [
            {"host_id": "pc-casa", "status": "offline", "ram_total_mib": 32768, "ram_free_mib": 30000},
        ]
        hub_client.list_vms = lambda host_id=None: [
            {"vm_name": "remote-vm", "state": "running", "host_id": "pc-casa", "lab_id": "asr-lab", "ram_mib": 4096, "vcpus": 2},
        ]
        context = ApiContext(
            settings=settings,
            telemetry=telemetry,
            host_registry=HostRegistry(settings=settings, telemetry=telemetry, hub_client=hub_client),
            battery=BatteryService(settings=settings, power_supply_dir=str(root / "power")),
            nas=NasService(nas_root, settings=settings, lab_store=lab_store),
            lab_store=lab_store,
            user_store=user_store,
            node_store=node_store,
            teleport_engine=TeleportEngine(backend, settings=settings, hub_client=hub_client, source_host_id="laptop"),
            local_vms=lambda: [VmInfo(id="local-vm", ram_mb=2048, status="running", host_id="laptop", lab_id="asr-lab")],
            hub_client=hub_client,
        )
        from hypergery_ubuntu.v1.auth import ApiTokenStore

        cls.token_store = ApiTokenStore(root / "api_tokens.json")
        cls.server = ApiServer(("127.0.0.1", 0), context, auth_token="test-owner-token", token_store=cls.token_store)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def get(self, path, token="test-owner-token"):
        request = Request(self.base + path, method="GET")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post(self, path, payload=None, token="test-owner-token"):
        data = json.dumps(payload or {}).encode("utf-8")
        request = Request(self.base + path, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_envelope(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIsNone(body["error"])
        self.assertIn("timestamp", body)
        self.assertEqual(body["data"]["status"], "ok")

    def test_hosts_endpoints(self):
        status, body = self.get("/hosts")
        ids = [host["id"] for host in body["data"]["hosts"]]
        self.assertIn("laptop", ids)
        self.assertIn("pc-casa", ids)
        status, body = self.get("/hosts/laptop")
        self.assertTrue(body["data"]["health"]["reachable"])

    def test_telemetry_with_alerts(self):
        status, body = self.get("/telemetry")
        self.assertEqual(body["data"]["local"]["host_id"], "laptop")
        kinds = {alert["kind"] for alert in body["data"]["alerts"]}
        self.assertIn("host_offline", kinds)  # pc-casa offline

    def test_labs_with_filters_and_validation(self):
        status, body = self.get("/labs")
        self.assertEqual(len(body["data"]["labs"]), 1)
        status, body = self.get("/labs?subject=DB")
        self.assertEqual(body["data"]["labs"], [])
        status, body = self.get("/labs/asr-lab")
        self.assertTrue(body["data"]["validation"]["ok"])

    def test_vms_merge_local_and_hub(self):
        status, body = self.get("/vms")
        ids = {vm["id"] for vm in body["data"]["vms"]}
        self.assertEqual(ids, {"local-vm", "remote-vm"})
        status, body = self.get("/vms/remote-vm")
        self.assertEqual(body["data"]["vm"]["host_id"], "pc-casa")

    def test_nas_status(self):
        status, body = self.get("/nas/status")
        self.assertTrue(body["data"]["health"]["ok"])

    def test_battery_endpoint(self):
        status, body = self.get("/battery")
        self.assertTrue(body["data"]["battery"]["available"])
        self.assertEqual(body["data"]["battery"]["percent"], 64)

    def test_orchestrator_plan_and_dry_run(self):
        status, body = self.get("/orchestrator/plan")
        self.assertTrue(body["ok"])
        plans = body["data"]["plans"]
        self.assertTrue(plans)
        self.assertTrue(all("reason" in plan for plan in plans))
        status, body = self.post("/orchestrator/dry-run", {"allow_remote": False})
        self.assertTrue(body["data"]["dry_run"])

    def test_network_and_guests(self):
        status, body = self.get("/network")
        self.assertEqual(len(body["data"]["networks"]), 1)
        status, body = self.get("/guests")
        users = {user["id"]: user for user in body["data"]["users"]}
        self.assertIn("can_use_remote_compute", users["gerard"]["effective_permissions"])
        self.assertNotIn("can_use_remote_compute", users["alumno"]["effective_permissions"])

    def test_external_nodes_endpoint(self):
        status, body = self.get("/external-nodes")
        self.assertEqual(body["data"]["nodes"][0]["id"], "loop-node")
        self.assertTrue(body["data"]["nodes"][0]["health"]["reachable"])

    def test_logs_endpoint(self):
        status, body = self.get("/logs?limit=5")
        self.assertTrue(body["ok"])
        self.assertIsInstance(body["data"]["events"], list)

    def test_teleport_dry_run_via_api(self):
        status, body = self.post("/teleport/dry-run", {"vm_name": "hg-source"})
        self.assertTrue(body["ok"])
        self.assertTrue(body["data"]["dry_run"])

    def test_teleport_start_requires_confirm(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post("/teleport/start", {"vm_name": "hg-source", "mode": "dry_run"})
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertFalse(body["ok"])
        self.assertIn("confirm", body["error"]["message"])

    def test_error_envelope_format(self):
        with self.assertRaises(HTTPError) as ctx:
            self.get("/vms/ghost-vm")
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertFalse(body["ok"])
        self.assertIsNone(body["data"])
        self.assertEqual(body["error"]["code"], "HYPERGERY_ERROR")
        self.assertIn("ghost-vm", body["error"]["message"])

    def test_serve_api_refuses_non_loopback_without_opt_in(self):
        from hypergery_ubuntu.v1.api import serve_api
        from hypergery_ubuntu.v1.errors import HyperGeryError

        with self.assertRaises(HyperGeryError) as ctx:
            serve_api(ApiContext(settings=V1Settings()), host="0.0.0.0", port=0)
        self.assertIn("non-loopback", str(ctx.exception))
        # Loopback binds are always fine (don't actually serve_forever here —
        # construction is enough; we only assert the guard does not trip).

    def test_unknown_endpoint_is_a_clean_error(self):
        with self.assertRaises(HTTPError) as ctx:
            self.get("/warp-drive")
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("Unknown endpoint", body["error"]["message"])


if __name__ == "__main__":
    unittest.main()
