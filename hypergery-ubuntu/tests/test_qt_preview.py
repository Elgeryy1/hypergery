import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

# A tiny valid PPM (2x2, white/black) that QPixmap can decode.
PPM_BYTES = b"P6\n2 2\n255\n" + bytes([255, 255, 255, 0, 0, 0, 0, 0, 0, 255, 255, 255])

if HAS_PYSIDE6:
    from PySide6.QtWidgets import QApplication


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class ScreenshotHelperTests(unittest.TestCase):
    def test_returns_none_without_virsh(self):
        from hypergery_ubuntu.ui_qt.screenshot import capture_vm_screenshot

        calls = []

        def runner(*args, **kwargs):  # pragma: no cover - must not run
            calls.append(args)
            raise AssertionError("runner should not be called without virsh")

        with patch("hypergery_ubuntu.ui_qt.screenshot.shutil.which", return_value=None):
            self.assertIsNone(capture_vm_screenshot("dc01", runner=runner))
        self.assertEqual(calls, [])

    def test_returns_bytes_on_success(self):
        from hypergery_ubuntu.ui_qt.screenshot import capture_vm_screenshot

        def runner(cmd, **kwargs):
            # virsh writes the screenshot to the last argument (the temp path).
            Path(cmd[-1]).write_bytes(PPM_BYTES)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("hypergery_ubuntu.ui_qt.screenshot.shutil.which", return_value="/usr/bin/virsh"):
            data = capture_vm_screenshot("dc01", runner=runner)
        self.assertEqual(data, PPM_BYTES)

    def test_returns_none_on_virsh_error(self):
        from hypergery_ubuntu.ui_qt.screenshot import capture_vm_screenshot

        def runner(cmd, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="domain is not running")

        with patch("hypergery_ubuntu.ui_qt.screenshot.shutil.which", return_value="/usr/bin/virsh"):
            self.assertIsNone(capture_vm_screenshot("dc01", runner=runner))

    def test_temp_file_is_cleaned_up(self):
        from hypergery_ubuntu.ui_qt import screenshot

        captured_path = {}

        def runner(cmd, **kwargs):
            captured_path["p"] = cmd[-1]
            Path(cmd[-1]).write_bytes(PPM_BYTES)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("hypergery_ubuntu.ui_qt.screenshot.shutil.which", return_value="/usr/bin/virsh"):
            screenshot.capture_vm_screenshot("dc01", runner=runner)
        self.assertFalse(Path(captured_path["p"]).exists())


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class PreviewRenderTests(unittest.TestCase):
    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_real_capture_replaces_placeholder_for_selected_vm(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window._preview_target = "dc01"
            window._on_preview_captured("dc01", PPM_BYTES)
            # The real screenshot shows; the name/hint placeholder is hidden.
            self.assertFalse(window.preview_image.isHidden())
            self.assertFalse(window.preview_image.pixmap().isNull())
            self.assertTrue(window.preview_screen_name.isHidden())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_stale_capture_is_ignored(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window._preview_target = "cl01"
            # A late result for a no-longer-selected VM must not paint anything.
            window._on_preview_captured("dc01", PPM_BYTES)
            self.assertTrue(window.preview_image.isHidden())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_powered_off_vm_shows_no_signal(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.backend import VmSummary
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            vm = VmSummary(name="cl01", state="shut off", lab_id="lab", ram_mib=1024, vcpus=1)
            window._update_preview(vm)
            self.assertTrue(window.preview_image.isHidden())
            self.assertEqual(window.preview_screen_name.text(), "cl01")
            self.assertIn("sin señal", window.preview_screen_hint.text().lower())
            window.close()
        self.assertIsNotNone(app)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_invalid_capture_falls_back_to_hint(self, backend_cls):
        app = QApplication.instance() or QApplication([])
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window._preview_target = "dc01"
            window._on_preview_captured("dc01", b"not an image")
            self.assertTrue(window.preview_image.isHidden())
            self.assertEqual(window.preview_screen_hint.text(), "Sin vista disponible")
            window.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
