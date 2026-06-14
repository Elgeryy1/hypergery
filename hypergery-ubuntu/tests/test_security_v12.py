"""v1.2 seguridad: HG-BUG-0001 (Hub auth) + TD-5 (RBAC enforced, escalada)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.registry import RegistryClient, RegistryServer, RegistryStore
from hypergery_ubuntu.registry.auth import AuthRateLimiter, load_or_create_hub_token

TOKEN = "secret-hub-token"


class HubAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(("127.0.0.1", 0), self.store, auth_token=TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _get(self, path: str, token: str | None) -> int:
        request = Request(self.base_url + path, method="GET")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status
        except HTTPError as exc:
            return exc.code

    def test_health_is_open(self):
        self.assertEqual(self._get("/health", None), 200)

    def test_requests_without_token_are_rejected(self):
        self.assertEqual(self._get("/hosts", None), 401)

    def test_wrong_token_is_rejected_and_audited(self):
        self.assertEqual(self._get("/hosts", "nope"), 401)
        events = self.store.list_events()
        self.assertTrue(any(e["kind"] == "auth_failure" for e in events), events)

    def test_correct_token_is_accepted(self):
        self.assertEqual(self._get("/hosts", TOKEN), 200)

    def test_client_sends_bearer_token(self):
        client = RegistryClient(self.base_url, token=TOKEN)
        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(client.request("GET", "/hosts"), {"hosts": []})

    def test_client_without_token_fails(self):
        client = RegistryClient(self.base_url, token="")
        with self.assertRaises(HyperGeryError):
            client.request("GET", "/hosts")

    def test_repeated_failures_are_rate_limited(self):
        self.server.auth_limiter = AuthRateLimiter(max_failures=3, window_seconds=60)
        for _ in range(3):
            self.assertEqual(self._get("/hosts", "wrong"), 401)
        self.assertEqual(self._get("/hosts", "wrong"), 429)
        # Incluso el token correcto queda bloqueado hasta que expire la ventana.
        self.assertEqual(self._get("/hosts", TOKEN), 429)

    def test_uploads_require_token(self):
        request = Request(self.base_url + "/packages/mig-a/file.bin", data=b"x" * 10, method="PUT")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=10)
        self.assertEqual(ctx.exception.code, 401)


class HubTokenFileTests(unittest.TestCase):
    def test_token_is_created_persisted_and_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.sqlite3"
            token = load_or_create_hub_token(db_path)
            token_file = Path(tmp) / "hub_token"
            self.assertTrue(token_file.is_file())
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(load_or_create_hub_token(db_path), token)

    def test_environment_token_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"HYPERGERY_HUB_TOKEN": "from-env"}):
                self.assertEqual(load_or_create_hub_token(Path(tmp) / "db.sqlite3"), "from-env")

    def test_server_with_empty_token_disables_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistryStore(Path(tmp) / "registry.sqlite3")
            server = RegistryServer(("127.0.0.1", 0), store, auth_token="")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                with urlopen(Request(f"http://{host}:{port}/hosts"), timeout=10) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


class V1ApiRbacTests(unittest.TestCase):
    """Escalada de privilegios: el token define la identidad y RBAC el límite."""

    @classmethod
    def setUpClass(cls):
        from hypergery_ubuntu.v1.api import ApiContext, ApiServer
        from hypergery_ubuntu.v1.auth import ApiTokenStore
        from hypergery_ubuntu.v1.rbac import User, UserStore

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.user_store = UserStore(root / "users.json")
        cls.user_store.add_user(User(id="gerard", role="Admin"))
        cls.user_store.add_user(User(id="alumno", role="Guest", assigned_labs=["asr-lab"]))
        cls.user_store.add_user(
            User(id="listillo", role="Guest", extra_permissions=["can_manage_guests", "can_use_remote_compute"])
        )
        cls.user_store.add_user(User(id="operador", role="Operator"))
        cls.token_store = ApiTokenStore(root / "api_tokens.json")
        cls.tokens = {user: cls.token_store.issue(user) for user in ("gerard", "alumno", "listillo", "operador")}
        context = ApiContext(user_store=cls.user_store)
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

    def _call(self, method: str, path: str, token: str | None, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + path, data=data, method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_health_is_open(self):
        status, _ = self._call("GET", "/health", None)
        self.assertEqual(status, 200)

    def test_requests_without_token_get_401(self):
        status, body = self._call("GET", "/labs", None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "auth_required")

    def test_owner_token_is_superadmin(self):
        status, _ = self._call("GET", "/guests", "owner-token")
        self.assertEqual(status, 200)

    def test_guest_can_read_labs_but_not_guests(self):
        status, _ = self._call("GET", "/labs", self.tokens["alumno"])
        self.assertEqual(status, 200)
        status, body = self._call("GET", "/guests", self.tokens["alumno"])
        self.assertEqual(status, 403)

    def test_guest_cannot_teleport_or_use_remote_compute(self):
        status, _ = self._call("POST", "/teleport/start", self.tokens["alumno"], {"confirm": True})
        self.assertEqual(status, 403)
        status, _ = self._call("POST", "/orchestrator/dry-run", self.tokens["alumno"], {})
        self.assertEqual(status, 403)

    def test_guest_escalation_via_extra_permissions_is_blocked(self):
        # GUEST_FORBIDDEN gana incluso con extra_permissions explícitos.
        status, _ = self._call("GET", "/guests", self.tokens["listillo"])
        self.assertEqual(status, 403)
        status, _ = self._call("POST", "/orchestrator/dry-run", self.tokens["listillo"], {})
        self.assertEqual(status, 403)

    def test_operator_passes_authz_for_teleport(self):
        # Operator tiene can_teleport: la autorización pasa y el fallo es el
        # 400 del engine no configurado, no un 403.
        status, body = self._call("POST", "/teleport/dry-run", self.tokens["operador"], {"vm_name": "x"})
        self.assertEqual(status, 400, body)

    def test_admin_can_manage_guests(self):
        status, _ = self._call("GET", "/guests", self.tokens["gerard"])
        self.assertEqual(status, 200)

    def test_revoked_token_stops_working(self):
        from hypergery_ubuntu.v1.rbac import User

        self.user_store.add_user(User(id="temporal", role="Operator"))
        token = self.token_store.issue("temporal")
        status, _ = self._call("GET", "/labs", token)
        self.assertEqual(status, 200)
        self.token_store.revoke("temporal")
        status, _ = self._call("GET", "/labs", token)
        self.assertEqual(status, 401)

    def test_token_store_file_is_0600(self):
        self.assertEqual(self.token_store.path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
