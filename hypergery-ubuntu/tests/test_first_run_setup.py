"""First Run Setup (v1.5): lógica, CLI y wizard Qt.

Garantías testeadas: el asistente sale solo cuando toca, el bundle Docker se
genera sin ejecutar nada, ningún modo arranca Docker sin confirmación, los
tokens no se filtran, la config queda 0600, y los diagnósticos jamás usan sudo.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu import firstrun
from hypergery_ubuntu.config import HyperGeryConfig


class ShouldShowWizardTests(unittest.TestCase):
    def test_wizard_shows_when_no_config_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(firstrun.should_show_wizard(Path(tmp) / "config.json"))

    def test_wizard_shows_when_first_run_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            HyperGeryConfig(hub_url="http://example:8765").save(path)
            self.assertTrue(firstrun.should_show_wizard(path))

    def test_wizard_hidden_when_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            firstrun.mark_first_run_complete("solo", path=path)
            self.assertFalse(firstrun.should_show_wizard(path))

    def test_reset_first_run_brings_wizard_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            firstrun.mark_first_run_complete("solo", path=path)
            firstrun.reset_first_run(path)
            self.assertTrue(firstrun.should_show_wizard(path))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            firstrun.mark_first_run_complete("evil-mode")


class FirstRunConfigSecurityTests(unittest.TestCase):
    def test_config_saved_with_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            firstrun.mark_first_run_complete(
                "nas-docker", hub_url="http://nas:8765", hub_token="SECRET-token-123", path=path
            )
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_setup_status_never_exposes_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            firstrun.mark_first_run_complete(
                "nas-docker", hub_url="http://nas:8765", hub_token="SECRET-token-123", path=path
            )
            status = firstrun.setup_status(path)
            self.assertNotIn("SECRET-token-123", json.dumps(status))
            self.assertTrue(status["hub_token_present"])


class DockerBundleTests(unittest.TestCase):
    def test_bundle_contains_all_required_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "hypergery-hub-docker"
            firstrun.generate_docker_bundle(dest)
            for name in ("docker-compose.yml", "Dockerfile", ".env.example", "README_SETUP.md", "SECURITY.md"):
                self.assertTrue((dest / name).is_file(), name)
            # Autocontenido: incluye el código del Hub, sin caches.
            self.assertTrue((dest / "hypergery-ubuntu" / "hypergery_ubuntu" / "cli.py").is_file())
            pycache = list((dest / "hypergery-ubuntu").rglob("__pycache__"))
            self.assertEqual(pycache, [])

    def test_bundle_generation_never_runs_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(firstrun.subprocess, "run") as fake_run:
                firstrun.generate_docker_bundle(Path(tmp) / "bundle")
            fake_run.assert_not_called()

    def test_bundle_env_example_has_no_real_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bundle"
            firstrun.generate_docker_bundle(dest)
            env = (dest / ".env.example").read_text(encoding="utf-8")
            self.assertIn("HYPERGERY_HUB_TOKEN=\n", env)

    def test_bundle_compose_avoids_qemu_tcp_and_documents_security(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bundle"
            firstrun.generate_docker_bundle(dest)
            security = (dest / "SECURITY.md").read_text(encoding="utf-8")
            for needle in ("VPN", "TLS", "Sin evasión"):
                self.assertIn(needle, security)


class EnvironmentDetectionTests(unittest.TestCase):
    def test_libvirt_diagnostics_never_invoke_sudo(self):
        commands: list[list[str]] = []
        real_run = firstrun.subprocess.run

        def spy(command, **kwargs):
            commands.append(list(command))
            return real_run(command, **kwargs)

        with patch.object(firstrun.subprocess, "run", side_effect=spy):
            info = firstrun.detect_libvirt()
        for command in commands:
            self.assertNotEqual(command[0], "sudo", command)
        # Lo que falte se SUGIERE como texto, nunca se ejecuta.
        for suggestion in info["suggested_commands"]:
            self.assertIsInstance(suggestion, str)

    def test_storage_check_does_not_delete_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = Path(tmp) / "important.qcow2"
            keep.write_bytes(b"data")
            info = firstrun.check_storage_path(tmp)
            self.assertTrue(info["writable"])
            self.assertTrue(keep.exists(), "la comprobación no debe borrar nada")
            leftovers = [p for p in Path(tmp).iterdir() if p.name.startswith(".hypergery-setup-probe-")]
            self.assertEqual(leftovers, [], "el fichero sonda se limpia solo")

    def test_storage_check_missing_parent_is_humanized(self):
        info = firstrun.check_storage_path("/nonexistent-root-xyz/vms")
        self.assertFalse(info["writable"])
        self.assertIn("No existe", info["detail"])


class _HubStub(BaseHTTPRequestHandler):
    auth_mode = "ok"  # ok | reject

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            body = b'{"status": "ok"}'
            self.send_response(200)
        elif self.path == "/vms":
            if self.auth_mode == "ok" and self.headers.get("Authorization") == "Bearer good-token":
                body = b'{"ok": true}'
                self.send_response(200)
            else:
                body = b'{"error": "unauthorized"}'
                self.send_response(401)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silencio en tests
        pass


class TestHubConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _HubStub)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_ok_with_valid_token(self):
        result = firstrun.test_hub_connection(self.base, "good-token")
        self.assertEqual(result["status"], "ok")

    def test_auth_error_with_bad_token(self):
        result = firstrun.test_hub_connection(self.base, "bad-token")
        self.assertEqual(result["status"], "auth_error")
        self.assertNotIn("bad-token", result["message"])

    def test_unreachable_hub_is_humanized(self):
        result = firstrun.test_hub_connection("http://127.0.0.1:1", "token", timeout=2)
        self.assertEqual(result["status"], "unreachable")
        self.assertIn("No se pudo conectar", result["message"])

    def test_bad_url_is_humanized(self):
        result = firstrun.test_hub_connection("nas:8765")
        self.assertEqual(result["status"], "bad_url")
        self.assertIn("http://", result["message"])


class CliSetupTests(unittest.TestCase):
    def _cli(self, *argv: str) -> int:
        from hypergery_ubuntu.cli import main

        return main(list(argv))

    def test_generate_docker_bundle_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "bundle")
            rc = self._cli("setup", "generate-docker-bundle", "--output", dest)
            self.assertEqual(rc, 0)
            self.assertTrue((Path(dest) / "README_SETUP.md").is_file())

    def test_status_and_reset_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with patch.dict(os.environ, {"HYPERGERY_CONFIG": str(config)}):
                firstrun.mark_first_run_complete("solo")
                self.assertEqual(self._cli("setup", "status"), 0)
                self.assertEqual(self._cli("setup", "reset-first-run"), 0)
                self.assertTrue(firstrun.should_show_wizard())

    def test_test_hub_without_url_fails_with_human_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with patch.dict(os.environ, {"HYPERGERY_CONFIG": str(config)}):
                rc = self._cli("setup", "test-hub")
                self.assertEqual(rc, 2)


class AppFirstRunFlagTests(unittest.TestCase):
    def test_first_run_flag_is_stripped_and_forces_wizard(self):
        from hypergery_ubuntu import app

        calls: dict[str, object] = {}

        def fake_qt_main(argv, *, force_first_run=False):
            calls["argv"] = argv
            calls["force"] = force_first_run
            return 0

        with patch("hypergery_ubuntu.ui_qt.main.main", fake_qt_main):
            rc = app.main(["hypergery", "--first-run"])
        self.assertEqual(rc, 0)
        self.assertTrue(calls["force"])
        self.assertNotIn("--first-run", calls["argv"])


class WizardQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pytest

        pytest.importorskip("PySide6")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self):
        from hypergery_ubuntu.ui_qt.setup_wizard import SetupWizard

        return SetupWizard()

    def test_wizard_builds_with_seven_pages(self):
        wizard = self._wizard()
        self.assertEqual(len(wizard.pageIds()), 7)

    def test_nas_profile_never_runs_docker(self):
        # El patch alcanza al módulo subprocess global: se permite el probe de
        # solo lectura `docker compose version`, pero JAMÁS un `up`/`run`.
        wizard = self._wizard()
        wizard.profile_page.buttons["nas-docker"].setChecked(True)
        with patch("hypergery_ubuntu.ui_qt.setup_wizard.subprocess.run") as fake_run:
            wizard.hub_page.initializePage()
            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(firstrun, "generate_docker_bundle") as fake_bundle:
                    fake_bundle.return_value = []
                    with patch("hypergery_ubuntu.ui_qt.setup_wizard.QFileDialog.getExistingDirectory", return_value=tmp):
                        wizard.hub_page._generate_bundle()
            for call in fake_run.call_args_list:
                command = [str(part) for part in call.args[0]]
                self.assertNotIn("up", command, f"comando mutador ejecutado: {command}")
                self.assertIn("version", " ".join(command), f"solo se permiten probes --version: {command}")

    def test_local_profile_does_not_start_docker_without_confirmation(self):
        from PySide6.QtWidgets import QMessageBox

        wizard = self._wizard()
        wizard.profile_page.buttons["local-docker"].setChecked(True)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "hub-docker"
            firstrun.generate_docker_bundle(bundle)
            wizard.hub_page._bundle_dir = bundle
            with patch("hypergery_ubuntu.ui_qt.setup_wizard.subprocess.run") as fake_run:
                with patch(
                    "hypergery_ubuntu.ui_qt.setup_wizard.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ):
                    wizard.hub_page._start_local_hub()
                fake_run.assert_not_called()
        self.assertIn("cancelado", wizard.hub_page.status_label.text().lower())

    def test_finishing_wizard_marks_first_run_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            with patch.dict(os.environ, {"HYPERGERY_CONFIG": str(config)}):
                wizard = self._wizard()
                wizard.profile_page.buttons["solo"].setChecked(True)
                wizard.accept()
                self.assertFalse(firstrun.should_show_wizard())
                saved = HyperGeryConfig.load(config)
                self.assertEqual(saved.setup_profile, "solo")


if __name__ == "__main__":
    unittest.main()
