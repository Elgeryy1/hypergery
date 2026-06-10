"""v1.4: telemetría de agente → Hub, orchestrator apply, dashboard y API
companion (acciones seguras por VM con RBAC + lab scoping)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.registry import RegistryStore
from hypergery_ubuntu.v1.errors import OrchestratorError
from hypergery_ubuntu.v1.orchestrator import PlacementPlan, apply_plan
from hypergery_ubuntu.v1.providers import VmInfo


class HostTelemetryStorageTests(unittest.TestCase):
    def test_heartbeat_telemetry_is_stored_and_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistryStore(Path(tmp) / "registry.sqlite3")
            sample = {"cpu_percent": 12.5, "ram_free_mib": 9000, "battery_percent": 80}
            store.register_host({"host_id": "pc", "hostname": "pc", "telemetry": sample})
            host = store.get_host("pc")
            self.assertEqual(host["telemetry"], sample)
            # Hosts antiguos sin telemetría devuelven {}.
            store.register_host({"host_id": "old", "hostname": "old"})
            self.assertEqual(store.get_host("old")["telemetry"], {})


class AgentTelemetryTests(unittest.TestCase):
    def test_host_payload_includes_local_telemetry_sample(self):
        from hypergery_ubuntu.agent import AgentConfig, HyperGeryAgent

        from .test_agent import FakeBackend, FakeClient

        agent = HyperGeryAgent(AgentConfig(host_id="local", name="Local"), backend=FakeBackend(), client=FakeClient())
        payload = agent.host_payload()
        self.assertIn("telemetry", payload)
        self.assertGreater(payload["telemetry"].get("ram_total_mib", 0), 0)


class _FakeTeleportEngine:
    def __init__(self):
        self.calls = []

    def teleport_vm(self, vm_name, *, mode=None, target_host_id="", **kwargs):
        self.calls.append({"vm": vm_name, "mode": mode, "target": target_host_id})
        return {"ok": True, "vm": vm_name, "target": target_host_id}


class ApplyPlanTests(unittest.TestCase):
    def _move_plan(self) -> PlacementPlan:
        return PlacementPlan(
            lab_id="asr-lab",
            vm_id="dc01",
            current_host="laptop",
            target_host="pc",
            reason="test",
            confidence=0.8,
            actions=[{"kind": "teleport", "vm_id": "dc01", "from_host": "laptop", "to_host": "pc", "mode": "suspend_copy"}],
        )

    def test_apply_requires_confirm(self):
        with self.assertRaises(OrchestratorError):
            apply_plan(self._move_plan(), teleport_engine=_FakeTeleportEngine(), confirm=False)

    def test_stay_plan_is_a_noop(self):
        plan = PlacementPlan(
            lab_id="asr-lab",
            vm_id="dc01",
            current_host="laptop",
            target_host="laptop",
            reason="stay",
            confidence=0.9,
            actions=[{"kind": "stay", "vm_id": "dc01", "host": "laptop"}],
        )
        engine = _FakeTeleportEngine()
        result = apply_plan(plan, teleport_engine=engine, confirm=True)
        self.assertEqual(engine.calls, [])
        self.assertTrue(result["applied"][0]["ok"])

    def test_move_plan_delegates_to_teleport_engine(self):
        engine = _FakeTeleportEngine()
        result = apply_plan(self._move_plan(), teleport_engine=engine, confirm=True)
        self.assertEqual(engine.calls, [{"vm": "dc01", "mode": "suspend_copy", "target": "pc"}])
        self.assertEqual(result["applied"][0]["kind"], "teleport")

    def test_move_plan_without_engine_fails(self):
        with self.assertRaises(OrchestratorError):
            apply_plan(self._move_plan(), teleport_engine=None, confirm=True)

    def test_unknown_action_kind_fails(self):
        plan = self._move_plan()
        plan.actions = [{"kind": "rm-rf", "vm_id": "dc01"}]
        with self.assertRaises(OrchestratorError):
            apply_plan(plan, teleport_engine=_FakeTeleportEngine(), confirm=True)


class _CompanionBackend:
    """Backend local mínimo: conoce dc01 y registra las acciones."""

    def __init__(self):
        self.calls = []

    def get_vm(self, name):
        if name != "dc01":
            raise RuntimeError("not local")
        return object()

    def start_vm(self, name):
        self.calls.append(("start", name))

    def shutdown_vm(self, name):
        self.calls.append(("shutdown", name))

    def create_snapshot(self, name, snapshot_name, description=""):
        self.calls.append(("snapshot", name, snapshot_name))


class _FakeHubClient:
    def __init__(self):
        self.queued = []

    def list_vms(self):
        return []

    def queue_vm_power_command(self, host_id, vm_name, action):
        self.queued.append((host_id, vm_name, action))
        return {"command_id": "cmd-1", "status": "pending"}


class CompanionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hypergery_ubuntu.v1.api import ApiContext, ApiServer
        from hypergery_ubuntu.v1.auth import ApiTokenStore
        from hypergery_ubuntu.v1.rbac import User, UserStore
        from hypergery_ubuntu.v1.settings import V1Settings

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.backend = _CompanionBackend()
        cls.hub_client = _FakeHubClient()
        user_store = UserStore(root / "users.json")
        user_store.add_user(User(id="alumno", role="Guest", assigned_labs=["asr-lab"]))
        user_store.add_user(User(id="intruso", role="Guest", assigned_labs=["otro-lab"]))
        user_store.add_user(User(id="operador", role="Operator"))
        user_store.add_user(User(id="admin", role="Admin"))
        cls.token_store = ApiTokenStore(root / "api_tokens.json")
        cls.tokens = {uid: cls.token_store.issue(uid) for uid in ("alumno", "intruso", "operador", "admin")}
        settings = V1Settings(offline_mode=True)
        cls.engine = _FakeTeleportEngine()
        context = ApiContext(
            settings=settings,
            user_store=user_store,
            backend=cls.backend,
            hub_client=cls.hub_client,
            teleport_engine=cls.engine,
            local_vms=lambda: [
                VmInfo(id="dc01", ram_mb=2048, status="running", host_id="laptop", lab_id="asr-lab"),
                VmInfo(id="remota", ram_mb=1024, status="running", host_id="pc", lab_id="asr-lab"),
            ],
        )
        cls.server = ApiServer(("127.0.0.1", 0), context, auth_token="owner-token", token_store=cls.token_store)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def setUp(self):
        self.backend.calls.clear()
        self.hub_client.queued.clear()

    def _post(self, path, token, payload=None):
        data = json.dumps(payload or {}).encode("utf-8")
        request = Request(self.base + path, data=data, method="POST")
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def _get(self, path, token):
        request = Request(self.base + path, method="GET")
        request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_guest_can_start_vm_in_their_lab(self):
        status, body = self._post("/vms/dc01/start", self.tokens["alumno"])
        self.assertEqual(status, 200, body)
        self.assertEqual(self.backend.calls, [("start", "dc01")])

    def test_guest_outside_the_lab_gets_403(self):
        status, _ = self._post("/vms/dc01/start", self.tokens["intruso"])
        self.assertEqual(status, 403)
        self.assertEqual(self.backend.calls, [])

    def test_acpi_shutdown_is_exposed_but_nothing_destructive(self):
        status, _ = self._post("/vms/dc01/shutdown", self.tokens["alumno"])
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.calls, [("shutdown", "dc01")])
        status, _ = self._post("/vms/dc01/force-off", self.tokens["admin"])
        self.assertEqual(status, 400, "force-off no existe en el companion (endpoint desconocido)")

    def test_snapshot_requires_confirm_and_name(self):
        status, _ = self._post("/vms/dc01/snapshot", self.tokens["alumno"], {"snapshot_name": "s1"})
        self.assertEqual(status, 400)
        status, _ = self._post("/vms/dc01/snapshot", self.tokens["alumno"], {"confirm": True})
        self.assertEqual(status, 400)
        status, _ = self._post("/vms/dc01/snapshot", self.tokens["alumno"], {"confirm": True, "snapshot_name": "s1"})
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.calls, [("snapshot", "dc01", "s1")])

    def test_remote_vm_action_queues_hub_command(self):
        status, body = self._post("/vms/remota/start", self.tokens["admin"])
        self.assertEqual(status, 200, body)
        self.assertEqual(self.hub_client.queued, [("pc", "remota", "start")])
        self.assertTrue(body["data"]["queued"])

    def test_unknown_vm_is_a_clean_400(self):
        status, _ = self._post("/vms/no-existe/start", self.tokens["admin"])
        self.assertEqual(status, 400)

    def test_orchestrator_apply_requires_remote_compute_and_teleport(self):
        plan = {
            "vm_id": "dc01",
            "target_host": "laptop",
            "actions": [{"kind": "stay", "vm_id": "dc01", "host": "laptop"}],
        }
        status, _ = self._post("/orchestrator/apply", self.tokens["alumno"], {"plan": plan, "confirm": True})
        self.assertEqual(status, 403)
        status, body = self._post("/orchestrator/apply", self.tokens["admin"], {"plan": plan, "confirm": True})
        self.assertEqual(status, 200, body)
        status, _ = self._post("/orchestrator/apply", self.tokens["admin"], {"plan": plan})
        self.assertEqual(status, 400, "sin confirm no se aplica")

    def test_dashboard_aggregates_health(self):
        status, body = self._get("/dashboard", self.tokens["operador"])
        self.assertEqual(status, 200, body)
        dashboard = body["data"]["dashboard"]
        for key in ("hosts", "local_telemetry", "alerts", "vms_total", "vms_by_state", "battery"):
            self.assertIn(key, dashboard)
        self.assertEqual(dashboard["vms_total"], 2)
        self.assertEqual(dashboard["vms_by_state"], {"running": 2})


if __name__ == "__main__":
    unittest.main()
