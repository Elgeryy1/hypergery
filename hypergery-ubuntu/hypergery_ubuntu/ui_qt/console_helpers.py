from __future__ import annotations


HOST_KEY_NAME = "Right Ctrl"


def is_host_key(key: int, native_scan_code: int = 0) -> bool:
    # Qt.Key_Control is shared by both Ctrl keys; X11 evdev scancode 105 is Right Ctrl.
    return key == 0x01000021 and native_scan_code in {0, 105}
