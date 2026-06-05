import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.v1.errors import (
    BatteryUnavailableError,
    HostOfflineError,
    LabValidationError,
    NasUnavailableError,
    NetworkConflictError,
    PermissionDeniedError,
    TeleportError,
    error_code,
)
from hypergery_ubuntu.v1.hglog import CATEGORIES, StructuredLogger, new_operation_id
from hypergery_ubuntu.v1.settings import V1Settings


class V1ErrorTests(unittest.TestCase):
    def test_errors_subclass_hypergery_error_with_codes(self):
        cases = {
            HostOfflineError: "HOST_OFFLINE",
            NasUnavailableError: "NAS_UNAVAILABLE",
            TeleportError: "TELEPORT_FAILED",
            BatteryUnavailableError: "BATTERY_UNAVAILABLE",
            LabValidationError: "LAB_INVALID",
            NetworkConflictError: "NETWORK_CONFLICT",
            PermissionDeniedError: "PERMISSION_DENIED",
        }
        for exc_type, code in cases.items():
            exc = exc_type("boom")
            self.assertIsInstance(exc, HyperGeryError)
            self.assertEqual(error_code(exc), code)
        self.assertEqual(error_code(HyperGeryError("x")), "HYPERGERY_ERROR")
        self.assertEqual(error_code(ValueError("x")), "INTERNAL_ERROR")


class V1SettingsTests(unittest.TestCase):
    def test_defaults_are_safe_and_valid(self):
        settings = V1Settings().validate()
        self.assertTrue(settings.dry_run_default)
        self.assertFalse(settings.offline_mode)
        self.assertEqual(settings.battery_mode, "recommend_only")
        self.assertFalse(settings.experimental_memdiff)
        self.assertEqual(settings.teleport_default_mode, "dry_run")

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1-settings.json"
            original = V1Settings(battery_eco_percent=60, log_level="debug")
            original.save(path)
            loaded = V1Settings.load(path)
            self.assertEqual(loaded.battery_eco_percent, 60)
            self.assertEqual(loaded.log_level, "debug")

    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1-settings.json"
            V1Settings(battery_offload_percent=35).save(path)
            with patch.dict(os.environ, {"HYPERGERY_V1_BATTERY_OFFLOAD_PERCENT": "25", "HYPERGERY_V1_OFFLINE_MODE": "true"}):
                loaded = V1Settings.load(path)
            self.assertEqual(loaded.battery_offload_percent, 25)
            self.assertTrue(loaded.offline_mode)

    def test_invalid_settings_raise_clear_errors(self):
        with self.assertRaises(HyperGeryError):
            V1Settings(battery_eco_percent=10, battery_offload_percent=30).validate()
        with self.assertRaises(HyperGeryError):
            V1Settings(battery_mode="aggressive").validate()
        with self.assertRaises(HyperGeryError):
            V1Settings(log_level="verbose").validate()
        with self.assertRaises(HyperGeryError):
            V1Settings(teleport_default_mode="warp").validate()
        with self.assertRaises(HyperGeryError):
            V1Settings(api_port=0).validate()

    def test_corrupt_settings_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1-settings.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(HyperGeryError):
                V1Settings.load(path)


class StructuredLoggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.logger = StructuredLogger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_writes_jsonl_with_all_fields(self):
        record = self.logger.info(
            "teleport",
            "package copied",
            module="teleport",
            host="lenovo",
            lab_id="asr-lab",
            vm_id="vm1",
            operation_id="teleport-abc",
            details={"bytes": 1024},
        )
        self.assertEqual(record["category"], "teleport")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        stored = json.loads(lines[0])
        for field in ("timestamp", "level", "category", "module", "host", "lab_id", "vm_id", "operation_id", "message", "details"):
            self.assertIn(field, stored)
        self.assertEqual(stored["details"], {"bytes": 1024})

    def test_level_threshold_filters_records(self):
        self.logger.set_level("warning")
        self.assertIsNone(self.logger.info("app", "ignored"))
        self.assertIsNotNone(self.logger.error("app", "kept"))
        self.assertEqual(len(self.logger.recent()), 1)

    def test_unknown_category_or_level_rejected(self):
        with self.assertRaises(HyperGeryError):
            self.logger.info("spaceship", "nope")
        with self.assertRaises(HyperGeryError):
            self.logger.log("loud", "app", "nope")
        with self.assertRaises(HyperGeryError):
            self.logger.set_level("silent")

    def test_query_filters_by_category_operation_and_text(self):
        op = new_operation_id("nas-commit")
        self.logger.info("nas", "commit started", operation_id=op)
        self.logger.info("nas", "commit verified", operation_id=op)
        self.logger.info("battery", "battery low", host="laptop")
        self.assertEqual(len(self.logger.query(category="nas")), 2)
        self.assertEqual(len(self.logger.query(operation_id=op)), 2)
        self.assertEqual(len(self.logger.query(contains="verified")), 1)
        self.assertEqual(len(self.logger.query(host="laptop")), 1)
        self.assertEqual(len(self.logger.query(category="nas", from_file=True)), 2)

    def test_export_writes_filtered_json(self):
        self.logger.info("api", "request served")
        self.logger.error("api", "request failed")
        destination = Path(self.tmp.name) / "export.json"
        self.logger.export(destination, category="api", level="error")
        data = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["message"], "request failed")

    def test_operation_ids_are_unique_and_kind_prefixed(self):
        first = new_operation_id("teleport")
        second = new_operation_id("teleport")
        self.assertTrue(first.startswith("teleport-"))
        self.assertNotEqual(first, second)

    def test_categories_cover_goal_requirements(self):
        for category in ("app", "agent", "hub", "nas", "teleport", "battery", "orchestrator", "network", "guest", "api", "tests"):
            self.assertIn(category, CATEGORIES)


if __name__ == "__main__":
    unittest.main()
