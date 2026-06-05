import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu.config import HyperGeryConfig, config_path, effective_config, effective_value


class ConfigTests(unittest.TestCase):
    def test_config_roundtrip_writes_only_known_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            saved = HyperGeryConfig(
                hub_url="http://hub.local:8765",
                host_id="source",
                host_name="Source Host",
                nas_staging_path="/mnt/hypergery-nas/hypergery",
                default_display="vnc",
            )
            self.assertEqual(saved.save(path), path)
            loaded = HyperGeryConfig.load(path)
            self.assertEqual(loaded.hub_url, "http://hub.local:8765")
            self.assertEqual(loaded.host_id, "source")
            self.assertEqual(loaded.default_display, "vnc")

    def test_effective_config_prefers_environment_over_config_over_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            HyperGeryConfig(hub_url="http://config.local:8765", host_id="from-config").save(path)
            env = {"HYPERGERY_HUB_URL": "http://env.local:8765"}
            with patch.dict(os.environ, env, clear=True):
                values = effective_config(path)
            self.assertEqual(values["hub_url"].value, "http://env.local:8765")
            self.assertEqual(values["hub_url"].source, "env:HYPERGERY_HUB_URL")
            self.assertEqual(values["host_id"].value, "from-config")
            self.assertEqual(values["host_id"].source, "config")
            self.assertEqual(values["default_display"].value, "vnc")
            self.assertEqual(values["default_display"].source, "default")

    def test_registry_url_is_compatible_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HYPERGERY_REGISTRY_URL": "http://registry.local:8765"},
            clear=True,
        ):
            self.assertEqual(effective_value("hub_url", Path(tmp) / "missing.json"), "http://registry.local:8765")

    def test_config_path_uses_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}, clear=True):
            self.assertEqual(config_path(), Path(tmp) / "hypergery" / "config.json")


if __name__ == "__main__":
    unittest.main()
