"""v1.1 packaging UAT (U1): build script alcanzable, entry points y `python3 -m`.

Cubre los fallos reales del primer UAT de v1.1:
- `./scripts/build-deb.sh` no existía con cwd=hypergery-ubuntu/ (solo en la raíz).
- `hypergery-agent` no existía en el entorno editable (entry point añadido
  después de la instalación editable original).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from hypergery_ubuntu import __version__

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parents[1]

EXPECTED_CONSOLE_SCRIPTS = {
    "hypergery": "hypergery_ubuntu.app:main",
    "hypergery-cli": "hypergery_ubuntu.cli:main",
    "hypergery-agent": "hypergery_ubuntu.agent:main",
}


class BuildScriptLocationTests(unittest.TestCase):
    def test_build_script_exists_at_repo_root(self):
        script = ROOT / "scripts" / "build-deb.sh"
        self.assertTrue(script.is_file(), script)

    def test_build_script_wrapper_exists_for_cwd_hypergery_ubuntu(self):
        # U1 real se ejecutó con cwd=hypergery-ubuntu/: ambas rutas deben valer.
        wrapper = SRC / "scripts" / "build-deb.sh"
        self.assertTrue(wrapper.is_file(), wrapper)
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("scripts/build-deb.sh", text)
        result = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ConsoleScriptTests(unittest.TestCase):
    def test_pyproject_defines_the_three_console_scripts(self):
        data = tomllib.loads((SRC / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["scripts"], EXPECTED_CONSOLE_SCRIPTS)

    def test_entry_modules_are_runnable_with_python_dash_m(self):
        # Los lanzadores del .deb ejecutan `python3 -m <módulo>`: sin el guard
        # `if __name__ == "__main__"` el comando instalado no haría nada.
        for rel in ("__main__.py", "cli.py", "agent.py"):
            text = (SRC / "hypergery_ubuntu" / rel).read_text(encoding="utf-8")
            self.assertIn('if __name__ == "__main__"', text, rel)

    def test_version_flag_via_python_dash_m_for_all_commands(self):
        # Mismo camino que los wrappers de /usr/bin del .deb; no requiere Qt.
        for module, prog in (
            ("hypergery_ubuntu", "HyperGery"),
            ("hypergery_ubuntu.cli", "hypergery-cli"),
            ("hypergery_ubuntu.agent", "hypergery-agent"),
        ):
            result = subprocess.run(
                [sys.executable, "-m", module, "--version"],
                capture_output=True,
                text=True,
                cwd=str(SRC),
            )
            self.assertEqual(result.returncode, 0, f"{module}: {result.stderr}")
            self.assertEqual(result.stdout.strip(), f"{prog} {__version__}", module)


if __name__ == "__main__":
    unittest.main()
