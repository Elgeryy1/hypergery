"""Hub robusto v1.1: HG-BUG-0005 (WAL/busy_timeout), 0006 (TTL), 0010 (upload)."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.registry import RegistryServer, RegistryStore
from hypergery_ubuntu.registry.server import default_max_upload_bytes
from hypergery_ubuntu.registry.store import (
    DEFAULT_COMMAND_TTL_SECONDS,
    MAX_COMMAND_TTL_SECONDS,
    MIN_COMMAND_TTL_SECONDS,
    SQLITE_BUSY_TIMEOUT_MS,
)


class SqliteRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_database_uses_wal_journal_mode(self):
        with closing(self.store.connect()) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")

    def test_connections_set_busy_timeout(self):
        with closing(self.store.connect()) as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(int(timeout), SQLITE_BUSY_TIMEOUT_MS)

    def test_concurrent_writers_do_not_hit_database_is_locked(self):
        # U3: varios agentes registrando/reportando a la vez contra el Hub.
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for i in range(10):
                    self.store.register_host({"host_id": f"host-{idx}", "hostname": f"h{idx}"})
                    self.store.report_vms(
                        {
                            "host_id": f"host-{idx}",
                            "vms": [{"vm_name": f"vm-{idx}-{i}", "state": "running"}],
                        }
                    )
            except Exception as exc:  # noqa: BLE001 — el test recoge cualquier fallo
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [], [str(e) for e in errors])
        self.assertEqual(len(self.store.list_hosts()), 8)


class CommandTtlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.store.register_host({"host_id": "node-a", "hostname": "a"})

    def tearDown(self):
        self.tmp.cleanup()

    def _force_expire(self, command_id: str) -> None:
        past = (datetime.now(UTC) - timedelta(seconds=5)).replace(microsecond=0).isoformat()
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            conn.execute("UPDATE commands SET expires_at = ? WHERE command_id = ?", (past, command_id))
            conn.commit()

    def test_commands_get_a_default_ttl(self):
        command = self.store.create_command({"target_host_id": "node-a", "command_type": "ping"})
        created = datetime.fromisoformat(command["created_at"])
        expires = datetime.fromisoformat(command["expires_at"])
        self.assertEqual((expires - created).total_seconds(), DEFAULT_COMMAND_TTL_SECONDS)

    def test_ttl_is_clamped_to_sane_bounds(self):
        low = self.store.create_command({"target_host_id": "node-a", "command_type": "ping", "ttl_seconds": 1})
        high = self.store.create_command({"target_host_id": "node-a", "command_type": "ping", "ttl_seconds": 10**9})
        for command, expected in ((low, MIN_COMMAND_TTL_SECONDS), (high, MAX_COMMAND_TTL_SECONDS)):
            created = datetime.fromisoformat(command["created_at"])
            expires = datetime.fromisoformat(command["expires_at"])
            self.assertEqual((expires - created).total_seconds(), expected)

    def test_invalid_ttl_is_rejected(self):
        with self.assertRaises(HyperGeryError):
            self.store.create_command({"target_host_id": "node-a", "command_type": "ping", "ttl_seconds": "soon"})

    def test_expired_command_is_never_delivered(self):
        command = self.store.create_command({"target_host_id": "node-a", "command_type": "vm_force_off"})
        self._force_expire(command["command_id"])
        self.assertEqual(self.store.pending_commands_for_host("node-a"), [])
        stored = self.store.get_command(command["command_id"])
        self.assertEqual(stored["status"], "failed")
        self.assertTrue(stored["result"].get("expired"))
        self.assertIn("expired", stored["result"].get("error", "").lower())

    def test_expired_command_result_cannot_be_set(self):
        command = self.store.create_command({"target_host_id": "node-a", "command_type": "ping"})
        self._force_expire(command["command_id"])
        with self.assertRaises(HyperGeryError):
            self.store.set_command_result(command["command_id"], {"status": "done", "result": {"ok": True}})

    def test_running_command_is_not_expired(self):
        command = self.store.create_command({"target_host_id": "node-a", "command_type": "ping"})
        self.store.set_command_result(command["command_id"], {"status": "running", "result": {}})
        self._force_expire(command["command_id"])
        stored = self.store.get_command(command["command_id"])
        self.assertEqual(stored["status"], "running")
        done = self.store.set_command_result(command["command_id"], {"status": "done", "result": {"ok": True}})
        self.assertEqual(done["status"], "done")

    def test_fresh_command_still_delivered(self):
        command = self.store.create_command({"target_host_id": "node-a", "command_type": "ping"})
        pending = self.store.pending_commands_for_host("node-a")
        self.assertEqual([c["command_id"] for c in pending], [command["command_id"]])


class UploadLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self.tmp.name) / "staging"
        store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(
            ("127.0.0.1", 0),
            store,
            staging_dir=self.staging,
            max_upload_bytes=1024,
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

    def _put(self, rel: str, data: bytes, headers: dict | None = None) -> int:
        request = Request(f"{self.base_url}/packages/mig-x/{rel}", data=data, method="PUT")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status
        except HTTPError as exc:
            return exc.code

    def test_upload_within_limit_succeeds(self):
        self.assertEqual(self._put("ok.bin", b"x" * 512), 201)
        self.assertEqual((self.staging / "mig-x" / "ok.bin").stat().st_size, 512)

    def test_upload_over_limit_is_rejected_with_413(self):
        self.assertEqual(self._put("big.bin", b"x" * 2048), 413)
        self.assertFalse((self.staging / "mig-x" / "big.bin").exists())

    def test_empty_upload_is_rejected(self):
        self.assertEqual(self._put("empty.bin", b""), 400)
        self.assertFalse((self.staging / "mig-x" / "empty.bin").exists())

    def test_upload_without_free_disk_space_is_rejected_with_507(self):
        fake_usage = type("Usage", (), {"total": 10, "used": 9, "free": 1})()
        with patch("hypergery_ubuntu.registry.server.shutil.disk_usage", return_value=fake_usage):
            self.assertEqual(self._put("nospace.bin", b"x" * 512), 507)
        self.assertFalse((self.staging / "mig-x" / "nospace.bin").exists())

    def test_default_limit_comes_from_environment(self):
        with patch.dict("os.environ", {"HYPERGERY_HUB_MAX_UPLOAD_MIB": "2"}):
            self.assertEqual(default_max_upload_bytes(), 2 * 1024 * 1024)
        with patch.dict("os.environ", {"HYPERGERY_HUB_MAX_UPLOAD_MIB": "not-a-number"}):
            self.assertEqual(default_max_upload_bytes(), 64 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
