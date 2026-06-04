from __future__ import annotations

import struct

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..backend import HyperGeryError
from .console_helpers import HOST_KEY_NAME, is_host_key


def _keysym(event: QKeyEvent) -> int:
    text = event.text()
    if text and len(text) == 1 and 0x20 <= ord(text) <= 0x7E:
        return ord(text)
    mapping = {
        Qt.Key.Key_Backspace: 0xFF08,
        Qt.Key.Key_Tab: 0xFF09,
        Qt.Key.Key_Return: 0xFF0D,
        Qt.Key.Key_Enter: 0xFF0D,
        Qt.Key.Key_Escape: 0xFF1B,
        Qt.Key.Key_Insert: 0xFF63,
        Qt.Key.Key_Delete: 0xFFFF,
        Qt.Key.Key_Home: 0xFF50,
        Qt.Key.Key_End: 0xFF57,
        Qt.Key.Key_Left: 0xFF51,
        Qt.Key.Key_Up: 0xFF52,
        Qt.Key.Key_Right: 0xFF53,
        Qt.Key.Key_Down: 0xFF54,
        Qt.Key.Key_PageUp: 0xFF55,
        Qt.Key.Key_PageDown: 0xFF56,
        Qt.Key.Key_Shift: 0xFFE1,
        Qt.Key.Key_Control: 0xFFE3,
        Qt.Key.Key_Alt: 0xFFE9,
        Qt.Key.Key_F1: 0xFFBE,
        Qt.Key.Key_F2: 0xFFBF,
        Qt.Key.Key_F3: 0xFFC0,
        Qt.Key.Key_F4: 0xFFC1,
        Qt.Key.Key_F5: 0xFFC2,
        Qt.Key.Key_F6: 0xFFC3,
        Qt.Key.Key_F7: 0xFFC4,
        Qt.Key.Key_F8: 0xFFC5,
        Qt.Key.Key_F9: 0xFFC6,
        Qt.Key.Key_F10: 0xFFC7,
        Qt.Key.Key_F11: 0xFFC8,
        Qt.Key.Key_F12: 0xFFC9,
    }
    return mapping.get(event.key(), 0)


class VncScreen(QLabel):
    def __init__(self, console: "IntegratedConsoleWidget") -> None:
        super().__init__()
        self.console = console
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 320)
        self.setStyleSheet("background: #111; color: #ddd;")
        self.setText("Click Connect to open the VM console.\nHost Key: Right Ctrl")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.console.capture_input()
        self.console.send_pointer(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.console.send_pointer(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.console.input_captured:
            self.console.send_pointer(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if is_host_key(event.key(), event.nativeScanCode()):
            self.console.release_input()
            event.accept()
            return
        if self.console.input_captured:
            self.console.send_key(event, True)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self.console.input_captured:
            self.console.send_key(event, False)


class IntegratedConsoleWidget(QWidget):
    def __init__(self, backend, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm_name = ""
        self.display: dict[str, object] | None = None
        self.socket: QTcpSocket | None = None
        self.buffer = bytearray()
        self.state = "idle"
        self.framebuffer: QImage | None = None
        self.fb_width = 0
        self.fb_height = 0
        self.pending_rects = 0
        self.input_captured = False
        self.pointer_mask = 0

        self.status = QLabel("No VM selected.")
        self.status.setObjectName("mutedLabel")
        self.hint = QLabel(
            "Click inside the console to capture input. Press Right Ctrl to release input. "
            "Closing this console does not stop the VM. Use ACPI Shutdown or Force Off to stop the VM."
        )
        self.hint.setWordWrap(True)
        self.hint.setToolTip(f"Host Key: {HOST_KEY_NAME}")
        self.screen = VncScreen(self)

        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.reconnect_button = QPushButton("Reconnect")
        self.cad_button = QPushButton("Send Ctrl+Alt+Del")
        self.external_button = QPushButton("Open External Viewer")
        self.connect_button.clicked.connect(self.connect_console)
        self.disconnect_button.clicked.connect(self.disconnect_console)
        self.reconnect_button.clicked.connect(self.reconnect_console)
        self.cad_button.clicked.connect(self.send_ctrl_alt_del)
        self.external_button.clicked.connect(self.open_external)

        actions = QHBoxLayout()
        for button in (
            self.connect_button,
            self.disconnect_button,
            self.reconnect_button,
            self.cad_button,
            self.external_button,
        ):
            actions.addWidget(button)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.hint)
        layout.addLayout(actions)
        layout.addWidget(self.screen, 1)
        self.update_controls(False)

    def set_vm(self, vm) -> None:
        name = getattr(vm, "name", "") if vm else ""
        state = str(getattr(vm, "state", "") if vm else "").lower()
        if name != self.vm_name:
            self.disconnect_console()
        self.vm_name = name
        if not name:
            self.status.setText("No VM selected.")
            self.screen.setText("Select a running VM to open the integrated console.")
            self.update_controls(False)
            return
        if "running" not in state and "paused" not in state:
            self.status.setText("VM is not running. Start the VM to open console.")
            self.screen.setText("VM is not running. Start the VM to open console.")
            self.update_controls(False)
            return
        self.status.setText(f"Ready to connect to {name}. Host Key: {HOST_KEY_NAME}")
        self.screen.setText("Click Connect to open the VM console.")
        self.update_controls(True)

    def update_controls(self, vm_can_connect: bool) -> None:
        connected = bool(self.socket and self.socket.state() == QAbstractSocket.SocketState.ConnectedState)
        self.connect_button.setEnabled(vm_can_connect and not connected)
        self.disconnect_button.setEnabled(connected)
        self.reconnect_button.setEnabled(vm_can_connect)
        self.cad_button.setEnabled(connected)
        self.external_button.setEnabled(bool(self.vm_name))

    def connect_console(self) -> None:
        if not self.vm_name:
            return
        try:
            display = self.backend.get_console_display(self.vm_name)
        except HyperGeryError as exc:
            self.status.setText(f"Integrated console unavailable: {exc}")
            self.screen.setText("Integrated console unavailable.\nUse Open External Viewer.")
            return
        if display.get("type") != "vnc":
            self.status.setText("Integrated console requires VNC. Use Settings to switch display to VNC or open external viewer.")
            self.screen.setText("SPICE remains supported through the external viewer fallback.")
            return
        self.disconnect_console()
        self.display = display
        self.buffer.clear()
        self.state = "protocol"
        self.socket = QTcpSocket(self)
        self.socket.readyRead.connect(self.on_ready_read)
        self.socket.errorOccurred.connect(self.on_socket_error)
        self.socket.disconnected.connect(lambda: self.update_controls(True))
        self.socket.connectToHost(str(display["host"]), int(display["port"]))
        self.status.setText(f"Connecting to {display['uri']}...")
        self.update_controls(True)

    def disconnect_console(self) -> None:
        self.release_input()
        if self.socket:
            self.socket.disconnectFromHost()
            self.socket.deleteLater()
            self.socket = None
        self.buffer.clear()
        self.state = "idle"
        self.update_controls(bool(self.vm_name))

    def reconnect_console(self) -> None:
        self.disconnect_console()
        self.connect_console()

    def open_external(self) -> None:
        if self.vm_name:
            self.backend.open_console(self.vm_name)

    def capture_input(self) -> None:
        if not self.input_captured:
            self.input_captured = True
            self.status.setText(f"Input captured. Press {HOST_KEY_NAME} to release.")

    def release_input(self) -> None:
        if self.input_captured:
            self.input_captured = False
            self.pointer_mask = 0
            self.status.setText(f"Input released. Host Key: {HOST_KEY_NAME}")

    def on_socket_error(self, _error) -> None:
        detail = self.socket.errorString() if self.socket else "unknown socket error"
        self.status.setText(f"Integrated console failed: {detail}. Use Open External Viewer.")
        self.update_controls(True)

    def on_ready_read(self) -> None:
        if not self.socket:
            return
        self.buffer.extend(bytes(self.socket.readAll()))
        try:
            self.process_buffer()
        except HyperGeryError as exc:
            self.status.setText(f"Integrated console failed: {exc}. Use Open External Viewer.")
            self.disconnect_console()

    def _take(self, size: int) -> bytes | None:
        if len(self.buffer) < size:
            return None
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def process_buffer(self) -> None:
        while True:
            if self.state == "protocol":
                data = self._take(12)
                if data is None:
                    return
                if not data.startswith(b"RFB "):
                    raise HyperGeryError("VNC server did not send an RFB protocol banner.")
                self.socket.write(b"RFB 003.008\n")
                self.state = "security"
            elif self.state == "security":
                data = self._take(1)
                if data is None:
                    return
                count = data[0]
                types = self._take(count)
                if types is None:
                    self.buffer.insert(0, count)
                    return
                if 1 not in types:
                    raise HyperGeryError("VNC authentication is required; integrated console supports local no-auth VNC only.")
                self.socket.write(b"\x01")
                self.state = "security-result"
            elif self.state == "security-result":
                data = self._take(4)
                if data is None:
                    return
                if struct.unpack(">I", data)[0] != 0:
                    raise HyperGeryError("VNC security negotiation failed.")
                self.socket.write(b"\x01")
                self.state = "server-init"
            elif self.state == "server-init":
                header = self._take(24)
                if header is None:
                    return
                self.fb_width, self.fb_height = struct.unpack(">HH", header[:4])
                name_len = struct.unpack(">I", header[20:24])[0]
                name = self._take(name_len)
                if name is None:
                    self.buffer = bytearray(header) + self.buffer
                    return
                self.framebuffer = QImage(self.fb_width, self.fb_height, QImage.Format.Format_RGB32)
                self.framebuffer.fill(Qt.GlobalColor.black)
                self.send_pixel_format()
                self.send_set_encodings()
                self.request_update(False)
                self.state = "message"
                self.status.setText(f"Connected to {self.vm_name}. Input released. Host Key: {HOST_KEY_NAME}")
                self.update_controls(True)
            elif self.state == "message":
                msg_type = self._take(1)
                if msg_type is None:
                    return
                if msg_type[0] == 0:
                    header = self._take(3)
                    if header is None:
                        self.buffer = bytearray(msg_type) + self.buffer
                        return
                    self.pending_rects = struct.unpack(">H", header[1:3])[0]
                    self.state = "rect"
                else:
                    return
            elif self.state == "rect":
                if self.pending_rects <= 0:
                    self.render_framebuffer()
                    self.request_update(True)
                    self.state = "message"
                    continue
                rect_header = self._take(12)
                if rect_header is None:
                    return
                x, y, w, h, encoding = struct.unpack(">HHHHi", rect_header)
                if encoding != 0:
                    raise HyperGeryError(f"Unsupported VNC encoding: {encoding}")
                pixels = self._take(w * h * 4)
                if pixels is None:
                    self.buffer = bytearray(rect_header) + self.buffer
                    return
                self.blit_raw_rect(x, y, w, h, pixels)
                self.pending_rects -= 1

    def send_pixel_format(self) -> None:
        # 32bpp little-endian true color, matching QImage Format_RGB32 memory layout.
        body = struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.socket.write(b"\x00\x00\x00\x00" + body)

    def send_set_encodings(self) -> None:
        self.socket.write(struct.pack(">BBHi", 2, 0, 1, 0))

    def request_update(self, incremental: bool) -> None:
        self.socket.write(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.fb_width, self.fb_height))

    def blit_raw_rect(self, x: int, y: int, w: int, h: int, pixels: bytes) -> None:
        if self.framebuffer is None:
            return
        for row in range(h):
            target = self.framebuffer.scanLine(y + row)
            target[x * 4:(x + w) * 4] = pixels[row * w * 4:(row + 1) * w * 4]

    def render_framebuffer(self) -> None:
        if self.framebuffer:
            self.screen.setPixmap(QPixmap.fromImage(self.framebuffer).scaled(
                self.screen.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.render_framebuffer()

    def send_key(self, event: QKeyEvent, down: bool) -> None:
        key = _keysym(event)
        if self.socket and key:
            self.socket.write(struct.pack(">BBxxI", 4, 1 if down else 0, key))

    def send_ctrl_alt_del(self) -> None:
        if not self.socket:
            return
        for key in (0xFFE3, 0xFFE9, 0xFFFF):
            self.socket.write(struct.pack(">BBxxI", 4, 1, key))
        for key in (0xFFFF, 0xFFE9, 0xFFE3):
            self.socket.write(struct.pack(">BBxxI", 4, 0, key))

    def send_pointer(self, event: QMouseEvent) -> None:
        if not self.socket or not self.framebuffer:
            return
        if event.type() == QMouseEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.pointer_mask |= 1
            elif event.button() == Qt.MouseButton.MiddleButton:
                self.pointer_mask |= 2
            elif event.button() == Qt.MouseButton.RightButton:
                self.pointer_mask |= 4
        elif event.type() == QMouseEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.pointer_mask &= ~1
            elif event.button() == Qt.MouseButton.MiddleButton:
                self.pointer_mask &= ~2
            elif event.button() == Qt.MouseButton.RightButton:
                self.pointer_mask &= ~4
        pos = event.position()
        scale = min(self.screen.width() / self.fb_width, self.screen.height() / self.fb_height)
        x_offset = (self.screen.width() - self.fb_width * scale) / 2
        y_offset = (self.screen.height() - self.fb_height * scale) / 2
        x = max(0, min(self.fb_width - 1, int((pos.x() - x_offset) / scale)))
        y = max(0, min(self.fb_height - 1, int((pos.y() - y_offset) / scale)))
        self.socket.write(struct.pack(">BBHH", 5, self.pointer_mask, x, y))
