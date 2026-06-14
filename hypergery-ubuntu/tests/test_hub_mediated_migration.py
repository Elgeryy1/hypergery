"""Flujo OFICIAL de migración v1.5: mediada por el Hub (visión de producto).

Origen → Hub Docker del NAS → Destino. El Hub crea/almacena el job, autoriza
(token), guarda el paquete en su staging, encola el comando para el agente del
destino y registra el estado de cada fase. Estos tests consolidan las
garantías de extremo a extremo; la live migration directa por libvirt
(qemu+ssh) es un modo avanzado aparte (test_v15_live_migration.py).
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.migration import (
    HUB_PACKAGE_PREFIX,
    import_vm_package,
    start_remote_migration,
    validate_vm_package,
)

from .test_migration import FakeBackend, FakeRegistryClient


def _start_hub_migration(backend, client):
    return start_remote_migration(
        backend,
        client,
        "hg-source",
        nas_path="",
        source_host_id="origen",
        target_host_id="target",
        transfer="hub",
    )


class HubJobLifecycleTests(unittest.TestCase):
    """El Hub crea el job, recibe el estado por fases y encola al destino."""

    def test_job_is_created_and_tracked_in_hub(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp))
            client = FakeRegistryClient()
            result = _start_hub_migration(backend, client)

            migration = client.migrations[result["migration_id"]]
            # Tras subir el paquete y encolar el comando, el job queda
            # esperando a que el agente del destino lo recoja.
            self.assertEqual(migration["status"], "waiting_target")
            self.assertEqual(migration["strategy"], "hub_transfer")
            # El job encola UN comando de import para el host destino.
            self.assertEqual(len(client.created_commands), 1)
            command = client.created_commands[0]
            self.assertEqual(command["target_host_id"], "target")
            self.assertEqual(result["command_id"], command["command_id"])

    def test_source_uploads_package_to_hub_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp))
            client = FakeRegistryClient()
            result = _start_hub_migration(backend, client)

            files = client.uploaded_packages[result["migration_id"]]
            self.assertIn("manifest.json", files)
            self.assertTrue(any(name.endswith(".qcow2") for name in files))
            # El paquete viaja por el Hub: la referencia es hub://, no una
            # ruta host-a-host.
            self.assertTrue(result["package_dir"].startswith(HUB_PACKAGE_PREFIX))

    def test_target_downloads_package_from_hub_and_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeBackend(Path(tmp) / "src")
            client = FakeRegistryClient()
            result = _start_hub_migration(source, client)

            # Lado destino: descarga del staging del Hub e import local.
            incoming = Path(tmp) / "dst" / "incoming"
            client.download_package(result["migration_id"], incoming)
            target = FakeBackend(Path(tmp) / "dst")
            imported = import_vm_package(target, incoming, target_vm_name="hg-moved")
            self.assertEqual(imported["target_vm_name"], "hg-moved")

    def test_checksums_are_validated_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeBackend(Path(tmp) / "src")
            client = FakeRegistryClient()
            result = _start_hub_migration(source, client)

            # Corrupción en tránsito/staging → el destino debe rechazar.
            files = client.uploaded_packages[result["migration_id"]]
            disk_name = next(name for name in files if name.endswith(".qcow2"))
            files[disk_name] = files[disk_name] + b"CORRUPTED"

            incoming = Path(tmp) / "dst" / "incoming"
            client.download_package(result["migration_id"], incoming)
            validation = validate_vm_package(incoming)
            self.assertFalse(validation["ok"])
            self.assertIn("checksum", "; ".join(validation["errors"]).lower())

            target = FakeBackend(Path(tmp) / "dst")
            with self.assertRaises(HyperGeryError):
                import_vm_package(target, incoming, target_vm_name="hg-moved")
            self.assertFalse((target.vms_dir / "hg-moved").exists(), "destino limpio tras fallo")


class SourceSafetyTests(unittest.TestCase):
    """El origen NUNCA se libera hasta que el destino está confirmado."""

    def test_source_is_never_deleted_by_the_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeBackend(Path(tmp))
            client = FakeRegistryClient()
            result = _start_hub_migration(backend, client)
            self.assertFalse(result["source_will_be_deleted"])
            # El disco y la VM de origen siguen intactos tras empaquetar+subir.
            self.assertTrue(backend.disk.exists())

    def test_target_failure_leaves_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeBackend(Path(tmp) / "src")
            client = FakeRegistryClient()
            result = _start_hub_migration(source, client)

            # El destino falla el import (paquete corrupto).
            files = client.uploaded_packages[result["migration_id"]]
            manifest = next(name for name in files if name == "manifest.json")
            files[manifest] = b"{not json"
            incoming = Path(tmp) / "dst" / "incoming"
            client.download_package(result["migration_id"], incoming)
            target = FakeBackend(Path(tmp) / "dst")
            with self.assertRaises(HyperGeryError):
                import_vm_package(target, incoming, target_vm_name="hg-moved")

            # Origen: VM y disco intactos; el paquete sigue en el Hub para
            # reintentar — nada que recuperar en el origen.
            self.assertTrue(source.disk.exists())
            self.assertIn(result["migration_id"], client.uploaded_packages)


class HubAuthRequiredTests(unittest.TestCase):
    """Sin token no hay migración: el Hub real rechaza upload/comandos (v1.2)."""

    def setUp(self):
        from hypergery_ubuntu.registry.server import RegistryServer
        from hypergery_ubuntu.registry.store import RegistryStore

        self.tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self.tmp.name) / "staging"
        store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(
            ("127.0.0.1", 0), store, staging_dir=self.staging, auth_token="hgtest-token"
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _status(self, method: str, path: str, *, token: str | None, payload: dict | None = None) -> int:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=5) as response:
                return response.status
        except HTTPError as exc:
            exc.read()
            return exc.code

    def test_migration_endpoints_require_token(self):
        for method, path in (
            ("POST", "/migrations/mig-x"),
            ("POST", "/packages/mig-x/manifest.json"),
            ("GET", "/packages/mig-x"),
            ("POST", "/commands"),
            ("GET", "/migrations/mig-x"),
        ):
            self.assertEqual(self._status(method, path, token=None), 401, f"{method} {path} sin token")
            self.assertEqual(self._status(method, path, token="wrong-token"), 401, f"{method} {path} token malo")


class JournalDoubleActiveTests(unittest.TestCase):
    """El journal persistente impide arrancar una VM con migración en vuelo."""

    def test_journal_blocks_start_while_migration_in_flight(self):
        from hypergery_ubuntu.migration_journal import MigrationJournal

        with tempfile.TemporaryDirectory() as tmp:
            journal = MigrationJournal(Path(tmp) / "journal.json")
            journal.begin("hg-moved", target_uri="qemu+ssh://gery@portatil/system", operation_id="op-1")
            with self.assertRaises(HyperGeryError) as ctx:
                journal.assert_startable("hg-moved")
            self.assertIn("migra", str(ctx.exception).lower())
            # Confirmado el desenlace, la entrada se libera y se puede arrancar.
            journal.clear("hg-moved")
            journal.assert_startable("hg-moved")


if __name__ == "__main__":
    unittest.main()
