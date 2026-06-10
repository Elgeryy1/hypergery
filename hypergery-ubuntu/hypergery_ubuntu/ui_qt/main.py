from __future__ import annotations

import os
import sys


def configure_qt_environment() -> None:
    if not os.environ.get("QT_QPA_PLATFORM") and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "gtk3")
    os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")


def configure_qt_application() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)


def main(argv: list[str] | None = None) -> int:
    configure_qt_environment()
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ModuleNotFoundError:
        print(
            "HyperGery Qt UI requires PySide6. Run ./scripts/install-ubuntu-deps.sh, then: cd hypergery-ubuntu && python3 -m pip install -e .",
            file=sys.stderr,
        )
        return 2

    from .. import APP_NAME, __version__
    from .icons import app_icon
    from .main_window import MainWindow
    from .screenshot import cleanup_stale_previews

    # HG-BUG-0019: barre capturas de preview huérfanas de una sesión anterior.
    cleanup_stale_previews()
    configure_qt_application()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("hypergery")
    app.setWindowIcon(app_icon())
    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(None, "HyperGery", str(exc))
        return 2
    window.show()
    return app.exec()
