import importlib.util
import json
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
            self.assertIn("No se puede contactar con el Hub", dialog.result_view.toPlainText())
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
                    "Inicio",
                    "Máquinas virtuales",
                    "Laboratorios",
                    "Plantillas",
                    "Otros equipos",
                    "Migraciones",
                    "Tareas remotas",
                    "Centro de control",
                    "Diagnóstico",
                    "Ajustes",
                ],
            )
            self.assertEqual(window.sidebar_nav.currentItem().text(), "Máquinas virtuales")
            self.assertEqual(window.main_tabs.currentIndex(), 0)
            self.assertFalse(window.main_tabs.tabBar().isVisible())

            window.sidebar_nav.setCurrentRow(sections.index("Otros equipos"))
            self.assertEqual(window.main_tabs.currentIndex(), 2)
            window.sidebar_nav.setCurrentRow(sections.index("Inicio"))
            self.assertEqual(window.main_tabs.currentIndex(), window.dashboard_page_index)
            with patch.object(window, "refresh_commands") as refresh_commands:
                window.sidebar_nav.setCurrentRow(sections.index("Tareas remotas"))
                refresh_commands.assert_called_once()
            self.assertEqual(window.main_tabs.currentIndex(), window.commands_page_index)
            window.sidebar_nav.setCurrentRow(sections.index("Diagnóstico"))
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
                window.sidebar_nav.setCurrentRow(sections.index("Ajustes"))
                app_settings.assert_called_once()
            self.assertEqual(window.sidebar_nav.currentItem().text(), "Máquinas virtuales")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_top_bar_status_chips_follow_hub_status(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertEqual(window.hub_chip.text(), "Hub: sin comprobar")
            window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=2)
            self.assertEqual(window.hub_chip.text(), "Hub: en línea")
            self.assertTrue(window.nas_chip.text().startswith("NAS: "))
            window.render_hub_status([], reachable=False)
            self.assertEqual(window.hub_chip.text(), "Hub: sin conexión")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_dashboard_health_cards_update_from_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            backend_cls.return_value.recent_logs.return_value = ""
            window = MainWindow()
            self.assertEqual(window.dash_hub_big.text(), "Sin comprobar")

            window.render_vms([
                VmSummary(name="vm-a", state="running", lab_id="default-lab", ram_mib=1024, vcpus=1),
                VmSummary(name="vm-b", state="shut off", lab_id="default-lab", ram_mib=1024, vcpus=1),
            ])
            self.assertEqual(window.dash_vm_big.text(), "1")
            self.assertIn("1 apagadas", window.dash_vm_sub.text())
            self.assertIn("2 en total", window.dash_vm_sub.text())

            window.render_hub_status([FAKE_ONLINE_HOST], reachable=True, vm_count=5)
            self.assertEqual(window.dash_hub_big.text(), "En línea")
            self.assertIn("5 máquina(s) registrada(s)", window.dash_hub_sub.text())
            self.assertEqual(window.dash_hosts_big.text(), "1 / 1")

            window.render_hub_status([], reachable=False)
            self.assertEqual(window.dash_hub_big.text(), "Sin conexión")
            warnings = [
                window.dash_warnings_layout.itemAt(i).widget().text()
                for i in range(window.dash_warnings_layout.count())
            ]
            self.assertTrue(any("no responde" in text for text in warnings))
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_dashboard_last_migration_from_worker_result(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            self.assertIn("Todavía no se ha movido", window.dash_migration_label.text())
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
            self.assertEqual(window.hub_status_label.text(), "EN LÍNEA")

            online_texts = [
                label.text() for label in window._host_card_frames[0].findChildren(QLabel)
            ]
            self.assertIn("KVM OK", online_texts)
            self.assertIn("libvirt OK", online_texts)
            self.assertTrue(any(text == "EN LÍNEA" for text in online_texts))

            offline_texts = [
                label.text() for label in window._host_card_frames[1].findChildren(QLabel)
            ]
            self.assertTrue(any(text == "SIN CONEXIÓN" for text in offline_texts))
            self.assertTrue(any("Sin señal desde 2026-06-01T10:00:00" in text for text in offline_texts))
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
            self.assertTrue(any("Todavía no hay equipos registrados" in text for text in texts))

            window.render_hub_offline("connection refused")
            texts = [
                label.text()
                for label in window.remote_cards_scroll.widget().findChildren(QLabel)
            ]
            self.assertTrue(any("No se puede contactar con el Hub" in text for text in texts))
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
            self.assertEqual(window.remote_status_label.text(), "Hub sin cargar")
            self.assertIn("Hub", window.remote_detail.placeholderText())
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
            self.assertEqual(window.run_doctor_button.text(), "Comprobar sistema")
            self.assertFalse(window.copy_report_button.isEnabled())
            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertIn("Diagnóstico", texts)
            self.assertTrue(any("Pulsa «Comprobar sistema» para revisar tu equipo" in text for text in texts))
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
            self.assertIn("Hay fallos críticos", window.diag_overall_label.text())
            self.assertTrue(window.copy_report_button.isEnabled())

            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertIn("Virtualización local", texts)
            self.assertIn("Herramientas", texts)
            self.assertIn("Docker", texts)
            self.assertTrue(any("CRÍTICO" in text for text in texts))

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
            self.assertIn("no se ha podido ejecutar", window.diag_overall_label.text().lower())
            page = window.main_tabs.widget(window.diagnostics_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertTrue(any("El diagnóstico no se ha podido ejecutar: boom" in text for text in texts))
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
                ["General", "Hub", "Agente", "NAS", "Valores por defecto", "Consola", "Apariencia", "Avanzado"],
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
            self.assertIn("http:// o https://", dialog.status.text())
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
            self.assertIn("No se han podido guardar los ajustes", show_error.call_args[0][0])
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_vm_page_header_chips_and_empty_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            backend_cls.return_value.recent_logs.return_value = ""
            window = MainWindow()
            self.assertEqual(window.vm_page_title.text(), "Máquinas virtuales")
            self.assertIn("Las máquinas de este equipo", window.vm_page_subtitle.text())
            self.assertEqual(window.vm_table.columnCount(), 7)

            window.render_vms([])
            self.assertEqual(window.vm_stack.currentIndex(), 1)
            self.assertIn("Crea tu primera máquina desde una ISO", window.vm_empty_subtitle.text())

            window.render_vms([
                VmSummary(name="dc01", state="running", lab_id="lab", ram_mib=4096, vcpus=2, graphics="vnc"),
                VmSummary(name="cl01", state="shut off", lab_id="lab", ram_mib=2048, vcpus=1, graphics="spice"),
                VmSummary(name="p01", state="paused", lab_id="lab", ram_mib=1024, vcpus=1),
            ])
            self.assertEqual(window.vm_table.rowCount(), 3)
            states = [window.vm_table.item(row, 1).text() for row in range(3)]
            self.assertEqual(states, ["ENCENDIDA", "APAGADA", "EN PAUSA"])
            self.assertEqual(window.vm_table.item(0, 6).text(), "VNC")

            # Destructive actions keep the danger style; core attributes survive.
            self.assertEqual(window.force_button.objectName(), "dangerButton")
            self.assertEqual(window.delete_button.objectName(), "dangerButton")
            for attr in ("start_button", "console_button", "external_console_button", "snapshots_button",
                         "clone_button", "migrate_button", "settings_button"):
                self.assertTrue(hasattr(window, attr))

            # Console detail card shows console status and Host Key.
            console_text = window.detail_views["Consola"].toPlainText()
            self.assertIn("Consola integrada", console_text)
            self.assertIn("Ctrl derecho", console_text)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_labs_sidebar_opens_real_workspace_page(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            sections = [window.sidebar_nav.item(i).text() for i in range(window.sidebar_nav.count())]
            window.sidebar_nav.setCurrentRow(sections.index("Laboratorios"))
            # Labs is a dedicated workspace page now, not the shared VM view.
            self.assertEqual(window.main_tabs.currentIndex(), window.labs_page_index)
            self.assertFalse(window.right_panel.isVisible())
            window.sidebar_nav.setCurrentRow(sections.index("Máquinas virtuales"))
            self.assertEqual(window.main_tabs.currentIndex(), 0)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_migrations_page_polish(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            page = window.main_tabs.widget(window.migrations_page_index)
            texts = [label.text() for label in page.findChildren(QLabel)]
            self.assertIn("Migraciones", texts)
            self.assertIn("Historial de traslados de máquinas entre equipos", texts)
            self.assertTrue(any("solo consulta" in text for text in texts))
            # History table and actions exist; copy starts disabled.
            self.assertEqual(window.migrations_table.columnCount(), 7)
            self.assertTrue(window.migrations_refresh_button.isEnabled())
            self.assertFalse(window.copy_migration_id_button.isEnabled())
            self.assertFalse(window.copy_migration_summary_button.isEnabled())
            # Quick action without a selected VM navigates instead of crashing.
            window.selected_vm = None
            window._open_live_migration_from_page()
            self.assertEqual(window.sidebar_nav.currentItem().text(), "Máquinas virtuales")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_host_view_vms_shows_remote_inventory(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel, QTableWidget
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()

            # Remote inventory renders in a dialog with the host's VMs.
            window._show_remote_vms_dialog(
                "gery-lenovo",
                {
                    "vms": [
                        # The Hub returns "vm_name" (host_vms table), not "name".
                        {"vm_name": "ubuntu-migrated", "state": "running", "lab_id": "default-lab", "ram_mib": 4096, "vcpus": 2},
                        {"vm_name": "ubuntu-hub-e2e", "state": "shut off", "lab_id": "default-lab", "ram_mib": 2048, "vcpus": 1},
                    ]
                },
            )
            dialog = window._remote_vms_dialog
            self.assertIn("gery-lenovo", dialog.windowTitle())
            table = dialog.findChild(QTableWidget, "remoteVmsTable")
            self.assertEqual(table.rowCount(), 2)
            self.assertEqual(table.item(0, 0).text(), "ubuntu-migrated")
            self.assertEqual(table.item(0, 1).text(), "RUNNING")
            self.assertEqual(table.item(0, 5).text(), "gery-lenovo")
            texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("las ejecuta el equipo de destino", texts)
            self.assertIn("Borrar máquinas en remoto", texts)
            self.assertIn("no está permitido a propósito", texts)
            dialog.close()

            # Hub error surfaces instead of silently showing local VMs.
            with patch.object(window, "show_error") as show_error:
                window._show_remote_vms_dialog("gery-lenovo", {"error": "connection refused"})
                show_error.assert_called_once()
                self.assertIn("gery-lenovo", show_error.call_args[0][0])

            # Viewing the local host keeps the existing navigation behavior.
            with patch.object(window, "_dashboard_go_vms") as go_vms, \
                 patch("hypergery_ubuntu.ui_qt.main_window.effective_config") as config:
                config.return_value = {"host_id": type("V", (), {"value": "local-host"})()}
                window._view_host_vms("local-host")
                go_vms.assert_called_once()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_vm_power_buttons_follow_vm_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window._show_remote_vms_dialog(
                "gery-lenovo",
                {
                    "vms": [
                        {"vm_name": "ubuntu-migrated", "state": "running", "lab_id": "default-lab", "ram_mib": 4096, "vcpus": 2},
                        {"vm_name": "ubuntu-hub-e2e", "state": "shut off", "lab_id": "default-lab", "ram_mib": 2048, "vcpus": 1},
                    ]
                },
            )
            dialog = window._remote_vms_dialog
            # No selection: every power action stays disabled.
            self.assertFalse(window.remote_vm_start_button.isEnabled())
            self.assertFalse(window.remote_vm_shutdown_button.isEnabled())
            self.assertFalse(window.remote_vm_force_off_button.isEnabled())
            self.assertTrue(window.remote_vm_refresh_button.isEnabled())
            # Force Off carries the danger style.
            self.assertEqual(window.remote_vm_force_off_button.objectName(), "dangerButton")
            # Running VM: Start disabled, Shutdown/Force Off enabled.
            window.remote_vms_table.selectRow(0)
            self.assertFalse(window.remote_vm_start_button.isEnabled())
            self.assertTrue(window.remote_vm_shutdown_button.isEnabled())
            self.assertTrue(window.remote_vm_force_off_button.isEnabled())
            # Shut off VM: only Start enabled.
            window.remote_vms_table.selectRow(1)
            self.assertTrue(window.remote_vm_start_button.isEnabled())
            self.assertFalse(window.remote_vm_shutdown_button.isEnabled())
            self.assertFalse(window.remote_vm_force_off_button.isEnabled())
            dialog.close()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_vm_power_actions_queue_hub_commands(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QMessageBox
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window._show_remote_vms_dialog(
                "gery-lenovo",
                {
                    "vms": [
                        {"vm_name": "ubuntu-migrated", "state": "running", "lab_id": "default-lab", "ram_mib": 4096, "vcpus": 2},
                        {"vm_name": "ubuntu-hub-e2e", "state": "shut off", "lab_id": "default-lab", "ram_mib": 2048, "vcpus": 1},
                    ]
                },
            )
            dialog = window._remote_vms_dialog

            def run_sync(label, fn, *, on_success=None, refresh_after=True, busy=True):
                result = fn()
                if on_success:
                    on_success(result)

            with patch.object(window, "run_operation", side_effect=run_sync), \
                 patch("hypergery_ubuntu.registry.RegistryClient") as client_cls:
                client = client_cls.return_value
                client.queue_vm_power_command.return_value = {"command_id": "cmd-power-1", "status": "pending"}

                # Start on a shut off VM queues vm_start for the remote host.
                window.remote_vms_table.selectRow(1)
                window.remote_vm_start_button.click()
                client.queue_vm_power_command.assert_called_once_with("gery-lenovo", "ubuntu-hub-e2e", "start")
                self.assertIn("cmd-power-1", window.remote_power_status.text())
                window._remote_power_poll_timer.stop()

                # Shutdown on a running VM queues vm_shutdown.
                client.queue_vm_power_command.reset_mock()
                window.remote_vms_table.selectRow(0)
                window.remote_vm_shutdown_button.click()
                client.queue_vm_power_command.assert_called_once_with("gery-lenovo", "ubuntu-migrated", "shutdown")
                window._remote_power_poll_timer.stop()

                # Force Off asks for confirmation; declining queues nothing.
                client.queue_vm_power_command.reset_mock()
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                    window.remote_vm_force_off_button.click()
                client.queue_vm_power_command.assert_not_called()
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    window.remote_vm_force_off_button.click()
                client.queue_vm_power_command.assert_called_once_with("gery-lenovo", "ubuntu-migrated", "force_off")
                window._remote_power_poll_timer.stop()

                # Command completion updates the status and refreshes inventory.
                client.command.return_value = {
                    "command_id": "cmd-power-1",
                    "status": "done",
                    "result": {"message": "force off executed on ubuntu-migrated (running -> shut off)."},
                }
                client.list_vms.return_value = [
                    {"vm_name": "ubuntu-migrated", "state": "shut off", "lab_id": "default-lab", "ram_mib": 4096, "vcpus": 2},
                ]
                window._remote_power_command_id = "cmd-power-1"
                window._poll_remote_power_command()
                self.assertIn("completada", window.remote_power_status.text())
                client.list_vms.assert_called_once_with("gery-lenovo")
                self.assertEqual(window.remote_vms_table.rowCount(), 1)
                self.assertEqual(window.remote_vms_table.item(0, 1).text(), "SHUT OFF")
                self.assertFalse(window._remote_power_poll_timer.isActive())

                # Hub errors surface in the status label instead of crashing.
                client.queue_vm_power_command.side_effect = Exception("hub offline")
                window.remote_vms_table.selectRow(0)
                window._queue_remote_power_action("start")
                self.assertIn("hub offline", window.remote_power_status.text())

            # No local backend power call ever happens for remote VMs.
            backend_cls.return_value.start_vm.assert_not_called()
            backend_cls.return_value.shutdown_vm.assert_not_called()
            backend_cls.return_value.force_off_vm.assert_not_called()
            dialog.close()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_migrations_history_renders_records_and_copies(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.render_migrations(
                {
                    "migrations": [
                        {
                            "migration_id": "mig-done-1",
                            "source_vm_name": "ubuntu",
                            "target_vm_name": "ubuntu-migrated",
                            "source_host_id": "pc-1",
                            "target_host_id": "pc-2",
                            "strategy": "hub_transfer",
                            "status": "done",
                            "package_path": "hub://mig-done-1",
                            "updated_at": "2026-06-05T18:49:00+00:00",
                            "errors": [],
                        },
                        {
                            "migration_id": "mig-fail-2",
                            "source_vm_name": "ubuntu",
                            "target_vm_name": "x",
                            "source_host_id": "pc-1",
                            "target_host_id": "pc-2",
                            "strategy": "nas_clone",
                            "status": "failed",
                            "errors": ["staging path rejected"],
                        },
                    ]
                }
            )
            self.assertEqual(window.migrations_table.rowCount(), 2)
            self.assertEqual(window.migrations_table.item(0, 0).text(), "mig-done-1")
            self.assertEqual(window.migrations_table.item(0, 5).text(), "DONE")
            self.assertEqual(window.migrations_table.item(1, 4).text(), "nas_clone")
            self.assertIn("2 traslado(s)", window.migrations_status_label.text())
            self.assertIn("1 completados", window.migrations_status_label.text())
            self.assertIn("1 fallidos", window.migrations_status_label.text())

            # Selecting a row enables copy actions and copies real data.
            window.migrations_table.selectRow(0)
            self.assertTrue(window.copy_migration_id_button.isEnabled())
            window.copy_selected_migration_id()
            self.assertEqual(QApplication.clipboard().text(), "mig-done-1")
            window.migrations_table.selectRow(1)
            window.copy_selected_migration_summary()
            summary = QApplication.clipboard().text()
            self.assertIn("mig-fail-2", summary)
            self.assertIn("staging path rejected", summary)

            # Hub error renders inline without touching history records.
            window.render_migrations({"error": "connection refused"})
            self.assertEqual(window.migrations_table.rowCount(), 0)
            self.assertIn("No se puede contactar con el Hub", window.migrations_status_label.text())
            self.assertFalse(window.copy_migration_id_button.isEnabled())
            window.close()
        self.assertIsNotNone(app)

    def test_console_window_status_bar_and_spice_card(self):
        app = QApplication.instance() or QApplication([])
        from unittest.mock import MagicMock
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.console import VmConsoleWindow

        backend = MagicMock()
        vm = VmSummary(name="hg-spice", state="shut off", lab_id="lab", ram_mib=1024, vcpus=1, graphics="spice")
        window = VmConsoleWindow(backend, vm)
        self.assertIn("Consola HyperGery - hg-spice", window.windowTitle())
        self.assertIn("Ctrl derecho", window.host_key_label.text())
        self.assertIn("no apaga la VM", window.close_note_label.text())
        self.assertIn("SPICE", window.display_label.text())

        # SPICE card keeps the v0.6 microcopy and is the active mode.
        self.assertIs(window.console.mode_stack.currentWidget(), window.console.spice_card)
        from PySide6.QtWidgets import QLabel
        texts = " ".join(label.text() for label in window.console.spice_card.findChildren(QLabel))
        self.assertIn("SPICE", texts)

        # No input capture without an active VNC connection.
        window.console.capture_input()
        self.assertFalse(window.console.input_captured)

        # Closing the console never powers off or deletes the VM.
        window.close()
        for call in backend.method_calls:
            self.assertNotIn("shutdown", str(call))
            self.assertNotIn("force_off", str(call))
            self.assertNotIn("delete", str(call))
        self.assertIsNotNone(app)

    def test_console_window_powered_off_vnc_vm_message(self):
        app = QApplication.instance() or QApplication([])
        from unittest.mock import MagicMock
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.console import VmConsoleWindow

        backend = MagicMock()
        vm = VmSummary(name="hg-vnc", state="shut off", lab_id="lab", ram_mib=1024, vcpus=1, graphics="vnc")
        window = VmConsoleWindow(backend, vm)
        self.assertIn("está apagada", window.console.screen.message.lower())
        self.assertIn("vuelve a conectar", window.console.screen.message)
        self.assertFalse(window.connect_action.isEnabled())
        window.console.capture_input()
        self.assertFalse(window.console.input_captured)
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
                ["Elegir máquina", "Equipo destino", "Opciones", "Comprobación", "Progreso", "Resultado"],
            )
            texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("no es migración de RAM en vivo", texts)
            self.assertIn("La máquina original y sus discos no se borran.", texts)
            self.assertIn("Debe estar apagada", texts)
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
            self.assertIn("No se puede mover una máquina encendida", texts)
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
            self.assertIn("sin conexión", dialog.error_label.text().lower())
            self.assertFalse(dialog.package_button.isEnabled())

            # Online, ready target passes preflight and enables Start Migration.
            dialog.target_host.setCurrentIndex(1)
            dialog._set_step(3)
            dialog.run_preflight()
            self.assertTrue(dialog.package_button.isEnabled(), dialog.error_label.text())
            self.assertIn("¿Se borra el original?: False", dialog.result_view.toPlainText())
            self.assertIn("el UUID y la MAC se regeneran al importar", dialog.result_view.toPlainText())
            dialog.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_hub_transfer_default_and_nas_toggle(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            # Hub transfer is the default and does not need a NAS path.
            self.assertEqual(dialog.values()["transfer"], "hub")
            self.assertFalse(dialog.nas_path.isEnabled())
            self.assertFalse(dialog.nas_browse_button.isEnabled())

            # Switching to shared NAS re-enables the path field.
            dialog.transfer_mode.setCurrentIndex(1)
            self.assertEqual(dialog.values()["transfer"], "nas")
            self.assertTrue(dialog.nas_path.isEnabled())
            self.assertTrue(dialog.nas_browse_button.isEnabled())

            # NAS mode without a path blocks preflight with a clear message.
            dialog.source_host_id.setText("source-host")
            dialog.target_host.setCurrentIndex(0)
            dialog.nas_path.setText("")
            dialog.run_preflight()
            self.assertIn("La carpeta del NAS es obligatoria", dialog.error_label.text())
            self.assertFalse(dialog.package_button.isEnabled())

            # Hub mode passes preflight without any NAS path and reports the transfer.
            dialog.transfer_mode.setCurrentIndex(0)
            dialog._set_step(3)
            dialog.run_preflight()
            self.assertTrue(dialog.package_button.isEnabled(), dialog.error_label.text())
            self.assertIn("Envío: por el Hub", dialog.result_view.toPlainText())
            self.assertIn("se borra de allí tras importarse", dialog.result_view.toPlainText())
            dialog.close()
        self.assertIsNotNone(app)

    def test_migration_wizard_auto_polls_status_and_stops_on_close(self):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.dialogs import LiveMigrationDialog
        MigrationFakeBackend = migration_fake_backend()

        with tempfile.TemporaryDirectory() as tmp:
            backend = MigrationFakeBackend(Path(tmp))
            with patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls:
                registry_cls.return_value.list_hosts.return_value = [FAKE_ONLINE_HOST]
                dialog = LiveMigrationDialog(backend, backend.get_vm("hg-source"))

            # Poll timer exists, repeats every few seconds, and starts inactive.
            self.assertEqual(dialog.status_poll_timer.interval(), 4000)
            self.assertFalse(dialog.status_poll_timer.isActive())

            # Closing the dialog stops an active poll loop (and nothing else).
            dialog.status_poll_timer.start()
            self.assertTrue(dialog.status_poll_timer.isActive())
            dialog.reject()
            self.assertFalse(dialog.status_poll_timer.isActive())

            # Without a started migration the poll handler is a safe no-op.
            dialog.refresh_migration_status()
            self.assertIn("Todavía no hay ningún traslado", dialog.error_label.text())
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
            self.assertIn("Aún no hay ID", dialog.error_label.text())
            dialog.copy_progress_logs()
            dialog.copy_summary()
            self.assertIn("Aún no hay resultado", dialog.error_label.text())

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
            self.assertIn("La máquina original no se ha tocado", texts)
            self.assertIn("UUID y MAC nuevos", texts)
            self.assertIn("se conserva", texts)

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


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtHubStagingTests(unittest.TestCase):
    def make_window(self, backend_cls, tmp):
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        return MainWindow()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_staging_panel_renders_stats_and_packages(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_hub_staging(
                {
                    "staging_dir": "/data/staging",
                    "count": 1,
                    "orphan_count": 1,
                    "total_size_bytes": 4096,
                    "packages": [
                        {
                            "migration_id": "mig-orphan",
                            "size_bytes": 4096,
                            "file_count": 2,
                            "age_hours": 48.0,
                            "migration_status": "",
                            "orphan": True,
                        }
                    ],
                }
            )
            self.assertIn("/data/staging", window.staging_stats_label.text())
            self.assertIn("1 orphan(s)", window.staging_stats_label.text())
            self.assertIn("mig-orphan", window.staging_detail.toPlainText())
            self.assertIn("sin registro de traslado (huérfano)", window.staging_detail.toPlainText())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_staging_panel_empty_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_hub_staging(
                {"staging_dir": "/data/staging", "count": 0, "orphan_count": 0, "total_size_bytes": 0, "packages": []}
            )
            self.assertEqual(window.staging_detail.toPlainText(), "No hay paquetes temporales.")
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_staging_panel_hub_offline_does_not_crash(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_hub_staging({"error": "connection refused"})
            self.assertIn("No se puede contactar con el Hub", window.staging_stats_label.text())
            self.assertIn("HYPERGERY_HUB_URL", window.staging_stats_label.text())
            window.render_hub_cleanup_result({"error": "connection refused"})
            self.assertIn("No se puede contactar con el Hub", window.staging_detail.toPlainText())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_dry_run_renders_candidates_without_deleting(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_hub_cleanup_result(
                {
                    "dry_run": True,
                    "older_than_hours": 24.0,
                    "candidates": [{"migration_id": "mig-orphan", "size_bytes": 4096, "reason": "orphan"}],
                    "total_size_bytes": 4096,
                    "deleted_count": 0,
                    "deleted_size_bytes": 0,
                    "skipped": [{"migration_id": "mig-active", "reason": "migration is active (status: importing)"}],
                    "errors": [],
                }
            )
            text = window.staging_detail.toPlainText()
            self.assertIn("SIMULACIÓN", text)
            self.assertIn("mig-orphan", text)
            self.assertIn("mig-active", text)
            self.assertNotIn("Deleted", text)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_confirmed_cleanup_requires_confirmation(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            with (
                patch.object(window, "_run_hub_cleanup") as run_cleanup,
                patch(
                    "hypergery_ubuntu.ui_qt.main_window.QMessageBox.warning",
                    return_value=QMessageBox.StandardButton.Cancel,
                ) as warning,
            ):
                window.confirm_hub_cleanup()
                warning.assert_called_once()
                run_cleanup.assert_not_called()
            with (
                patch.object(window, "_run_hub_cleanup") as run_cleanup,
                patch(
                    "hypergery_ubuntu.ui_qt.main_window.QMessageBox.warning",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                window.confirm_hub_cleanup()
                run_cleanup.assert_called_once_with(dry_run=False)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_real_cleanup_result_logs_and_refreshes(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            with patch.object(window, "refresh_hub_staging") as refresh:
                window.render_hub_cleanup_result(
                    {
                        "dry_run": False,
                        "older_than_hours": 24.0,
                        "candidates": [{"migration_id": "mig-orphan", "size_bytes": 4096, "reason": "orphan"}],
                        "total_size_bytes": 4096,
                        "deleted_count": 1,
                        "deleted_size_bytes": 4096,
                        "skipped": [],
                        "errors": [],
                    }
                )
                refresh.assert_called_once()
            text = window.staging_detail.toPlainText()
            self.assertIn("LIMPIEZA EJECUTADA", text)
            self.assertIn("Borrados 1 paquete(s)", text)
            self.assertIn("Limpieza del Hub completada", window.activity_log.toPlainText())
            window.close()
        self.assertIsNotNone(app)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtCommandQueueTests(unittest.TestCase):
    SAMPLE_COMMANDS = [
        {
            "command_id": "cmd-power-1",
            "target_host_id": "lenovo",
            "command_type": "vm_start",
            "status": "done",
            "payload": {"vm_name": "vm1"},
            "result": {"message": "start executed on vm1 (shut off -> running)."},
            "created_at": "2026-06-05T01:00:00+00:00",
            "updated_at": "2026-06-05T01:00:05+00:00",
        },
        {
            "command_id": "cmd-mig-1",
            "target_host_id": "pc-casa",
            "command_type": "import_vm_package",
            "status": "failed",
            "payload": {"migration_id": "mig-1"},
            "result": {"error": "target offline"},
            "created_at": "2026-06-05T00:00:00+00:00",
            "updated_at": "2026-06-05T00:00:10+00:00",
        },
        {
            "command_id": "cmd-ping-1",
            "target_host_id": "pc-casa",
            "command_type": "ping",
            "status": "pending",
            "payload": {},
            "result": {},
            "created_at": "2026-06-05T02:00:00+00:00",
            "updated_at": "2026-06-05T02:00:00+00:00",
        },
    ]

    def make_window(self, backend_cls, tmp):
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        return MainWindow()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_commands_page_renders_statuses_and_summary(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_commands({"commands": self.SAMPLE_COMMANDS})
            self.assertEqual(window.commands_table.rowCount(), 3)
            self.assertIn("3 mostradas / 3 orden(es)", window.commands_status_label.text())
            self.assertIn("1 pendientes", window.commands_status_label.text())
            self.assertIn("1 fallidas", window.commands_status_label.text())
            statuses = {window.commands_table.item(row, 3).text() for row in range(3)}
            self.assertEqual(statuses, {"DONE", "FAILED", "PENDING"})
            results = [window.commands_table.item(row, 7).text() for row in range(3)]
            self.assertTrue(any("start executed" in text for text in results))
            self.assertTrue(any("target offline" in text for text in results))
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_commands_filters(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_commands({"commands": self.SAMPLE_COMMANDS})
            window.commands_filter.setCurrentText("Fallidas")
            self.assertEqual(window.commands_table.rowCount(), 1)
            self.assertEqual(window.commands_table.item(0, 0).text(), "cmd-mig-1")
            window.commands_filter.setCurrentText("De encendido/apagado")
            self.assertEqual(window.commands_table.rowCount(), 1)
            self.assertEqual(window.commands_table.item(0, 2).text(), "vm_start")
            window.commands_filter.setCurrentText("De traslado")
            self.assertEqual(window.commands_table.rowCount(), 1)
            self.assertEqual(window.commands_table.item(0, 2).text(), "import_vm_package")
            window.commands_filter.setCurrentText("Todas")
            self.assertEqual(window.commands_table.rowCount(), 3)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_commands_copy_buttons_follow_selection(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_commands({"commands": self.SAMPLE_COMMANDS})
            self.assertFalse(window.copy_command_id_button.isEnabled())
            self.assertFalse(window.copy_command_result_button.isEnabled())
            # Copy without selection is a safe no-op.
            window.copy_selected_command_id()
            window.copy_selected_command_result()
            window.commands_table.selectRow(0)
            self.assertTrue(window.copy_command_id_button.isEnabled())
            window.copy_selected_command_id()
            self.assertEqual(QApplication.clipboard().text(), window.commands_visible[0]["command_id"])
            window.copy_selected_command_result()
            self.assertIn('"', QApplication.clipboard().text())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_commands_page_hub_offline_and_empty_states(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window.render_commands({"error": "connection refused"})
            self.assertEqual(window.commands_table.rowCount(), 0)
            self.assertIn("No se puede contactar con el Hub", window.commands_status_label.text())
            window.render_commands({"commands": []})
            self.assertIn("aún no tiene órdenes", window.commands_status_label.text())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_commands_page_has_no_destructive_actions(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QPushButton

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            page = window.main_tabs.widget(window.commands_page_index)
            button_texts = {button.text().lower() for button in page.findChildren(QPushButton)}
            for forbidden in ("delete", "requeue", "retry", "run", "execute", "cancel"):
                for text in button_texts:
                    self.assertNotIn(forbidden, text)
            window.close()
        self.assertIsNotNone(app)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtRemoteVmDetailsTests(unittest.TestCase):
    REMOTE_VM = {
        "vm_name": "hg-remote",
        "state": "running",
        "lab_id": "lab1",
        "ram_mib": 2048,
        "vcpus": 2,
        "disk_paths": ["/var/lib/libvirt/images/hg-remote.qcow2"],
        "iso_paths": [],
        "display": "vnc",
        "networks": ["hg-net-lab1"],
        "macs": ["52:54:00:aa:bb:cc"],
        "updated_at": "2020-01-01T00:00:00+00:00",
    }

    def make_window_with_dialog(self, backend_cls, tmp, vms):
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        window = MainWindow()
        window.remote_hosts = [dict(FAKE_ONLINE_HOST)]
        window._show_remote_vms_dialog("target", {"vms": vms})
        return window

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_details_panel_shows_fields_and_stale_warning(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window_with_dialog(backend_cls, tmp, [dict(self.REMOTE_VM)])
            window.remote_vms_table.selectRow(0)
            text = window.remote_vm_detail.toPlainText()
            self.assertIn("hg-remote", text)
            self.assertIn("target", text)
            self.assertIn("lab1", text)
            self.assertIn("hg-remote.qcow2", text)
            self.assertIn("VNC", text)
            self.assertIn("52:54:00:aa:bb:cc", text)
            self.assertIn("hg-net-lab1", text)
            self.assertIn("2020-01-01T00:00:00+00:00", text)
            self.assertIn("desactualizados", text)
            window._remote_vms_dialog.close()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_details_panel_fresh_inventory_has_no_stale_warning(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import now_iso

        with tempfile.TemporaryDirectory() as tmp:
            fresh = dict(self.REMOTE_VM, updated_at=now_iso())
            window = self.make_window_with_dialog(backend_cls, tmp, [fresh])
            window.remote_vms_table.selectRow(0)
            text = window.remote_vm_detail.toPlainText()
            self.assertIn("hg-remote", text)
            self.assertNotIn("desactualizados", text)
            window._remote_vms_dialog.close()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_remote_command_completion_logs_activity(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window_with_dialog(backend_cls, tmp, [dict(self.REMOTE_VM)])

            def fake_run_operation(label, fn, *, on_success=None, **kwargs):
                result = fn()
                if on_success:
                    on_success(result)

            window._remote_power_command_id = "cmd-1"
            with (
                patch.object(window, "run_operation", side_effect=fake_run_operation),
                patch.object(window, "_refresh_remote_vms"),
                patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls,
            ):
                registry_cls.return_value.command.return_value = {
                    "status": "done",
                    "result": {"message": "start executed on hg-remote."},
                }
                window._poll_remote_power_command()
            self.assertIn("Orden remota completada: cmd-1", window.activity_log.toPlainText())

            window._remote_power_command_id = "cmd-2"
            with (
                patch.object(window, "run_operation", side_effect=fake_run_operation),
                patch.object(window, "_refresh_remote_vms"),
                patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls,
            ):
                registry_cls.return_value.command.return_value = {
                    "status": "failed",
                    "result": {"error": "VM state mismatch"},
                }
                window._poll_remote_power_command()
            self.assertIn("Orden remota FALLÓ: cmd-2", window.activity_log.toPlainText())
            window._remote_vms_dialog.close()
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_details_panel_clears_without_selection_and_console_stays_disabled(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QPushButton

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window_with_dialog(backend_cls, tmp, [dict(self.REMOTE_VM)])
            dialog = window._remote_vms_dialog
            console_buttons = [b for b in dialog.findChildren(QPushButton) if b.text() == "Consola"]
            self.assertEqual(len(console_buttons), 1)
            self.assertFalse(console_buttons[0].isEnabled())
            self.assertIn("versión futura", console_buttons[0].toolTip())
            window.remote_vms_table.clearSelection()
            window._update_remote_power_buttons()
            self.assertEqual(window.remote_vm_detail.toPlainText(), "")
            # No remote delete button exists anywhere in the dialog.
            button_texts = {b.text().lower() for b in dialog.findChildren(QPushButton)}
            self.assertFalse(any("delete" in text for text in button_texts))
            dialog.close()
            window.close()
        self.assertIsNotNone(app)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtLabsWorkspaceTests(unittest.TestCase):
    LAB = {
        "lab_id": "asr-lab",
        "name": "ASR Lab",
        "description": "Active Directory lab",
        "network_mode": "isolated",
        "subnet": "192.168.30.0/24",
        "bridge_name": "hgbr1234567",
        "vms": ["alpha", "ghost"],
        "vm_roles": {"alpha": "server"},
    }

    def make_window(self, backend_cls, tmp):
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        window = MainWindow()
        window.labs = [dict(self.LAB)]
        window.all_vms = [
            VmSummary(name="alpha", state="shut off", lab_id="asr-lab", ram_mib=2048, vcpus=2),
        ]
        window.remote_vms_inventory = [
            {
                "host_id": "lenovo",
                "vm_name": "remote-db",
                "state": "running",
                "lab_id": "asr-lab",
                "ram_mib": 4096,
                "vcpus": 4,
            }
        ]
        window.render_labs_workspace()
        return window

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_workspace_renders_cards_status_and_host_distribution(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            self.assertEqual(len(window._lab_ws_card_frames), 1)
            self.assertEqual(window.lab_ws_title.text(), "ASR Lab")
            self.assertIn("isolated", window.lab_ws_meta.text())
            self.assertIn("Active Directory lab", window.lab_ws_meta.text())
            status = window.lab_ws_status_label.text()
            self.assertIn("3 máquina(s)", status)
            self.assertIn("1 encendidas", status)
            self.assertIn("1 apagadas", status)
            self.assertIn("1 sin crear", status)
            hosts = window.lab_ws_hosts_label.text()
            self.assertIn("lenovo: 1 máquina(s)", hosts)
            self.assertEqual(window.lab_ws_vm_table.rowCount(), 3)
            roles = {window.lab_ws_vm_table.item(row, 1).text() for row in range(3)}
            self.assertIn("server", roles)
            locations = {window.lab_ws_vm_table.item(row, 6).text() for row in range(3)}
            self.assertIn("Remoto", locations)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_workspace_empty_state(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QLabel
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.labs = []
            window.render_labs_workspace()
            texts = []
            for index in range(window.lab_ws_cards_layout.count()):
                widget = window.lab_ws_cards_layout.itemAt(index).widget()
                if widget is not None:
                    texts.extend(label.text() for label in widget.findChildren(QLabel))
            self.assertTrue(any("Todavía no hay laboratorios" in text for text in texts))
            self.assertTrue(any("default-lab" in text for text in texts))
            self.assertEqual(window.lab_ws_title.text(), "Ningún laboratorio seleccionado")
            self.assertFalse(window.lab_ws_start_button.isEnabled())
            self.assertFalse(window.lab_ws_shutdown_button.isEnabled())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_start_lab_requires_confirmation_and_targets_shut_off_vms(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            with (
                patch.object(window, "_execute_lab_power") as execute,
                patch(
                    "hypergery_ubuntu.ui_qt.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ) as question,
            ):
                window.start_lab()
                question.assert_called_once()
                self.assertIn("Se encenderán 1 máquina(s) en 1 equipo(s)", question.call_args.args[2])
                execute.assert_not_called()
            with (
                patch.object(window, "_execute_lab_power") as execute,
                patch(
                    "hypergery_ubuntu.ui_qt.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                window.start_lab()
                execute.assert_called_once()
                lab_id, action, targets = execute.call_args.args
                self.assertEqual((lab_id, action), ("asr-lab", "start"))
                self.assertEqual([vm["name"] for vm in targets], ["alpha"])
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_shutdown_lab_targets_running_vms_including_remote(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            with (
                patch.object(window, "_execute_lab_power") as execute,
                patch(
                    "hypergery_ubuntu.ui_qt.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ) as question,
            ):
                window.shutdown_lab()
                self.assertIn("apagado suave de 1 máquina(s) encendida(s)", question.call_args.args[2])
                _lab_id, action, targets = execute.call_args.args
                self.assertEqual(action, "shutdown")
                self.assertEqual([vm["name"] for vm in targets], ["remote-db"])
                self.assertTrue(targets[0]["remote"])
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_execute_lab_power_mixes_local_and_remote_and_reports_partial_failure(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)

            def fake_run_operation(label, fn, *, on_success=None, **kwargs):
                result = fn()
                if on_success:
                    on_success(result)

            backend = backend_cls.return_value
            backend.start_vm.side_effect = lambda name: None
            targets = [
                {"name": "alpha", "host_id": window._local_host_id(), "remote": False, "state": "shut off"},
                {"name": "remote-db", "host_id": "lenovo", "remote": True, "state": "shut off"},
                {"name": "broken", "host_id": window._local_host_id(), "remote": False, "state": "shut off"},
            ]

            def start_vm(name):
                if name == "broken":
                    raise Exception("libvirt exploded")

            backend.start_vm.side_effect = start_vm
            with (
                patch.object(window, "run_operation", side_effect=fake_run_operation),
                patch.object(window, "refresh_all"),
                patch("hypergery_ubuntu.registry.RegistryClient") as registry_cls,
            ):
                registry_cls.return_value.queue_vm_power_command.return_value = {"command_id": "cmd-9"}
                window._execute_lab_power("asr-lab", "start", targets)
                registry_cls.return_value.queue_vm_power_command.assert_called_once_with("lenovo", "remote-db", "start")
            feedback = window.lab_ws_feedback.text()
            self.assertIn("1 máquina(s) locales: alpha", feedback)
            self.assertIn("remote-db@lenovo (cmd-9)", feedback)
            self.assertIn("1 FALLARON", feedback)
            self.assertIn("libvirt exploded", feedback)
            self.assertIn("Laboratorio asr-lab (start)", window.activity_log.toPlainText())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_workspace_has_no_force_off_or_delete_lab_actions(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QPushButton

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            page = window.main_tabs.widget(window.labs_page_index)
            button_texts = {button.text().lower() for button in page.findChildren(QPushButton)}
            self.assertFalse(any("force" in text for text in button_texts))
            self.assertFalse(any("delete" in text for text in button_texts))
            # Snapshot Lab exists but is explicitly disabled as planned.
            snapshot = [b for b in page.findChildren(QPushButton) if b.text() == "Instantánea del laboratorio"]
            self.assertEqual(len(snapshot), 1)
            self.assertFalse(snapshot[0].isEnabled())
            self.assertIn("Previsto", snapshot[0].toolTip())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_vm_action_buttons_follow_selection(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            # Row order is alphabetical: alpha (local), ghost (not created), remote-db (remote).
            window.lab_ws_vm_table.selectRow(0)
            self.assertTrue(window.lab_ws_open_vm_button.isEnabled())
            self.assertTrue(window.lab_ws_migrate_button.isEnabled())
            self.assertFalse(window.lab_ws_view_remote_button.isEnabled())
            window.lab_ws_vm_table.selectRow(1)
            self.assertFalse(window.lab_ws_open_vm_button.isEnabled())
            self.assertFalse(window.lab_ws_view_remote_button.isEnabled())
            window.lab_ws_vm_table.selectRow(2)
            self.assertFalse(window.lab_ws_open_vm_button.isEnabled())
            self.assertTrue(window.lab_ws_view_remote_button.isEnabled())
            window.close()
        self.assertIsNotNone(app)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class QtControlCenterTests(unittest.TestCase):
    def make_window(self, backend_cls, tmp):
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        return MainWindow()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_control_center_page_has_all_module_tabs(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            tabs = [window.v1_tabs.tabText(i) for i in range(window.v1_tabs.count())]
            self.assertEqual(
                tabs,
                [
                    "Mi equipo",
                    "Sugerencias",
                    "Batería",
                    "Copias en el NAS",
                    "Redes",
                    "Usuarios",
                    "Equipos externos",
                    "Historial",
                ],
            )
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_sidebar_navigation_triggers_refresh_once(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            sections = [window.sidebar_nav.item(i).text() for i in range(window.sidebar_nav.count())]
            with patch.object(window, "refresh_v1_all") as refresh:
                window.sidebar_nav.setCurrentRow(sections.index("Centro de control"))
                refresh.assert_called_once()
                window.sidebar_nav.setCurrentRow(sections.index("Inicio"))
                window.sidebar_nav.setCurrentRow(sections.index("Centro de control"))
                refresh.assert_called_once()  # only loads automatically the first time
            self.assertEqual(window.main_tabs.currentIndex(), window.control_center_page_index)
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_views_render_fetched_text_and_errors_inline(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window._set_v1_view("Battery", '{"battery": {"available": true, "percent": 57, "charging": true}}')
            self.assertIn("57", window.v1_views["Battery"].toPlainText())
            # El resumen humano también se rellena, en español.
            self.assertIn("57", window.v1_summaries["Battery"].toPlainText())
            self.assertIn("Batería", window.v1_summaries["Battery"].toPlainText())

            def fake_run_operation(label, fn, *, on_success=None, **kwargs):
                result = fn()
                if on_success:
                    on_success(result)

            with (
                patch.object(window, "run_operation", side_effect=fake_run_operation),
                patch.object(window, "_v1_collect", side_effect=Exception("service exploded")),
            ):
                window.refresh_v1_tab("NAS")
            self.assertIn("service exploded", window.v1_views["NAS"].toPlainText())
            self.assertIn("No se ha podido cargar", window.v1_summaries["NAS"].toPlainText())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_collectors_work_against_real_services_offline(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "XDG_DATA_HOME": str(Path(tmp) / "data"),
                "XDG_STATE_HOME": str(Path(tmp) / "state"),
                "XDG_CONFIG_HOME": str(Path(tmp) / "config"),
                "HYPERGERY_V1_OFFLINE_MODE": "true",
                "HYPERGERY_NAS_STAGING_PATH": str(Path(tmp) / "nas"),
            }
            with patch.dict(os.environ, env):
                window = self.make_window(backend_cls, tmp)
                backend_cls.return_value.list_vms.side_effect = Exception("no libvirt in tests")
                battery_payload = window._v1_collect("Battery")
                self.assertIn("battery", battery_payload)
                network_payload = window._v1_collect("Network")
                self.assertIn("hg-net-default-lab", json.dumps(network_payload))
                guests_payload = window._v1_collect("Guests")
                self.assertIn("users", guests_payload)
                orchestrator_payload = window._v1_collect("Orchestrator")
                self.assertIn("plans", orchestrator_payload)
                logs_payload = window._v1_collect("Logs")
                self.assertIn("events", logs_payload)
                window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_export_report_writes_json(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        import json

        with tempfile.TemporaryDirectory() as tmp:
            window = self.make_window(backend_cls, tmp)
            window._set_v1_view("Battery", '{"battery": {"percent": 57}}')
            target = Path(tmp) / "report.json"
            with patch(
                "hypergery_ubuntu.ui_qt.main_window.QFileDialog.getSaveFileName",
                return_value=(str(target), ""),
            ):
                window.export_v1_report()
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("Battery", data["sections"])
            self.assertIn("57", data["sections"]["Battery"])
            self.assertIn("Informe del Centro de control exportado", window.activity_log.toPlainText())
            window.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
