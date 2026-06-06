import unittest
from pathlib import Path

from hypergery_ubuntu.ui_qt.console_helpers import (
    HOST_KEY_NAME,
    SPICE_INTEGRATED_MESSAGE,
    SPICE_STATUS_MESSAGE,
    can_capture_input,
    can_switch_display_to_vnc,
    centered_offset,
    console_message_for_graphics,
    console_mode_for_graphics,
    is_host_key,
    scale_to_fit_size,
    should_autoconnect_console,
    widget_to_framebuffer,
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
        self.assertIn("visor externo", console_message_for_graphics("spice"))
        self.assertIn("VNC", console_message_for_graphics("spice"))
        self.assertEqual(SPICE_STATUS_MESSAGE, "Pantalla SPICE detectada. Usa el visor externo o cambia esta máquina a VNC.")

    def test_capture_requires_connected_vnc(self):
        self.assertTrue(can_capture_input("vnc", True))
        self.assertFalse(can_capture_input("vnc", False))
        self.assertFalse(can_capture_input("spice", True))
        self.assertFalse(can_capture_input("spice", False))

    def test_switch_to_vnc_only_for_shutoff_spice(self):
        self.assertTrue(can_switch_display_to_vnc("spice", "shut off"))
        self.assertFalse(can_switch_display_to_vnc("spice", "running"))
        self.assertFalse(can_switch_display_to_vnc("vnc", "shut off"))

    def test_scale_to_fit_preserves_aspect_ratio(self):
        width, height, scale = scale_to_fit_size(1000, 700, 1024, 768)
        self.assertEqual((width, height), (933, 700))
        self.assertAlmostEqual(scale, 700 / 768)

    def test_centered_offset(self):
        self.assertEqual(centered_offset(1000, 700, 933, 700), (33, 0))
        self.assertEqual(centered_offset(800, 600, 800, 450), (0, 75))

    def test_widget_coordinates_translate_to_framebuffer(self):
        self.assertEqual(widget_to_framebuffer(500, 350, 1000, 700, 1024, 768), (512, 384))
        self.assertEqual(widget_to_framebuffer(33, 0, 1000, 700, 1024, 768), (0, 0))
        self.assertEqual(widget_to_framebuffer(999, 699, 1000, 700, 1024, 768), (1023, 766))
        self.assertEqual(widget_to_framebuffer(1200, 900, 1000, 700, 1024, 768), (1023, 767))

    def test_widget_coordinates_use_real_size_without_scale_to_fit(self):
        self.assertEqual(
            widget_to_framebuffer(300, 200, 1000, 700, 1024, 768, scale_to_fit=False),
            (300, 200),
        )

    def test_autoconnect_only_for_running_vnc(self):
        self.assertTrue(should_autoconnect_console("vnc", "running"))
        self.assertTrue(should_autoconnect_console("vnc", "paused"))
        self.assertFalse(should_autoconnect_console("vnc", "shut off"))
        self.assertFalse(should_autoconnect_console("spice", "running"))
        self.assertFalse(should_autoconnect_console("spice", "shut off"))

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
        self.assertIn("La consola integrada requiere VNC", source)
        self.assertIn("Abrir visor externo", source)
        self.assertIn("Cambiar a VNC", source)
        self.assertIn("SPICE_STATUS_MESSAGE", source)
        self.assertIn("self.scale_to_fit = True", source)

    def test_console_window_close_does_not_power_off_vm(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "hypergery_ubuntu" / "ui_qt" / "console.py").read_text(encoding="utf-8")
        close_body = source.split("def closeEvent", 1)[1]
        self.assertIn("disconnect_console", close_body)
        self.assertNotIn("shutdown", close_body)
        self.assertNotIn("force_off", close_body)


if __name__ == "__main__":
    unittest.main()
