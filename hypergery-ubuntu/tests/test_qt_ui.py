import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

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
    def test_app_shell_sidebar_navigation(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            sections = [window.sidebar_nav.item(i).text() for i in range(window.sidebar_nav.count())]
            self.assertEqual(
                sections,
                [
                    "Dashboard",
                    "Virtual Machines",
                    "Labs",
                    "Templates",
                    "Remote Hosts",
                    "Migrations",
                    "Diagnostics",
                    "Settings",
                ],
            )
            self.assertEqual(window.sidebar_nav.currentItem().text(), "Virtual Machines")
            self.assertEqual(window.main_tabs.currentIndex(), 0)
            self.assertFalse(window.main_tabs.tabBar().isVisible())

            window.sidebar_nav.setCurrentRow(sections.index("Remote Hosts"))
            self.assertEqual(window.main_tabs.currentIndex(), 2)
            window.sidebar_nav.setCurrentRow(sections.index("Dashboard"))
            self.assertEqual(window.main_tabs.currentIndex(), window.dashboard_page_index)
            window.sidebar_nav.setCurrentRow(sections.index("Diagnostics"))
            self.assertEqual(window.main_tabs.currentIndex(), window.diagnostics_page_index)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_app_shell_settings_entry_opens_dialog_and_restores_selection(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            sections = [window.sidebar_nav.item(i).text() for i in range(window.sidebar_nav.count())]
            with patch.object(window, "app_settings") as app_settings:
                window.sidebar_nav.setCurrentRow(sections.index("Settings"))
                app_settings.assert_called_once()
            self.assertEqual(window.sidebar_nav.currentItem().text(), "Virtual Machines")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_top_bar_status_chips_follow_hub_status(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertEqual(window.hub_chip.text(), "Hub: not checked")
            window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=2)
            self.assertEqual(window.hub_chip.text(), "Hub: online")
            self.assertTrue(window.nas_chip.text().startswith("NAS: "))
            window.render_hub_status([], reachable=False)
            self.assertEqual(window.hub_chip.text(), "Hub: offline")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_dashboard_health_cards_update_from_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertEqual(window.dash_hub_big.text(), "Not checked")

            window.render_vms([
                VmSummary(name="vm-a", state="running", lab_id="default-lab", ram_mib=1024, vcpus=1),
                VmSummary(name="vm-b", state="shut off", lab_id="default-lab", ram_mib=1024, vcpus=1),
            ])
            self.assertEqual(window.dash_vm_big.text(), "1")
            self.assertIn("1 shutoff", window.dash_vm_sub.text())
            self.assertIn("2 total", window.dash_vm_sub.text())

            window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=5)
            self.assertEqual(window.dash_hub_big.text(), "Online")
            self.assertIn("5 VM record(s)", window.dash_hub_sub.text())
            self.assertEqual(window.dash_hosts_big.text(), "1 / 1")

            window.render_hub_status([], reachable=False)
            self.assertEqual(window.dash_hub_big.text(), "Offline")
            warnings = [
                window.dash_warnings_layout.itemAt(i).widget().text()
                for i in range(window.dash_warnings_layout.count())
            ]
            self.assertTrue(any("Hub is not responding" in text for text in warnings))
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_dashboard_last_migration_from_worker_result(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertIn("No migrations", window.dash_migration_label.text())
            window.render_remote_hosts({
                "hosts": [FAKE_ONLINE_HOST],
                "vm_count": 1,
                "migrations": [{"migration_id": "hg-mig-1", "vm_name": "hg-src", "status": "done"}],
            })
            self.assertIn("hg-mig-1", window.dash_migration_label.text())
            self.assertIn("done", window.dash_migration_label.text())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_hosts_page_renders_host_cards_with_badges(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        offline_host = {
            "host_id": "ubuntu-hyperv-old",
            "name": "Old Host",
            "status": "offline",
            "last_seen": "2026-06-01T10:00:00",
            "kvm_ok": True,
            "libvirt_ok": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_remote_hosts({
                "hosts": [FAKE_ONLINE_HOST, offline_host],
                "vm_count": 4,
                "migrations": [],
                "latency_ms": 12,
            })
            self.assertEqual(len(window._host_card_frames), 2)
            self.assertEqual(window.hub_latency_label.text(), "12 ms")
            self.assertEqual(window.hub_status_label.text(), "ONLINE")

            online_texts = [
                label.text() for label in window._host_card_frames[0].findChildren(QLabel)
            ]
            self.assertIn("KVM OK", online_texts)
            self.assertIn("libvirt OK", online_texts)
            self.assertTrue(any(text == "ONLINE" for text in online_texts))

            offline_texts = [
                label.text() for label in window._host_card_frames[1].findChildren(QLabel)
            ]
            self.assertTrue(any(text == "OFFLINE" for text in offline_texts))
            self.assertTrue(any("No heartbeat since 2026-06-01T10:00:00" in text for text in offline_texts))
            self.assertEqual(window._host_card_frames[1].objectName(), "hostCardOffline")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_hosts_empty_and_hub_offline_states(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_remote_hosts({"hosts": [], "vm_count": 0, "migrations": []})
            texts = [
                label.text()
                for label in window.remote_cards_scroll.widget().findChildren(QLabel)
            ]
            self.assertTrue(any("No hosts registered yet" in text for text in texts))

            window.render_hub_offline("connection refused")
            texts = [
                label.text()
                for label in window.remote_cards_scroll.widget().findChildren(QLabel)
            ]
            self.assertTrue(any("Hub not reachable" in text for text in texts))
            self.assertTrue(any("docker compose" in text for text in texts))
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_hosts_card_selection_enables_test_button(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_remote_hosts({"hosts": [FAKE_ONLINE_HOST], "vm_count": 1, "migrations": []})
            self.assertIsNone(window.selected_remote_host_index)
            window.update_actions()
            self.assertFalse(window.test_remote_button.isEnabled())
            window._select_host_card(0)
            self.assertEqual(window.selected_remote_host_index, 0)
            self.assertEqual(window._host_card_frames[0].objectName(), "hostCardSelected")
            self.assertTrue(window.test_remote_button.isEnabled())
            window.close()
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

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_hosts_render_updates_vm_count_from_worker_result(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_remote_hosts({"hosts": [FAKE_ONLINE_HOST], "vm_count": 3})

            self.assertEqual(window.hub_vm_count_label.text(), "3")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_render_hub_status_does_not_fetch_vm_inventory(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=4)

            registry_cls.assert_not_called()
            self.assertEqual(window.hub_vm_count_label.text(), "4")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_render_hub_status_marks_missing_inventory_unavailable(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=None)

            self.assertEqual(window.hub_vm_count_label.text(), "unavailable")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_diagnostics_page_has_header_and_run_doctor(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertTrue(hasattr(window, "run_doctor_button"))
            self.assertEqual(window.run_doctor_button.text(), "Run Doctor")
            self.assertFalse(window.copy_report_button.isEnabled())
            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertIn("Diagnostics", texts)
            self.assertTrue(any("Run Doctor to check your environment" in text for text in texts))
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_diagnostics_renders_grouped_results_and_counts(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.doctor import DoctorItem
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            items = [
                DoctorItem("OK", "/dev/kvm", "exists and accessible"),
                DoctorItem("OK", "virsh", "/usr/bin/virsh"),
                DoctorItem("WARN", "docker compose", "docker not found"),
                DoctorItem("FAIL", "hub reachable", "connection refused", True),
            ]
            window.render_doctor_results({"items": items, "exit_code": 1})
            self.assertEqual(window.diag_ok_chip.text(), "2 OK")
            self.assertEqual(window.diag_warn_chip.text(), "1 WARN")
            self.assertEqual(window.diag_fail_chip.text(), "1 FAIL")
            self.assertIn("exit code 1", window.diag_overall_label.text())
            self.assertTrue(window.copy_report_button.isEnabled())

            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertIn("Local Virtualization", texts)
            self.assertIn("Tooling", texts)
            self.assertIn("Docker", texts)
            self.assertTrue(any("CRITICAL" in text for text in texts))

            # Copy with results populates clipboard without crashing.
            window.copy_doctor_report()
            self.assertIn("hub reachable", QApplication.clipboard().text())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_diagnostics_failure_shows_callout_and_copy_is_safe(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_doctor_results({"error": "boom"})
            self.assertFalse(window.copy_report_button.isEnabled())
            self.assertIn("failed", window.diag_overall_label.text().lower())
            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertTrue(any("Doctor failed to run: boom" in text for text in texts))
            # Copy Report without results must not crash.
            window.copy_doctor_report()
            window.close()
        self.assertIsNotNone(app)

    def test_app_settings_dialog_has_sections_and_source_chips(self):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.dialogs import AppSettingsDialog

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HYPERGERY_CONFIG": str(Path(tmp) / "config.json"),
                "HYPERGERY_HUB_URL": "http://env-hub.local:8765",
            }
            with patch.dict(os.environ, env, clear=False):
                dialog = AppSettingsDialog(object())

            sections = [dialog.section_nav.item(i).text() for i in range(dialog.section_nav.count())]
            self.assertEqual(
                sections,
                ["General", "Hub", "Host Agent", "NAS", "VM Defaults", "Console", "Appearance", "Advanced"],
            )
            self.assertEqual(dialog.pages.count(), 8)
            dialog.section_nav.setCurrentRow(sections.index("Hub"))
            self.assertEqual(dialog.pages.currentIndex(), sections.index("Hub"))

            chip_names = {label.objectName() for label in dialog.findChildren(QLabel)}
            self.assertIn("srcChipEnv", chip_names)
            self.assertIn("srcChipDefault", chip_names)
            dialog.close()
        self.assertIsNotNone(app)

    def test_app_settings_omits_unchanged_env_derived_hub_url(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import AppSettingsDialog

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HYPERGERY_CONFIG": str(Path(tmp) / "config.json"),
                "HYPERGERY_HUB_URL": "http://env-hub.local:8765",
            }
            with patch.dict(os.environ, env, clear=False):
                dialog = AppSettingsDialog(object())

            self.assertNotIn("hub_url", dialog.values())
            dialog.close()
        self.assertIsNotNone(app)

    def test_app_settings_rejects_invalid_hub_url(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import AppSettingsDialog

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HYPERGERY_CONFIG": str(Path(tmp) / "config.json")}, clear=False):
            dialog = AppSettingsDialog(object())
            dialog.hub_url.setText("foo")
            dialog.validate_and_accept()

            self.assertNotEqual(dialog.result(), int(QDialog.DialogCode.Accepted))
            self.assertIn("http:// or https://", dialog.status.text())
            dialog.close()
        self.assertIsNotNone(app)

    def test_app_settings_values_include_user_edits(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import AppSettingsDialog

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HYPERGERY_CONFIG": str(Path(tmp) / "config.json")}, clear=False):
            dialog = AppSettingsDialog(object())
            dialog.hub_url.setText("http://edited-hub.local:8765")

            self.assertEqual(dialog.values()["hub_url"], "http://edited-hub.local:8765")
            dialog.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_app_settings_save_oserror_shows_error(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            fake_dialog = Mock()
            fake_dialog.exec.return_value = QDialog.DialogCode.Accepted
            fake_dialog.values.return_value = {"hub_url": "http://saved-hub.local:8765"}
            with (
                patch("hypergery_ubuntu.ui_qt.main_window.AppSettingsDialog", return_value=fake_dialog),
                patch("hypergery_ubuntu.config.HyperGeryConfig.save", side_effect=OSError("disk full")),
                patch.object(window, "show_error") as show_error,
            ):
                window.app_settings()

            show_error.assert_called_once()
            self.assertIn("Cannot save HyperGery settings", show_error.call_args[0][0])
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_vm_page_header_chips_and_empty_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertEqual(window.vm_page_title.text(), "Virtual Machines")
            self.assertIn("KVM/libvirt", window.vm_page_subtitle.text())
            self.assertEqual(window.vm_table.columnCount(), 7)

            window.render_vms([])
            self.assertEqual(window.vm_stack.currentIndex(), 1)
            self.assertIn("Create your first VM from an ISO", window.vm_empty_subtitle.text())

            window.render_vms([
                VmSummary(name="dc01", state="running", lab_id="lab", ram_mib=4096, vcpus=2, graphics="vnc"),
                VmSummary(name="cl01", state="shut off", lab_id="lab", ram_mib=2048, vcpus=1, graphics="spice"),
                VmSummary(name="p01", state="paused", lab_id="lab", ram_mib=1024, vcpus=1),
            ])
            self.assertEqual(window.vm_table.rowCount(), 3)
            states = [window.vm_table.item(row, 1).text() for row in range(3)]
            self.assertEqual(states, ["RUNNING", "SHUTOFF", "PAUSED"])
            self.assertEqual(window.vm_table.item(0, 6).text(), "VNC")

            # Destructive actions keep the danger style; core attributes survive.
            self.assertEqual(window.force_button.objectName(), "dangerButton")
            self.assertEqual(window.delete_button.objectName(), "dangerButton")
            for attr in ("start_button", "console_button", "external_console_button", "snapshots_button",
                         "clone_button", "migrate_button", "settings_button"):
                self.assertTrue(hasattr(window, attr))

            # Console detail card shows console status and Host Key.
            console_text = window.detail_views["Console"].toPlainText()
            self.assertIn("Integrated console", console_text)
            self.assertIn("Right Ctrl", console_text)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_labs_sidebar_shows_banner_without_breaking_page(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            sections = [window.sidebar_nav.item(i).text() for i in range(window.sidebar_nav.count())]
            window.sidebar_nav.setCurrentRow(sections.index("Labs"))
            self.assertEqual(window.main_tabs.currentIndex(), 0)
            self.assertEqual(window.vm_page_title.text(), "Labs")
            self.assertIn("v0.7.x", window.labs_mode_banner.text())
            window.sidebar_nav.setCurrentRow(sections.index("Virtual Machines"))
            self.assertEqual(window.vm_page_title.text(), "Virtual Machines")
            self.assertFalse(window.labs_mode_banner.isVisible())
            window.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_steps_and_microcopy(self):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            self.assertEqual(len(dialog._step_labels), 6)
            self.assertEqual(
                list(dialog.STEPS),
                ["Select VM", "Target Host", "Options", "Preflight", "Progress", "Result"],
            )
            texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("NAS Clone Migration", texts)
            self.assertIn("not live RAM migration", texts)
            self.assertIn("Source VM and source disks will not be deleted.", texts)
            self.assertIn("Must be shut off", texts)
            dialog.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_running_vm_blocks_next_with_callout(self):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp), state="running")
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            self.assertEqual(dialog.current_step(), 0)
            self.assertFalse(dialog.next_button.isEnabled())
            texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("Running VM migration is blocked", texts)
            dialog.go_next()
            self.assertEqual(dialog.current_step(), 0)
            dialog.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_offline_target_blocks_and_preflight_enables_start(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        offline_host = dict(FAKE_ONLINE_HOST, host_id="offline-target", status="offline")
        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            nas = Path(tmp) / "nas"
            nas.mkdir()
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [offline_host, FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))
            dialog.nas_path.setText(str(nas))
            dialog.source_host_id.setText("source-host")

            # Offline target blocks Next on the Target Host step and blocks preflight.
            dialog._set_step(1)
            dialog.target_host.setCurrentIndex(0)
            self.assertFalse(dialog.next_button.isEnabled())
            dialog.run_preflight()
            self.assertIn("offline", dialog.error_label.text().lower())
            self.assertFalse(dialog.package_button.isEnabled())

            # Online, ready target passes preflight and enables Start Migration.
            dialog.target_host.setCurrentIndex(1)
            dialog._set_step(3)
            dialog.run_preflight()
            self.assertTrue(dialog.package_button.isEnabled(), dialog.error_label.text())
            self.assertIn("Source will be deleted: False", dialog.result_view.toPlainText())
            self.assertIn("UUID and MAC will be regenerated", dialog.result_view.toPlainText())
            dialog.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_progress_result_and_copy_safety(self):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            # Copy buttons must be safe without any migration data.
            dialog.copy_migration_id()
            self.assertIn("No migration ID", dialog.error_label.text())
            dialog.copy_progress_logs()
            dialog.copy_summary()
            self.assertIn("No result", dialog.error_label.text())

            # Progress page renders migration id and state list.
            dialog.last_result = {"migration_id": "hg-mig-77", "package_dir": "/nas/migrations/hg-mig-77"}
            dialog.migration_id_label.setText("Migration ID: hg-mig-77")
            dialog._render_progress_states("importing")
            states = [
                dialog.progress_states_layout.itemAt(i).widget().text()
                for i in range(dialog.progress_states_layout.count())
            ]
            self.assertTrue(any("importing" in text and "▶" in text for text in states))
            dialog.copy_migration_id()
            self.assertEqual(QApplication.clipboard().text(), "hg-mig-77")

            # Result success page shows source intact and UUID/MAC regenerated.
            dialog._show_result_success({"status": "done"})
            self.assertEqual(dialog.current_step(), 5)
            texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("Source VM remains untouched", texts)
            self.assertIn("regenerated UUID and MAC", texts)
            self.assertIn("conserved", texts)

            # Closing the wizard must not touch the backend destructively.
            dialog.reject()
            self.assertFalse(hasattr(backend, "deleted_vms"))
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
