from __future__ import annotations

import sys

from . import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv[1:] if argv else []
    # --version no debe requerir Qt ni un display.
    if "--version" in args or "-V" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    from .ui_qt.main import main as qt_main

    return qt_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
