"""v1.1 app identity: single version source (HG-BUG-0017), --version, .deb packaging."""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from hypergery_ubuntu import APP_NAME, __version__

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parents[1]


class SingleVersionSourceTests(unittest.TestCase):
    def test_pyproject_reads_version_from_package(self):
        data = tomllib.loads((SRC / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("version", data["project"].get("dynamic", []))
        self.assertNotIn("version", data["project"])
        self.assertEqual(
            data["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "hypergery_ubuntu.__version__",
        )

    def test_ui_display_version_is_the_package_version(self):
        from hypergery_ubuntu.ui_qt import styles

        self.assertEqual(styles.APP_DISPLAY_VERSION, __version__)

    def test_no_hardcoded_version_literals_outside_init(self):
        # The only assignment of the app version lives in __init__.py.
        for path in (SRC / "hypergery_ubuntu").rglob("*.py"):
            if path.name == "__init__.py" and path.parent.name == "hypergery_ubuntu":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("APP_DISPLAY_VERSION =", text, path)


class VersionFlagTests(unittest.TestCase):
    def test_app_version_flag_prints_and_exits_zero_without_qt(self):
        from hypergery_ubuntu.app import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["hypergery", "--version"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), f"{APP_NAME} {__version__}")

    def test_cli_version_flag(self):
        from hypergery_ubuntu.cli import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().strip(), f"hypergery-cli {__version__}")

    def test_agent_version_flag(self):
        from hypergery_ubuntu.agent import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().strip(), f"hypergery-agent {__version__}")


class DesktopEntryTests(unittest.TestCase):
    def _entries(self) -> dict[str, str]:
        text = (SRC / "packaging" / "hypergery.desktop").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "[Desktop Entry]")
        entries = {}
        for line in lines[1:]:
            if "=" in line:
                key, value = line.split("=", 1)
                entries[key] = value
        return entries

    def test_desktop_file_has_required_keys(self):
        entries = self._entries()
        self.assertEqual(entries["Type"], "Application")
        self.assertEqual(entries["Name"], "HyperGery")
        self.assertEqual(entries["Exec"], "hypergery")
        self.assertEqual(entries["Icon"], "hypergery")
        self.assertEqual(entries["Terminal"], "false")
        self.assertIn("System;", entries["Categories"])

    def test_icon_svg_exists(self):
        svg = (SRC / "packaging" / "hypergery.svg").read_text(encoding="utf-8")
        self.assertIn("<svg", svg)


class BuildDebTests(unittest.TestCase):
    SCRIPT = ROOT / "scripts" / "build-deb.sh"

    def test_script_static_checks(self):
        self.assertTrue(self.SCRIPT.is_file())
        text = self.SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertIn("dpkg-deb", text)
        result = subprocess.run(["bash", "-n", str(self.SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("dpkg-deb") is None, "dpkg-deb not available")
    def test_builds_installable_deb(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(self.SCRIPT)],
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "HYPERGERY_DIST_DIR": tmp},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            deb = Path(result.stdout.strip())
            self.assertTrue(deb.is_file(), deb)
            # El nombre del artefacto es parte del contrato de U1
            # (PEP 440 → Debian: .dev0 → ~dev0, rc0 → ~rc0).
            deb_version = __version__.replace(".dev", "~dev").replace("rc", "~rc")
            self.assertEqual(deb.name, f"hypergery_{deb_version}_all.deb")

            field = subprocess.run(
                ["dpkg-deb", "--field", str(deb), "Package", "Architecture", "Depends"],
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("Package: hypergery", field)
            self.assertIn("Architecture: all", field)
            self.assertIn("python3", field)
            # B4: la UI usa PySide6.QtNetwork (consola VNC); el .deb debe pedirlo
            # para que `hypergery --first-run` no falle con ModuleNotFoundError.
            self.assertIn("qtnetwork", field.lower())
            self.assertIn("qtgui", field.lower())

            contents = subprocess.run(
                ["dpkg-deb", "-c", str(deb)], capture_output=True, text=True
            ).stdout
            for expected in (
                "./usr/bin/hypergery",
                "./usr/bin/hypergery-cli",
                "./usr/bin/hypergery-agent",
                "./usr/lib/hypergery/hypergery_ubuntu/app.py",
                "./usr/share/applications/hypergery.desktop",
                "./usr/share/icons/hicolor/scalable/apps/hypergery.svg",
                "./usr/share/doc/hypergery/copyright",
            ):
                self.assertIn(expected, contents)
            self.assertNotIn("__pycache__", contents)


if __name__ == "__main__":
    unittest.main()
