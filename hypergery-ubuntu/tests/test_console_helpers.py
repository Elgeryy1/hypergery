import unittest
from pathlib import Path

from hypergery_ubuntu.ui_qt.console_helpers import (
    HOST_KEY_NAME,
    SPICE_INTEGRATED_MESSAGE,
    SPICE_STATUS_MESSAGE,
    can_capture_input,
    can_switch_display_to_vnc,
    console_message_for_graphics,
    console_mode_for_graphics,
    is_host_key,
)


class ConsoleHelperTests(unittest.TestCase):
    def test_right_ctrl_host_key_helper(self):
        self.assertEqual(HOST_KEY_NAME, "Right Ctrl")
        self.assertTrue(is_host_key(0x01000021, 105))
        self.assertFalse(is_host_key(0x01000020, 105))

    def test_console_mode_prefers_integrated_vnc_only(self):
        self.assertEqual(console_mode_for_graphics("vnc"), "integrated-vnc")
        self.assertEqual(console_mode_for_graphics("spice"), "external-spice")
        self.assertEqual(console_mode_for_graphics(""), "unavailable")

    def test_spice_message_points_to_external_viewer(self):
        self.assertEqual(console_message_for_graphics("spice"), SPICE_INTEGRATED_MESSAGE)
        self.assertIn("External Viewer", console_message_for_graphics("spice"))
        self.assertIn("VNC", console_message_for_graphics("spice"))
        self.assertEqual(SPICE_STATUS_MESSAGE, "SPICE display detected. Use External Viewer or switch this VM to VNC.")

    def test_capture_requires_connected_vnc(self):
        self.assertTrue(can_capture_input("vnc", True))
        self.assertFalse(can_capture_input("vnc", False))
        self.assertFalse(can_capture_input("spice", True))
        self.assertFalse(can_capture_input("spice", False))

    def test_switch_to_vnc_only_for_shutoff_spice(self):
        self.assertTrue(can_switch_display_to_vnc("spice", "shut off"))
        self.assertFalse(can_switch_display_to_vnc("spice", "running"))
        self.assertFalse(can_switch_display_to_vnc("vnc", "shut off"))

    def test_main_window_opens_console_window_not_detail_tab(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "hypergery_ubuntu" / "ui_qt" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("VmConsoleWindow", source)
        self.assertIn("self.console_windows", source)
        self.assertIn("connect_console()", source)
        self.assertNotIn('addTab(self.console_widget, "Console")', source)
        self.assertNotIn("IntegratedConsoleWidget", source)

    def test_console_source_has_spice_card_actions(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "hypergery_ubuntu" / "ui_qt" / "console.py").read_text(encoding="utf-8")
        self.assertIn("Integrated console requires VNC", source)
        self.assertIn("Open External Viewer", source)
        self.assertIn("Switch to VNC", source)
        self.assertIn("SPICE_STATUS_MESSAGE", source)

    def test_console_window_close_does_not_power_off_vm(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "hypergery_ubuntu" / "ui_qt" / "console.py").read_text(encoding="utf-8")
        close_body = source.split("def closeEvent", 1)[1]
        self.assertIn("disconnect_console", close_body)
        self.assertNotIn("shutdown", close_body)
        self.assertNotIn("force_off", close_body)


if __name__ == "__main__":
    unittest.main()
