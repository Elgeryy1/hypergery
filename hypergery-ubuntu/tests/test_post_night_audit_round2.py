"""Auditoría post-noche, 2ª tanda: HG-BUG-0028 (journal de migración),
0029 (límite de long-polls), 0019 (temp de preview), 0023 (humanizar CLI)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import CommandResult, HyperGeryError
from hypergery_ubuntu.migration_journal import MigrationJournal


class MigrationJournalTests(unittest.TestCase):
    def _journal(self, tmp: str) -> MigrationJournal:
        return MigrationJournal(Path(tmp) / "journal.json")

    def test_begin_blocks_start_and_clear_unblocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = self._journal(tmp)
            journal.begin("web01", target_uri="qemu+ssh://portatil/system", operation_id="op-1")
            with self.assertRaises(HyperGeryError) as ctx:
                journal.assert_startable("web01")
            self.assertIn("unconfirmed migration", str(ctx.exception))
            self.assertEqual([e["vm_name"] for e in journal.list()], ["web01"])
            self.assertTrue(journal.clear("web01"))
            journal.assert_startable("web01")  # ya no lanza
            self.assertFalse(journal.clear("web01"))

    def test_unrelated_vm_is_startable(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = self._journal(tmp)
            journal.begin("web01", target_uri="qemu+ssh://x/system")
            journal.assert_startable("other-vm")

    def test_corrupt_journal_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            path.write_text("{ not json", encoding="utf-8")
            journal = MigrationJournal(path)
            self.assertEqual(journal.list(), [])
            journal.assert_startable("web01")


class BackendStartVmJournalTests(unittest.TestCase):
    def test_start_vm_refuses_vm_with_in_flight_migration(self):
        from hypergery_ubuntu.backend import HyperGeryBackend

        class _Backend(HyperGeryBackend):
            def __init__(self):
                self.calls = []

            def virsh(self, args, *, timeout=120, check=True):
                self.calls.append(list(args))
                return CommandResult(["virsh", *args], 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            journal_path = Path(tmp) / "migration_journal.json"
            MigrationJournal(journal_path).begin("hg-locked", target_uri="qemu+ssh://x/system")
            backend = _Backend()
            with patch("hypergery_ubuntu.migration_journal.journal_path", return_value=journal_path):
                with self.assertRaises(HyperGeryError):
                    backend.start_vm("hg-locked")
                # nunca llegó a invocar virsh start
                self.assertEqual(backend.calls, [])
                # una VM sin entrada arranca con normalidad
                backend.start_vm("hg-free")
                self.assertEqual(backend.calls, [["start", "hg-free"]])


class LiveMigrationJournalIntegrationTests(unittest.TestCase):
    """El journal se marca al migrar y se limpia/retiene según el resultado."""

    def _migrator(self, host, journal, **plan_kwargs):
        from hypergery_ubuntu.v1.live_migration import LiveMigrationPlan, LiveMigrator
        from hypergery_ubuntu.v1.progress import ProgressChannel

        plan = LiveMigrationPlan(vm_name="web01", target_uri="qemu+ssh://portatil/system", **plan_kwargs)
        return LiveMigrator(host, plan, channel=ProgressChannel(), journal=journal)

    def test_success_with_undefine_clears_journal(self):
        from tests.test_v15_live_migration import _happy_host

        with tempfile.TemporaryDirectory() as tmp:
            journal = MigrationJournal(Path(tmp) / "j.json")
            host = _happy_host()
            result = self._migrator(host, journal, shared_storage=True).run()
            self.assertTrue(result["ok"], result)
            self.assertEqual(journal.list(), [], "origen eliminado → journal limpio")

    def test_keep_source_definition_retains_journal_entry(self):
        from tests.test_v15_live_migration import _happy_host

        with tempfile.TemporaryDirectory() as tmp:
            journal = MigrationJournal(Path(tmp) / "j.json")
            host = _happy_host()
            result = self._migrator(host, journal, shared_storage=True, undefine_source_on_success=False).run()
            self.assertTrue(result["ok"], result)
            self.assertEqual([e["vm_name"] for e in journal.list()], ["web01"],
                             "se conserva el origen → el journal sigue protegiendo")

    def test_failed_migration_with_running_source_clears_journal(self):
        from tests.test_v15_live_migration import _fail, _happy_host

        with tempfile.TemporaryDirectory() as tmp:
            journal = MigrationJournal(Path(tmp) / "j.json")
            host = _happy_host(migrate_result=_fail("operation failed: migration unexpectedly failed"))
            host.script[("S", "domstate", "web01")] = lambda: CommandResult(["virsh"], 0, "running\n", "")
            host.script[("T", "domstate", "web01")] = lambda: CommandResult(["virsh"], 0, "paused\n", "")
            result = self._migrator(host, journal, shared_storage=True).run()
            self.assertFalse(result["ok"])
            self.assertEqual(journal.list(), [], "origen vivo de nuevo → journal limpio")


class LongPollLimitTests(unittest.TestCase):
    def test_too_many_long_polls_get_503(self):
        from hypergery_ubuntu.v1.api import ApiContext, ApiServer
        from hypergery_ubuntu.v1.progress import get_progress_channel

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        op = get_progress_channel().start("test-longpoll", operation_id="op-longpoll-test")
        get_progress_channel().update(op, percent=1)
        context = ApiContext(user_store=__import__("hypergery_ubuntu.v1.rbac", fromlist=["UserStore"]).UserStore(Path(tmp.name) / "u.json"))
        server = ApiServer(("127.0.0.1", 0), context, auth_token="")  # auth off para aislar el 503
        # Sin huecos disponibles: cualquier long-poll debe dar 503.
        server.long_poll_slots = threading.BoundedSemaphore(1)
        server.long_poll_slots.acquire()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(f"{base}/progress/{op}?since=0&timeout=1", method="GET")
            try:
                with urlopen(request, timeout=10) as response:
                    status = response.status
            except HTTPError as exc:
                exc.read()
                status = exc.code
            self.assertEqual(status, 503)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class PreviewTempDirTests(unittest.TestCase):
    def test_previews_use_runtime_dir_and_cleanup_removes_stale(self):
        from hypergery_ubuntu.ui_qt import screenshot

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"XDG_RUNTIME_DIR": tmp}):
                preview_dir = screenshot._preview_dir()
                self.assertTrue(str(preview_dir).startswith(tmp))
                self.assertEqual(preview_dir.stat().st_mode & 0o777, 0o700)
                # Simula una captura huérfana de un proceso muerto.
                (preview_dir / "hg-preview-stale.ppm").write_bytes(b"x")
                (preview_dir / "unrelated.txt").write_bytes(b"y")
                removed = screenshot.cleanup_stale_previews()
                self.assertEqual(removed, 1)
                self.assertFalse((preview_dir / "hg-preview-stale.ppm").exists())
                self.assertTrue((preview_dir / "unrelated.txt").exists())


class CliHumanizedErrorsTests(unittest.TestCase):
    def test_cli_humanizes_virsh_errors(self):
        import io
        from contextlib import redirect_stderr

        from hypergery_ubuntu import cli

        def boom(_backend, _args):
            raise HyperGeryError("error: Failed to start domain hg01: Cannot access storage file /nas/win.iso")

        buf = io.StringIO()
        with patch.object(cli, "HyperGeryBackend"), patch.object(cli, "create_vm", boom), redirect_stderr(buf):
            rc = cli.main(["create-vm", "--name", "hg01", "--iso", "/nas/win.iso"])
        self.assertEqual(rc, 2)
        out = buf.getvalue()
        self.assertIn("No se pudo encender la máquina", out)
        self.assertIn("Detalle técnico", out)


if __name__ == "__main__":
    unittest.main()
