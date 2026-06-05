import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hypergery_ubuntu import cli
from hypergery_ubuntu.config import EffectiveValue
from hypergery_ubuntu.doctor import DoctorItem, _current_group_names, collect_doctor_items, doctor_exit_code, format_doctor_items


class DoctorTests(unittest.TestCase):
    def test_doctor_exit_code_fails_only_for_critical_failures(self):
        self.assertEqual(doctor_exit_code([DoctorItem("WARN", "docker", "missing")]), 0)
        self.assertEqual(doctor_exit_code([DoctorItem("FAIL", "hub", "offline", critical=True)]), 1)

    def test_format_doctor_items_uses_clear_status_prefixes(self):
        text = format_doctor_items([DoctorItem("OK", "python", "3.x"), DoctorItem("FAIL", "hub", "offline")])
        self.assertIn("OK   python: 3.x", text)
        self.assertIn("FAIL hub: offline", text)

    def _effective_config(self, nas_path: str, source: str = "default"):
        return {
            "hub_url": EffectiveValue("http://127.0.0.1:8765", "default"),
            "host_id": EffectiveValue("host", "default"),
            "host_name": EffectiveValue("host", "default"),
            "nas_staging_path": EffectiveValue(nas_path, source),
            "default_display": EffectiveValue("vnc", "default"),
            "default_iso_folder": EffectiveValue(str(Path.home()), "default"),
            "default_vm_storage_path": EffectiveValue("", "default"),
        }

    def _collect_with_baseline_patches(self, nas_path: str, source: str = "default"):
        def path_exists(path):
            return str(path) == "/dev/kvm"

        with (
            patch("hypergery_ubuntu.doctor.effective_config", return_value=self._effective_config(nas_path, source)),
            patch("hypergery_ubuntu.doctor._current_group_names", return_value={"kvm", "libvirt"}),
            patch("hypergery_ubuntu.doctor._which", side_effect=lambda name, critical=True: DoctorItem("OK", name, "/usr/bin/" + name)),
            patch("hypergery_ubuntu.doctor.shutil.which", return_value=None),
            patch("hypergery_ubuntu.doctor.Path.exists", path_exists),
            patch("hypergery_ubuntu.doctor.os.access", return_value=True),
            patch("hypergery_ubuntu.doctor.RegistryClient") as registry_cls,
        ):
            registry_cls.return_value.health.return_value = {"status": "ok"}
            registry_cls.return_value.list_vms.return_value = []
            return collect_doctor_items()

    def test_collect_doctor_items_skips_orphan_group_ids(self):
        with (
            patch("hypergery_ubuntu.doctor.os.getgroups", return_value=[12345]),
            patch("hypergery_ubuntu.doctor.os.getgid", return_value=67890),
            patch("hypergery_ubuntu.doctor.grp.getgrgid", side_effect=KeyError),
        ):
            groups = _current_group_names()

        self.assertEqual(groups, set())

    def test_default_missing_nas_staging_path_warns_and_exit_is_zero(self):
        items = self._collect_with_baseline_patches("/missing-default-nas", "default")
        nas_item = next(item for item in items if item.name == "nas staging path")

        self.assertEqual(nas_item.status, "WARN")
        self.assertFalse(nas_item.critical)
        self.assertEqual(doctor_exit_code(items), 0)

    def test_env_missing_nas_staging_path_fails_critically(self):
        items = self._collect_with_baseline_patches("/missing-env-nas", "env:HYPERGERY_NAS_STAGING_PATH")
        nas_item = next(item for item in items if item.name == "nas staging path")

        self.assertEqual(nas_item.status, "FAIL")
        self.assertTrue(nas_item.critical)
        self.assertEqual(doctor_exit_code(items), 1)

    def test_existing_writable_nas_staging_path_is_ok(self):
        with TemporaryDirectory() as tmp:
            items = self._collect_with_baseline_patches(tmp, "env:HYPERGERY_NAS_STAGING_PATH")
        nas_item = next(item for item in items if item.name == "nas staging path")

        self.assertEqual(nas_item.status, "OK")
        self.assertFalse(nas_item.critical)

    @patch("hypergery_ubuntu.doctor.collect_doctor_items")
    @patch("hypergery_ubuntu.cli.HyperGeryBackend")
    def test_cli_doctor_does_not_create_backend(self, backend_cls, collect):
        collect.return_value = [DoctorItem("OK", "python", "3.x")]
        buf = StringIO()
        with redirect_stdout(buf):
            code = cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("OK", buf.getvalue())
        backend_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
