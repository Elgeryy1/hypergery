from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DockerHubStaticTests(unittest.TestCase):
    def test_docker_hub_files_exist(self):
        self.assertTrue((ROOT / "docker" / "Dockerfile").is_file())
        self.assertTrue((ROOT / "docker" / "docker-compose.yml").is_file())
        self.assertTrue((ROOT / "docker" / ".env.example").is_file())
        self.assertTrue((ROOT / "docker" / "data" / ".gitkeep").is_file())

    def test_compose_exposes_hub_without_secrets(self):
        compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("${HYPERGERY_HUB_PORT:-8765}:8765", compose)
        self.assertIn("${HYPERGERY_NAS_ROOT:-/share/CACHEDEV2_DATA/Gerard/hypergery}:/hypergery", compose)
        self.assertIn("HYPERGERY_HUB_DB=/data/hypergery-hub.sqlite", compose)
        self.assertNotIn("password", compose.lower())
        self.assertNotIn("ssh_key", compose.lower())
        self.assertNotIn("Y:\\", compose)

    def test_env_example_uses_qnap_nas_root(self):
        env_example = (ROOT / "docker" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("HYPERGERY_HUB_PORT=8765", env_example)
        self.assertIn("HYPERGERY_NAS_ROOT=/share/CACHEDEV2_DATA/Gerard/hypergery", env_example)


if __name__ == "__main__":
    unittest.main()
