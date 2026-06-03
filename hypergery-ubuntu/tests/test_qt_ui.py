import os
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from hypergery_ubuntu.ui_qt.dialogs import FILE_DIALOG_OPTIONS
from hypergery_ubuntu.ui_qt.main import configure_qt_application, configure_qt_environment


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


if __name__ == "__main__":
    unittest.main()
