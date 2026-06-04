from __future__ import annotations


HOST_KEY_NAME = "Right Ctrl"
SPICE_INTEGRATED_MESSAGE = "This VM uses SPICE. Use External Viewer or switch display to VNC for integrated console."
NO_DISPLAY_MESSAGE = "Integrated console is unavailable. Use External Viewer or configure a local VNC display."


def is_host_key(key: int, native_scan_code: int = 0) -> bool:
    # Qt.Key_Control is shared by both Ctrl keys; X11 evdev scancode 105 is Right Ctrl.
    return key == 0x01000021 and native_scan_code in {0, 105}


def console_mode_for_graphics(graphics: str | None) -> str:
    normalized = (graphics or "").strip().lower()
    if normalized == "vnc":
        return "integrated-vnc"
    if normalized == "spice":
        return "external-spice"
    return "unavailable"


def console_message_for_graphics(graphics: str | None) -> str:
    mode = console_mode_for_graphics(graphics)
    if mode == "integrated-vnc":
        return "Click Connect to open the VM console."
    if mode == "external-spice":
        return SPICE_INTEGRATED_MESSAGE
    return NO_DISPLAY_MESSAGE
