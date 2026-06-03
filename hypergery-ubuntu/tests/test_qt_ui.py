import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from hypergery_ubuntu.ui_qt.dialogs import FILE_DIALOG_OPTIONS
from hypergery_ubuntu.ui_qt.main import configure_qt_application


class QtUiTests(unittest.TestCase):
    def test_qt_uses_non_native_file_dialogs(self):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)

        configure_qt_application()

        self.assertTrue(QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs))
        self.assertTrue(FILE_DIALOG_OPTIONS & QFileDialog.Option.DontUseNativeDialog)


if __name__ == "__main__":
    unittest.main()
