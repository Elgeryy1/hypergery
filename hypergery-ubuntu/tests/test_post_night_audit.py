"""Regresiones de la auditoría post-noche (docs/audit/POST_NIGHT_AUDIT.md).

HG-BUG-0025 bind directo a vfio-pci sin parada dura · 0026 tokens de usuario
sin comparación constante · 0027 API v1 sin rate limit · 0021 excepciones
silenciosas en el agente · 0013 import sin preflight de espacio.
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.v1.errors import HyperGeryError

from .test_migration import FakeBackend

# Nota release/v1.5.0-rc: GpuBindHardStopTests (HG-BUG-0025) se queda en las
# ramas v1.7/audit — el GPU passthrough no entra en v1.5.


class ConstantTimeTokenTests(unittest.TestCase):
    """HG-BUG-0026: resolve() de tokens de usuario en tiempo constante."""

    def test_resolve_roundtrip_still_works(self):
        from hypergery_ubuntu.v1.auth import ApiTokenStore

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiTokenStore(Path(tmp) / "tokens.json")
            token = store.issue("gerard")
            self.assertEqual(store.resolve(token), "gerard")
            self.assertIsNone(store.resolve("wrong-token"))
            self.assertIsNone(store.resolve(""))
            store.revoke("gerard")
            self.assertIsNone(store.resolve(token))

    def test_resolve_uses_constant_time_comparison(self):
        from hypergery_ubuntu.v1.auth import ApiTokenStore

        source = inspect.getsource(ApiTokenStore.resolve)
        self.assertIn("compare_digest", source)
        self.assertNotIn(".get(token)", source)


class V1ApiRateLimitTests(unittest.TestCase):
    """HG-BUG-0027: anti fuerza bruta también en el API v1."""

    @classmethod
    def setUpClass(cls):
        from hypergery_ubuntu.registry.auth import AuthRateLimiter
        from hypergery_ubuntu.v1.api import ApiContext, ApiServer
        from hypergery_ubuntu.v1.auth import ApiTokenStore
        from hypergery_ubuntu.v1.rbac import UserStore

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        context = ApiContext(user_store=UserStore(root / "users.json"))
        cls.server = ApiServer(
            ("127.0.0.1", 0),
            context,
            auth_token="owner-token",
            token_store=ApiTokenStore(root / "tokens.json"),
        )
        cls.server.auth_limiter = AuthRateLimiter(max_failures=3, window_seconds=60)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def _get(self, token: str | None) -> int:
        request = Request(self.base + "/labs", method="GET")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=10) as response:
                return response.status
        except HTTPError as exc:
            exc.read()
            return exc.code

    def test_repeated_auth_failures_get_429(self):
        for _ in range(3):
            self.assertEqual(self._get("wrong"), 401)
        self.assertEqual(self._get("wrong"), 429)
        # Incluso el token bueno queda bloqueado hasta que expire la ventana.
        self.assertEqual(self._get("owner-token"), 429)


class AgentSilentExceptionTests(unittest.TestCase):
    """HG-BUG-0021: ningún `except Exception` mudo (sin log) en el agente."""

    def test_agent_has_no_silent_swallows(self):
        source = Path(inspect.getfile(__import__("hypergery_ubuntu.agent", fromlist=["agent"]))).read_text(
            encoding="utf-8"
        )
        silent = re.findall(r"except Exception:\n\s+pass\b", source)
        self.assertEqual(silent, [], "except Exception: pass sin log en agent.py")

    def test_new_v1_modules_have_no_silent_swallows(self):
        import hypergery_ubuntu.v1 as v1

        v1_dir = Path(v1.__file__).parent
        offenders = []
        for module in ("backups.py", "backup_verifier.py", "live_migration.py", "migration_engine.py",
                       "progress.py", "auth.py"):
            source = (v1_dir / module).read_text(encoding="utf-8")
            if re.search(r"except Exception:\n\s+pass\b", source):
                offenders.append(module)
        self.assertEqual(offenders, [])


class ImportSpacePreflightTests(unittest.TestCase):
    """HG-BUG-0013: el import comprueba espacio libre ANTES de copiar."""

    def test_import_fails_early_without_space(self):
        from hypergery_ubuntu import migration

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            export = migration.export_vm_package(backend, "hg-source", root / "nas", target_vm_name="hg-tight")
            fake_usage = type("Usage", (), {"total": 10, "used": 9, "free": 1024})()
            with patch.object(migration.shutil, "disk_usage", return_value=fake_usage):
                with self.assertRaises(HyperGeryError) as ctx:
                    migration.import_vm_package(backend, export["package_dir"], target_vm_name="hg-tight")
            self.assertIn("free space", str(ctx.exception))
            self.assertFalse((backend.vms_dir / "hg-tight").exists(), "no se creó nada en el destino")

    def test_import_with_space_still_works(self):
        from hypergery_ubuntu import migration

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = FakeBackend(root)
            export = migration.export_vm_package(backend, "hg-source", root / "nas", target_vm_name="hg-roomy")
            result = migration.import_vm_package(backend, export["package_dir"], target_vm_name="hg-roomy")
            self.assertEqual(result["target_vm_name"], "hg-roomy")


if __name__ == "__main__":
    unittest.main()
