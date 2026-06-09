"""v1.6: comprobaciones estáticas del proyecto Android (sin SDK local)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
SRC = ANDROID / "app" / "src" / "main" / "java" / "com" / "hypergery" / "companion"


class AndroidProjectTests(unittest.TestCase):
    def test_gradle_project_structure(self):
        for rel in (
            "settings.gradle.kts",
            "build.gradle.kts",
            "app/build.gradle.kts",
            "app/src/main/AndroidManifest.xml",
            "README.md",
        ):
            self.assertTrue((ANDROID / rel).is_file(), rel)
        workflow = ROOT / ".github" / "workflows" / "android.yml"
        fallback = ANDROID / "ci" / "android.yml"
        self.assertTrue(workflow.is_file() or fallback.is_file())

    def test_manifest_only_needs_internet(self):
        manifest = (ANDROID / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        permissions = re.findall(r'uses-permission android:name="([^"]+)"', manifest)
        self.assertEqual(permissions, ["android.permission.INTERNET"])

    def test_api_client_exposes_only_safe_actions(self):
        client = (SRC / "api" / "ApiClient.kt").read_text(encoding="utf-8")
        self.assertIn('"Authorization", "Bearer $token"', client)
        for forbidden in ("force-off", "force_off", "undefine", "delete-vm", "delete_vm"):
            self.assertNotIn(forbidden, client, f"acción destructiva en la app: {forbidden}")
        self.assertIn("/snapshot", client)
        self.assertIn('put("confirm", true)', client)

    def test_ui_confirms_every_action(self):
        screen = (SRC / "ui" / "VmListScreen.kt").read_text(encoding="utf-8")
        self.assertIn("AlertDialog", screen)
        self.assertIn("Confirmar", screen)

    def test_long_poll_uses_progress_channel_contract(self):
        client = (SRC / "api" / "ApiClient.kt").read_text(encoding="utf-8")
        self.assertIn("/progress/", client)
        self.assertIn("since=", client)


if __name__ == "__main__":
    unittest.main()
