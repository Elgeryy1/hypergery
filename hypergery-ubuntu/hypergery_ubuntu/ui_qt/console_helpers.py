from __future__ import annotations

import socket


HOST_KEY_NAME = "Ctrl derecho"
SPICE_INTEGRATED_MESSAGE = "Esta máquina usa SPICE. Usa el visor externo o cambia la pantalla a VNC para la consola integrada."
SPICE_STATUS_MESSAGE = "Pantalla SPICE detectada. Usa el visor externo o cambia esta máquina a VNC."
NO_DISPLAY_MESSAGE = "La consola integrada no está disponible. Usa el visor externo o configura una pantalla VNC local."

# Connecting the VNC socket can block the UI thread if the host or VM is
# unreachable, so the connect is done off-thread with this hard timeout.
VNC_CONNECT_TIMEOUT = 10.0
VNC_CONNECTING_MESSAGE = "Conectando…"
VNC_FAILED_MESSAGE = "No se pudo conectar a la consola"
VNC_TIMEOUT_REASON = "Se agotó el tiempo de espera (10 s) al conectar con la consola."


def blocking_vnc_connect(host: str, port: int, timeout: float = VNC_CONNECT_TIMEOUT) -> int:
    """Open a TCP connection to the VNC server with a hard ``timeout``.

    Runs the blocking ``connect`` so it can be done on a worker thread. Returns a
    detached socket *file descriptor* that the caller adopts into a ``QTcpSocket``
    via ``setSocketDescriptor``. Raises ``TimeoutError`` when the connect times
    out and ``OSError`` for every other connection failure.
    """
    sock = socket.create_connection((host, int(port)), timeout=timeout)
    try:
        sock.setblocking(True)
        sock.settimeout(None)
        # Hand ownership of the OS handle to the caller; ``detach`` keeps the fd
        # open while letting this Python socket object be garbage collected.
        return sock.detach()
    except BaseException:
        sock.close()
        raise


def vnc_connect_error_reason(exc: BaseException) -> str:
    """Map a connect exception to a short Spanish reason for the UI."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return VNC_TIMEOUT_REASON
    detail = str(exc).strip()
    return detail or "No se pudo abrir la conexión con el servidor VNC."


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
        return "Pulsa «Conectar» para abrir la consola de la máquina."
    if mode == "external-spice":
        return SPICE_INTEGRATED_MESSAGE
    return NO_DISPLAY_MESSAGE


def can_capture_input(graphics: str | None, connected: bool) -> bool:
    return console_mode_for_graphics(graphics) == "integrated-vnc" and connected


def can_switch_display_to_vnc(graphics: str | None, state: str | None) -> bool:
    return console_mode_for_graphics(graphics) == "external-spice" and (state or "").strip().lower() == "shut off"


def should_autoconnect_console(graphics: str | None, state: str | None) -> bool:
    normalized_state = (state or "").strip().lower()
    return console_mode_for_graphics(graphics) == "integrated-vnc" and (
        "running" in normalized_state or "paused" in normalized_state
    )


def scale_to_fit_size(widget_width: int, widget_height: int, fb_width: int, fb_height: int) -> tuple[int, int, float]:
    if widget_width <= 0 or widget_height <= 0 or fb_width <= 0 or fb_height <= 0:
        return 0, 0, 1.0
    scale = min(widget_width / fb_width, widget_height / fb_height)
    scaled_width = max(1, int(fb_width * scale))
    scaled_height = max(1, int(fb_height * scale))
    return scaled_width, scaled_height, scale


def centered_offset(widget_width: int, widget_height: int, content_width: int, content_height: int) -> tuple[int, int]:
    return max(0, (widget_width - content_width) // 2), max(0, (widget_height - content_height) // 2)


def widget_to_framebuffer(
    x: float,
    y: float,
    widget_width: int,
    widget_height: int,
    fb_width: int,
    fb_height: int,
    *,
    scale_to_fit: bool = True,
) -> tuple[int, int]:
    if fb_width <= 0 or fb_height <= 0:
        return 0, 0
    if scale_to_fit:
        scaled_width, scaled_height, scale = scale_to_fit_size(widget_width, widget_height, fb_width, fb_height)
        x_offset, y_offset = centered_offset(widget_width, widget_height, scaled_width, scaled_height)
    else:
        scale = 1.0
        x_offset, y_offset = 0, 0
    fb_x = int((x - x_offset) / scale)
    fb_y = int((y - y_offset) / scale)
    return max(0, min(fb_width - 1, fb_x)), max(0, min(fb_height - 1, fb_y))
