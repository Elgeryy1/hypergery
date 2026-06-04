import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

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


if __name__ == "__main__":
    unittest.main()
