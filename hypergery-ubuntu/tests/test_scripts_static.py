from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCRIPTS = (
    "scripts/start-second-host.sh",
    "scripts/install-agent-user-service.sh",
)


class ScriptsStaticTests(unittest.TestCase):
    def test_scripts_exist_and_pass_bash_syntax_check(self):
        for rel_path in SCRIPTS:
            script = ROOT / rel_path
            self.assertTrue(script.is_file(), rel_path)
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{rel_path}: {result.stderr}")

    def test_agent_service_installer_is_user_level_and_credential_free(self):
        script = (ROOT / "scripts/install-agent-user-service.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl --user", script)
        self.assertIn("hypergery-agent.service", script)
        self.assertIn("agent run", script)
        self.assertIn("HYPERGERY_HUB_URL", script)
        self.assertIn("loginctl enable-linger", script)
        # The unit installation itself must never invoke sudo; the only sudo
        # mention is the optional manual enable-linger hint.
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("echo"):
                continue
            self.assertNotIn("sudo", stripped, f"unexpected sudo usage: {line}")
        # No credential material is referenced or persisted in actual code
        # (comments may mention the guarantee itself).
        code_lines = [
            line for line in script.splitlines() if line.strip() and not line.strip().startswith("#")
        ]
        lowered = "\n".join(code_lines).lower()
        for needle in ("password", "passwd", "token", "secret", "credentials="):
            self.assertNotIn(needle, lowered)

    def test_launchers_default_to_nas_hub(self):
        for rel_path in SCRIPTS:
            script = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn("http://192.168.1.150:8765", script, rel_path)

    def test_hub_default_is_parametrized_not_hardcoded(self):
        # HG-BUG-0020: la IP es el Hub del NAS privado de Gerard y solo puede
        # ser el VALOR POR DEFECTO; HYPERGERY_HUB_URL debe poder sustituirla
        # sin editar el script.
        for rel_path in SCRIPTS:
            script = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn(
                "${HYPERGERY_HUB_URL:-http://192.168.1.150:8765}", script, rel_path
            )


if __name__ == "__main__":
    unittest.main()
