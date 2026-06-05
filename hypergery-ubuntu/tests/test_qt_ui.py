import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

FAKE_ONLINE_HOST = {
    "host_id": "target",
    "status": "online",
    "hostname": "target.local",
    "kvm_ok": True,
    "libvirt_ok": True,
    "ram_total_mib": 8192,
    "ram_free_mib": 4096,
    "disk_free_mib": 20000,
    "active_vms": [],
}


def migration_fake_backend():
    try:
        from tests.test_migration import FakeBackend
    except ModuleNotFoundError:
        from test_migration import FakeBackend
    return FakeBackend

if HAS_PYSIDE6:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog

    from hypergery_ubuntu.ui_qt.dialogs import FILE_DIALOG_OPTIONS
    from hypergery_ubuntu.ui_qt.main import configure_qt_application, configure_qt_environment


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtUiTests(unittest.TestCase):
    def test_qt_uses_non_native_file_dialogs(self):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)

        configure_qt_application()

        self.assertTrue(QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs))
        self.assertTrue(FILE_DIALOG_OPTIONS & QFileDialog.Option.DontUseNativeDialog)

    def test_wayland_sessions_use_xcb_by_default(self):
        env = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
        with patch.dict("os.environ", env, clear=True):
            configure_qt_environment()

            self.assertEqual("xcb", os.environ["QT_QPA_PLATFORM"])
            self.assertEqual("gtk3", os.environ["QT_QPA_PLATFORMTHEME"])
            self.assertEqual("Fusion", os.environ["QT_STYLE_OVERRIDE"])

    def test_existing_qpa_platform_is_respected(self):
        env = {
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
            "QT_QPA_PLATFORM": "wayland",
            "QT_QPA_PLATFORMTHEME": "custom",
            "QT_STYLE_OVERRIDE": "CustomStyle",
        }
        with patch.dict("os.environ", env, clear=True):
            configure_qt_environment()

            self.assertEqual("wayland", os.environ["QT_QPA_PLATFORM"])
            self.assertEqual("custom", os.environ["QT_QPA_PLATFORMTHEME"])
            self.assertEqual("CustomStyle", os.environ["QT_STYLE_OVERRIDE"])

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_main_window_constructor_does_not_list_vms(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()

            backend_cls.return_value.list_vms.assert_not_called()
            window.close()
        self.assertIsNotNone(app)

    def test_live_migration_dialog_blocks_running_vm(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp), state="running")
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))
            dialog.nas_path.setText(str(Path(tmp) / "nas"))
            dialog.target_host.setCurrentIndex(0)
            dialog.run_preflight()

            self.assertFalse(dialog.package_button.isEnabled())
            self.assertIn("Running VM migration is blocked", dialog.result_view.toPlainText())
            dialog.close()
        self.assertIsNotNone(app)

    def test_live_migration_dialog_shows_hub_unavailable(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import HyperGeryError
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.side_effect = HyperGeryError("registry offline")
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            self.assertFalse(dialog.package_button.isEnabled())
            self.assertIn("Hub not reachable", dialog.result_view.toPlainText())
            self.assertIn("HYPERGERY_HUB_URL", dialog.result_view.toPlainText())
            self.assertIn("docker compose", dialog.result_view.toPlainText())
            self.assertIn("registry offline", dialog.result_view.toPlainText())
            dialog.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_hosts_panel_uses_hub_labels(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertEqual(window.remote_status_label.text(), "Hub not loaded")
            self.assertIn("HyperGery Hub", window.remote_detail.placeholderText())
            self.assertTrue(hasattr(window, "hub_status_label"))
            window.close()
        self.assertIsNotNone(app)

    def test_live_migration_dialog_uses_config_defaults(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.config import HyperGeryConfig
        from hypergery_ubuntu.backend import HyperGeryError
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            HyperGeryConfig(
                hub_url="http://config-hub.local:8765",
                host_id="source-from-config",
                nas_staging_path=str(Path(tmp) / "nas"),
            ).save(config_path)
            env = {"HYPERGERY_CONFIG": str(config_path)}
            backend = MigrationFakeBackend(Path(tmp))
            with patch.dict(os.environ, env, clear=True), patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.side_effect = HyperGeryError("hub offline")
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))
            self.assertEqual(dialog.registry_url.text(), "http://config-hub.local:8765")
            self.assertEqual(dialog.source_host_id.text(), "source-from-config")
            self.assertEqual(dialog.nas_path.text(), str(Path(tmp) / "nas"))
            dialog.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
