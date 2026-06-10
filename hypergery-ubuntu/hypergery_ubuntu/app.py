from __future__ import annotations

import sys

from . import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv[1:] if argv else []
    # --version no debe requerir Qt ni un display.
    if "--version" in args or "-V" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    # v1.5: --first-run fuerza el asistente de primera ejecución. Se quita de
    # argv para que QApplication no lo vea como argumento desconocido.
    force_first_run = "--first-run" in args
    if force_first_run:
        full = list(sys.argv if argv is None else argv)
        argv = [item for item in full if item != "--first-run"]
    from .ui_qt.main import main as qt_main

    return qt_main(argv, force_first_run=force_first_run)


if __name__ == "__main__":
    raise SystemExit(main())
