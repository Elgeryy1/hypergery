from __future__ import annotations

import sys


def configure_qt_application() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ModuleNotFoundError:
        print(
            "HyperGery Qt UI requires PySide6. Run ./scripts/install-ubuntu-deps.sh, then: cd hypergery-ubuntu && python3 -m pip install -e .",
            file=sys.stderr,
        )
        return 2

    from .main_window import MainWindow

    configure_qt_application()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("HyperGery")
    app.setOrganizationName("HyperGery")
    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(None, "HyperGery", str(exc))
        return 2
    window.show()
    return app.exec()
