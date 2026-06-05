import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu import cli


class V1CliTests(unittest.TestCase):
    def run_cli(self, args, env=None):
        buf = StringIO()
        overrides = {"HYPERGERY_V1_OFFLINE_MODE": "true"}
        overrides.update(env or {})
        with patch.dict(os.environ, overrides):
            with redirect_stdout(buf):
                code = cli.main(args)
        return code, buf.getvalue()

    def with_tmp_env(self, tmp):
        return {
            "XDG_DATA_HOME": str(Path(tmp) / "data"),
            "XDG_STATE_HOME": str(Path(tmp) / "state"),
            "XDG_CONFIG_HOME": str(Path(tmp) / "config"),
            "HYPERGERY_NAS_STAGING_PATH": str(Path(tmp) / "nas"),
        }

    def test_v1_labs_validate_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            code, output = self.run_cli(["v1", "labs", "validate"], env=env)
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertIn("default-lab", data)
        self.assertTrue(data["default-lab"]["ok"])

    def test_v1_network_validate_ok_and_conflict_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            code, output = self.run_cli(["v1", "network", "validate"], env=env)
            self.assertEqual(code, 0)
            data = json.loads(output)
            self.assertTrue(data["ok"])
            # Force a CIDR conflict by writing a second lab with the same subnet.
            from hypergery_ubuntu.labs import LabStore

            with patch.dict(os.environ, env):
                store = LabStore(Path(env["XDG_DATA_HOME"]) / "hypergery")
                first = store.list_labs()[0]
                clash = store.create_lab("Clash Lab")
                clash["subnet"] = first["subnet"]
                store.write_lab(clash)
            code, output = self.run_cli(["v1", "network", "validate"], env=env)
            self.assertEqual(code, 1)
            self.assertIn("CIDR conflict", output)

    def test_v1_guests_list_empty_then_with_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            code, output = self.run_cli(["v1", "guests", "list"], env=env)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["users"], [])
            from hypergery_ubuntu.v1.rbac import User, UserStore

            with patch.dict(os.environ, env):
                UserStore().add_user(User(id="alumno", role="Guest"))
            code, output = self.run_cli(["v1", "guests", "list"], env=env)
            users = json.loads(output)["users"]
            self.assertEqual(users[0]["id"], "alumno")
            self.assertNotIn("can_use_remote_compute", users[0]["effective_permissions"])

    def test_v1_nas_commit_is_dry_run_without_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            Path(env["HYPERGERY_NAS_STAGING_PATH"]).mkdir(parents=True)
            code, output = self.run_cli(["v1", "nas", "commit", "--lab", "default-lab"], env=env)
            self.assertEqual(code, 0)
            data = json.loads(output)
            self.assertTrue(data["dry_run"])
            self.assertFalse((Path(env["HYPERGERY_NAS_STAGING_PATH"]) / "labs-commits").exists())
            code, output = self.run_cli(["v1", "nas", "commit", "--lab", "default-lab", "--confirm"], env=env)
            self.assertEqual(code, 0)
            data = json.loads(output)
            self.assertFalse(data["dry_run"])
            self.assertTrue(data["verified"])
            code, output = self.run_cli(["v1", "nas", "status"], env=env)
            status = json.loads(output)
            self.assertTrue(status["health"]["ok"])
            self.assertEqual(len(status["commits"]), 1)

    def test_v1_orchestrator_plan_local_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            with patch("hypergery_ubuntu.v1.cli_v1._local_backend", return_value=None):
                code, output = self.run_cli(["v1", "orchestrator", "plan", "--local-only"], env=env)
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertIn("plans", data)

    def test_v1_health_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            Path(env["HYPERGERY_NAS_STAGING_PATH"]).mkdir(parents=True)
            code, output = self.run_cli(["v1", "health"], env=env)
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertTrue(data["hosts"])
        self.assertTrue(data["nas"]["ok"])
        self.assertIn("battery", data)

    def test_v1_telemetry_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.with_tmp_env(tmp)
            code, output = self.run_cli(["v1", "telemetry"], env=env)
            self.assertEqual(code, 0)
            data = json.loads(output)
            self.assertGreater(data["sample"]["ram_total_mib"], 0)
            history = Path(env["XDG_STATE_HOME"]) / "hypergery" / "telemetry" / "history.json"
            self.assertTrue(history.is_file())


if __name__ == "__main__":
    unittest.main()
