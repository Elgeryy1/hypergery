import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from hypergery_ubuntu import cli
from hypergery_ubuntu.doctor import DoctorItem, doctor_exit_code, format_doctor_items


class DoctorTests(unittest.TestCase):
    def test_doctor_exit_code_fails_only_for_critical_failures(self):
        self.assertEqual(doctor_exit_code([DoctorItem("WARN", "docker", "missing")]), 0)
        self.assertEqual(doctor_exit_code([DoctorItem("FAIL", "hub", "offline", critical=True)]), 1)

    def test_format_doctor_items_uses_clear_status_prefixes(self):
        text = format_doctor_items([DoctorItem("OK", "python", "3.x"), DoctorItem("FAIL", "hub", "offline")])
        self.assertIn("OK   python: 3.x", text)
        self.assertIn("FAIL hub: offline", text)

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
