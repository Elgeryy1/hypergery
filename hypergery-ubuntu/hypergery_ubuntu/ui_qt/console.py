from __future__ import annotations

import struct
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QImage, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..backend import HyperGeryError
from .console_helpers import (
    HOST_KEY_NAME,
    SPICE_INTEGRATED_MESSAGE,
    SPICE_STATUS_MESSAGE,
    VNC_CONNECT_TIMEOUT,
    VNC_CONNECTING_MESSAGE,
    VNC_FAILED_MESSAGE,
    blocking_vnc_connect,
    can_capture_input,
    can_switch_display_to_vnc,
    centered_offset,
    console_message_for_graphics,
    console_mode_for_graphics,
    is_host_key,
    scale_to_fit_size,
    should_autoconnect_console,
    vnc_connect_error_reason,
    widget_to_framebuffer,
)


class VncConnectWorker(QObject):
    """Open the VNC TCP socket off the UI thread with a hard connect timeout.

    Lives in its own :class:`QThread`. ``run`` performs the blocking connect and
    emits exactly one terminal signal: ``connected`` with a live socket file
    descriptor, ``timed_out`` when the connect exceeds ``timeout`` seconds, or
    ``failed`` with a short Spanish reason for any other error.
    """

    connected = Signal(int)
    failed = Signal(str)
    timed_out = Signal()
    finished = Signal()

    def __init__(self, host: str, port: int, timeout: float = VNC_CONNECT_TIMEOUT) -> None:
        super().__init__()
        self._host = host
        self._port = int(port)
        self._timeout = timeout

    def run(self) -> None:
        try:
            descriptor = blocking_vnc_connect(self._host, self._port, self._timeout)
        except (TimeoutError, OSError) as exc:
            if isinstance(exc, TimeoutError):
                self.timed_out.emit()
            else:
                self.failed.emit(vnc_connect_error_reason(exc))
        except Exception as exc:  # pragma: no cover - defensive, keep UI alive.
            self.failed.emit(vnc_connect_error_reason(exc))
        else:
            self.connected.emit(int(descriptor))
        finally:
            self.finished.emit()


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


class VncScreen(QWidget):
    def __init__(self, console: "IntegratedConsoleWidget") -> None:
        super().__init__()
        self.console = console
        self.message = f"Pulsa «Conectar» para abrir la consola.\nTecla para soltar el ratón: {HOST_KEY_NAME}"
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 320)
        self.setStyleSheet("background: #111; color: #ddd;")

    def setText(self, text: str) -> None:
        self.message = text
        self.update()

    def setPixmap(self, _pixmap) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self.console.framebuffer:
            image = self.console.framebuffer
            if self.console.scale_to_fit:
                scaled_width, scaled_height, _scale = scale_to_fit_size(
                    self.width(), self.height(), self.console.fb_width, self.console.fb_height
                )
                x_offset, y_offset = centered_offset(self.width(), self.height(), scaled_width, scaled_height)
                painter.drawImage(x_offset, y_offset, image.scaled(
                    scaled_width,
                    scaled_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            else:
                painter.drawImage(0, 0, image)
        elif self.message:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)

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
        # El teclado llega al guest si la pantalla tiene el foco, sin obligar a
        # capturar el ratón con un clic. Así el «Press any key» del instalador de
        # Windows funciona en cuanto abres la consola (no hace falta saber que
        # primero hay que hacer clic dentro).
        if self.console.input_captured or self.hasFocus():
            self.console.send_key(event, True)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self.console.input_captured or self.hasFocus():
            self.console.send_key(event, False)


class IntegratedConsoleWidget(QWidget):
    def __init__(self, backend, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm = None
        self.vm_name = ""
        self.vm_state = ""
        self.graphics = ""
        self.display: dict[str, object] | None = None
        # Para una VM en otro equipo: el endpoint VNC ya tunelizado (127.0.0.1:
        # puerto local) en vez de preguntar a la libvirt local. Lo fija
        # VmConsoleWindow en modo remoto.
        self.display_override: dict[str, object] | None = None
        self.socket: QTcpSocket | None = None
        self.connect_thread: QThread | None = None
        self.connect_worker: VncConnectWorker | None = None
        # Cancelled connect threads draining in the background (HG-BUG-0014):
        # kept referenced until finished so Qt never destroys a running QThread.
        self._draining_threads: set[QThread] = set()
        # Instalación: pulsa «espacio» automáticamente unas veces al conectar para
        # cazar el «Press any key to boot from CD» (ventana de ~5 s) sin que el
        # usuario tenga que clavar el momento. Lo activa open_console(force).
        self.nudge_boot_on_connect = False
        self._boot_nudges_left = 0
        self.connecting = False
        self.buffer = bytearray()
        self.state = "idle"
        self.framebuffer: QImage | None = None
        self.fb_width = 0
        self.fb_height = 0
        self.pending_rects = 0
        self.input_captured = False
        self.pointer_mask = 0
        self.scale_to_fit = True
        self.status_callback: Callable[[str], None] | None = None
        self.controls_callback: Callable[[bool, bool], None] | None = None
        self.vm_updated_callback: Callable[[str], None] | None = None

        self.status = QLabel("Ninguna máquina seleccionada.")
        self.status.setObjectName("mutedLabel")
        self.hint = QLabel(
            f"Haz clic dentro de la consola para capturar el teclado y el ratón. Pulsa {HOST_KEY_NAME} para soltarlos. "
            "Cerrar esta consola no apaga la máquina. Usa «Apagar (suave)» o «Apagar a la fuerza»."
        )
        self.hint.setWordWrap(True)
        self.hint.setToolTip(f"Tecla para soltar: {HOST_KEY_NAME}")
        self.screen = VncScreen(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.screen)
        self.scroll_area.setWidgetResizable(True)
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.scroll_area)
        self.spice_card = self._build_spice_card()
        self.mode_stack.addWidget(self.spice_card)
        self.error_card = self._build_error_card()
        self.mode_stack.addWidget(self.error_card)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.status)
        layout.addWidget(self.hint)
        layout.addWidget(self.mode_stack, 1)
        self.setStyleSheet(
            """
            QWidget { background: #141820; color: #e8edf5; }
            QLabel#mutedLabel { color: #aab4c3; }
            QFrame#spiceCard {
                background: #202734;
                border: 1px solid #394354;
                border-radius: 8px;
            }
            QLabel#consoleCardTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #2f7cf6;
                color: #ffffff;
                border: 0;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: 700;
            }
            """
        )
        self.update_controls(False)

    def _build_spice_card(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(24, 24, 24, 24)
        outer_layout.addStretch()
        card = QFrame()
        card.setObjectName("spiceCard")
        card.setMaximumWidth(680)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(14)
        title = QLabel("La consola integrada requiere VNC")
        title.setObjectName("consoleCardTitle")
        text = QLabel(
            "Esta máquina usa SPICE. HyperGery puede abrirla con el visor externo, o puedes cambiar "
            "la pantalla de la máquina a VNC mientras está apagada."
        )
        text.setWordWrap(True)
        text.setObjectName("mutedLabel")
        self.spice_power_hint = QLabel("")
        self.spice_power_hint.setWordWrap(True)
        self.spice_power_hint.setObjectName("mutedLabel")
        self.spice_external_button = QPushButton("Abrir visor externo")
        self.spice_external_button.setObjectName("primaryButton")
        self.spice_switch_button = QPushButton("Cambiar a VNC")
        self.spice_external_button.clicked.connect(self.open_external)
        self.spice_switch_button.clicked.connect(self.switch_display_to_vnc)
        actions = QHBoxLayout()
        actions.addWidget(self.spice_external_button)
        actions.addWidget(self.spice_switch_button)
        actions.addStretch()
        card_layout.addWidget(title)
        card_layout.addWidget(text)
        card_layout.addWidget(self.spice_power_hint)
        card_layout.addLayout(actions)
        outer_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer_layout.addStretch()
        return outer

    def _build_error_card(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(24, 24, 24, 24)
        outer_layout.addStretch()
        card = QFrame()
        card.setObjectName("spiceCard")
        card.setMaximumWidth(680)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(14)
        title = QLabel(VNC_FAILED_MESSAGE)
        title.setObjectName("consoleCardTitle")
        self.error_detail = QLabel("")
        self.error_detail.setWordWrap(True)
        self.error_detail.setObjectName("mutedLabel")
        self.retry_button = QPushButton("Reintentar")
        self.retry_button.setObjectName("primaryButton")
        self.error_external_button = QPushButton("Abrir visor externo")
        self.retry_button.clicked.connect(self.reconnect_console)
        self.error_external_button.clicked.connect(self.open_external)
        actions = QHBoxLayout()
        actions.addWidget(self.retry_button)
        actions.addWidget(self.error_external_button)
        actions.addStretch()
        card_layout.addWidget(title)
        card_layout.addWidget(self.error_detail)
        card_layout.addLayout(actions)
        outer_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer_layout.addStretch()
        return outer

    def show_connection_error(self, reason: str) -> None:
        full_reason = f"{reason} Comprueba que la máquina está encendida y vuelve a intentarlo, o usa «Abrir visor externo»."
        self.error_detail.setText(full_reason)
        self.set_status(f"{VNC_FAILED_MESSAGE}: {reason}")
        self.mode_stack.setCurrentWidget(self.error_card)
        self.update_controls(console_mode_for_graphics(self.graphics) == "integrated-vnc")

    def set_vm(self, vm) -> None:
        name = getattr(vm, "name", "") if vm else ""
        state = str(getattr(vm, "state", "") if vm else "").lower()
        graphics = str(getattr(vm, "graphics", "") if vm else "").lower()
        if name != self.vm_name:
            self.disconnect_console()
        self.vm_name = name
        self.vm_state = state
        self.graphics = graphics
        self.vm = vm
        if not name:
            self.set_status("Ninguna máquina seleccionada.")
            self.mode_stack.setCurrentWidget(self.scroll_area)
            self.screen.setText("Selecciona una máquina encendida para abrir la consola integrada.")
            self.update_controls(False)
            return
        if console_mode_for_graphics(graphics) == "external-spice":
            self.mode_stack.setCurrentWidget(self.spice_card)
            self.set_status(SPICE_STATUS_MESSAGE)
            switch_enabled = can_switch_display_to_vnc(graphics, state)
            self.spice_switch_button.setEnabled(switch_enabled)
            self.spice_power_hint.setText("" if switch_enabled else "Apaga la VM antes de cambiar el modo de pantalla.")
            self.update_controls(False)
            return
        self.mode_stack.setCurrentWidget(self.scroll_area)
        if "running" not in state and "paused" not in state:
            self.set_status("La máquina está apagada.")
            self.screen.setText("La máquina está apagada.\nEnciéndela desde HyperGery y vuelve a conectar.")
            self.update_controls(False)
            return
        message = console_message_for_graphics(graphics)
        self.set_status(f"Lista para {name}. Tecla para soltar: {HOST_KEY_NAME}")
        self.screen.setText(message)
        self.update_controls(console_mode_for_graphics(graphics) == "integrated-vnc")

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        if self.status_callback:
            self.status_callback(text)

    def update_controls(self, vm_can_connect: bool) -> None:
        connected = self.is_connected()
        if self.controls_callback:
            self.controls_callback(vm_can_connect, connected)

    def is_connected(self) -> bool:
        return bool(self.socket and self.socket.state() == QAbstractSocket.SocketState.ConnectedState)

    def connect_console(self) -> None:
        if not self.vm_name:
            return
        if self.connecting:
            # A connect attempt is already running on the worker thread.
            return
        if "running" not in self.vm_state and "paused" not in self.vm_state:
            self.set_status("La máquina no está encendida. Enciéndela para abrir la consola.")
            self.screen.setText("La máquina no está encendida. Enciéndela para abrir la consola.")
            self.update_controls(False)
            return
        if console_mode_for_graphics(self.graphics) == "external-spice":
            self.set_status(SPICE_STATUS_MESSAGE)
            self.mode_stack.setCurrentWidget(self.spice_card)
            self.update_controls(False)
            return
        if self.display_override is not None:
            # VM remota: el VNC ya está tunelizado a 127.0.0.1:puerto local.
            display = self.display_override
        else:
            try:
                display = self.backend.get_console_display(self.vm_name)
            except HyperGeryError as exc:
                self.set_status(f"Consola integrada no disponible: {exc}")
                self.screen.setText("Consola integrada no disponible.\nUsa «Abrir visor externo».")
                return
        if display.get("type") != "vnc":
            self.set_status(SPICE_INTEGRATED_MESSAGE if display.get("type") == "spice" else "La consola integrada requiere VNC.")
            self.screen.setText(f"{SPICE_INTEGRATED_MESSAGE}\n\nUsa «Abrir visor externo».")
            return
        self.disconnect_console()
        self.display = display
        self.buffer.clear()
        self.state = "idle"
        # The TCP connect can block indefinitely if the host/VM is unreachable,
        # so it runs on a worker thread with a hard timeout. The UI shows a
        # non-blocking "Conectando…" state until the worker reports back.
        self._start_connect_worker(str(display["host"]), int(display["port"]))
        self.mode_stack.setCurrentWidget(self.scroll_area)
        self.screen.setText(f"{VNC_CONNECTING_MESSAGE}\nConectando con {display['uri']}…")
        self.set_status(f"{VNC_CONNECTING_MESSAGE} {display['uri']}")
        self.update_controls(True)

    def _start_connect_worker(self, host: str, port: int) -> None:
        self.connecting = True
        thread = QThread(self)
        worker = VncConnectWorker(host, port, VNC_CONNECT_TIMEOUT)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.connected.connect(self._on_worker_connected)
        worker.failed.connect(self._on_worker_failed)
        worker.timed_out.connect(self._on_worker_timed_out)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_connect_thread_finished)
        self.connect_thread = thread
        self.connect_worker = worker
        thread.start()

    def _on_connect_thread_finished(self) -> None:
        self.connecting = False
        self.connect_thread = None
        self.connect_worker = None

    def _stop_connect_worker(self) -> None:
        """Cancela el connect en vuelo SIN bloquear la UI (HG-BUG-0014).

        El connect bloqueante sigue corriendo en su hilo (acotado por el
        timeout de 10 s), pero se le retira el control de la UI: sus señales
        de resultado se desconectan, salvo ``connected``, que se recablea a
        ``_discard_descriptor`` para que un socket tardío se cierre en vez de
        filtrarse. El hilo queda referenciado en ``_draining_threads`` hasta
        que termina, evitando el crash «QThread destroyed while thread is
        still running» sin ningún ``wait()`` síncrono.
        """
        thread = self.connect_thread
        if thread is None:
            self.connecting = False
            return
        worker = self.connect_worker
        self.connecting = False
        self.connect_thread = None
        self.connect_worker = None
        if worker is not None:
            for signal in (worker.connected, worker.failed, worker.timed_out):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            worker.connected.connect(self._discard_descriptor)
            # El wrapper Python del worker debe sobrevivir hasta que el hilo
            # termine: si se recolecta, PySide destruye el QObject con señales
            # aún en vuelo (segfault). El hilo (referenciado abajo) lo ancla.
            thread._hg_draining_worker = worker
        # Este hilo cancelado ya no debe tocar el estado del próximo intento.
        try:
            thread.finished.disconnect(self._on_connect_thread_finished)
        except (RuntimeError, TypeError):
            pass
        # Sin padre Qt: si este widget muere antes que el hilo, Qt no destruye
        # un QThread en marcha. La referencia Python lo mantiene vivo.
        thread.setParent(None)
        self._draining_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._draining_threads.discard(t))
        thread.quit()

    def _on_worker_connected(self, descriptor: int) -> None:
        if not self.connecting:
            # We were cancelled while connecting; close the orphaned descriptor.
            self._discard_descriptor(descriptor)
            return
        self.connecting = False
        socket = QTcpSocket(self)
        if not socket.setSocketDescriptor(descriptor, QAbstractSocket.SocketState.ConnectedState):
            socket.deleteLater()
            self._discard_descriptor(descriptor)
            self.show_connection_error("No se pudo adoptar la conexión con la consola.")
            return
        self.socket = socket
        self.buffer.clear()
        self.state = "protocol"
        socket.readyRead.connect(self.on_ready_read)
        socket.errorOccurred.connect(self.on_socket_error)
        socket.disconnected.connect(lambda: self.update_controls(True))
        self.mode_stack.setCurrentWidget(self.scroll_area)
        # Da el foco del teclado a la pantalla para que el «Press any key» del
        # instalador funcione sin tener que hacer clic dentro primero.
        self.screen.setFocus(Qt.FocusReason.OtherFocusReason)
        self.set_status(
            f"Conectada. Si arranca un instalador, pulsa una tecla cuando veas «Press any key». "
            f"Tecla para soltar el ratón: {HOST_KEY_NAME}"
        )
        self.update_controls(True)
        # The server speaks first in RFB, but if any bytes are already buffered,
        # process them now so the handshake is not stalled waiting for readyRead.
        if socket.bytesAvailable():
            self.on_ready_read()

    def _on_worker_failed(self, reason: str) -> None:
        if not self.connecting:
            return
        self.connecting = False
        self.show_connection_error(reason)

    def _on_worker_timed_out(self) -> None:
        if not self.connecting:
            return
        self.connecting = False
        self.show_connection_error("Se agotó el tiempo de espera (10 s) al conectar con la consola.")

    @staticmethod
    def _discard_descriptor(descriptor: int) -> None:
        try:
            import socket as _socket

            _socket.socket(fileno=int(descriptor)).close()
        except OSError:
            pass

    def disconnect_console(self) -> None:
        was_connected = self.is_connected()
        was_connecting = self.connecting
        self.release_input()
        self._stop_connect_worker()
        if self.socket:
            self.socket.disconnectFromHost()
            self.socket.deleteLater()
            self.socket = None
        self.buffer.clear()
        self.state = "idle"
        if was_connecting and not was_connected:
            self.set_status("Conexión con la consola cancelada.")
        if was_connected:
            self.framebuffer = None
            self.screen.setText(f"Consola desconectada. Pulsa «Conectar» para reconectar.\nTecla para soltar: {HOST_KEY_NAME}")
            self.screen.update()
            self.set_status("Desconectada")
        self.update_controls(bool(self.vm_name) and console_mode_for_graphics(self.graphics) == "integrated-vnc")

    def reconnect_console(self) -> None:
        self.disconnect_console()
        self.connect_console()

    def open_external(self) -> None:
        if self.vm_name:
            self.backend.open_console(self.vm_name)

    def switch_display_to_vnc(self) -> None:
        if not can_switch_display_to_vnc(self.graphics, self.vm_state):
            self.set_status("Apaga la VM antes de cambiar el modo de pantalla.")
            return
        vm = self.vm
        ram_mib = int(getattr(vm, "ram_mib", 0) or 0)
        vcpus = int(getattr(vm, "vcpus", 0) or 0)
        if ram_mib < 256 or vcpus < 1:
            self.set_status("No se ha podido cambiar la pantalla a VNC: los ajustes de RAM/vCPU no están disponibles.")
            return
        network_mode = "isolated" if str(getattr(vm, "network", "")).endswith("-isolated") else "nat"
        try:
            self.backend.update_settings(
                self.vm_name,
                ram_mib=ram_mib,
                vcpus=vcpus,
                boot_iso=str(getattr(vm, "iso_path", "") or ""),
                network_mode=network_mode,
                display_mode="vnc",
                lab_id=str(getattr(vm, "lab_id", "") or "default-lab"),
            )
        except HyperGeryError as exc:
            self.set_status(f"No se ha podido cambiar la pantalla a VNC: {exc}")
            return
        self.graphics = "vnc"
        self.set_status("Pantalla cambiada a VNC. Enciende la VM y conecta la consola integrada.")
        self.mode_stack.setCurrentWidget(self.scroll_area)
        self.screen.setText("Pantalla cambiada a VNC.\nEnciende la VM y pulsa «Conectar».")
        self.update_controls(False)
        if self.vm_updated_callback:
            self.vm_updated_callback(self.vm_name)

    def capture_input(self) -> None:
        if not can_capture_input(self.graphics, self.is_connected()):
            if console_mode_for_graphics(self.graphics) == "external-spice":
                self.set_status(SPICE_STATUS_MESSAGE)
            return
        if not self.input_captured:
            self.input_captured = True
            self.set_status(f"Teclado y ratón capturados - pulsa {HOST_KEY_NAME} para soltarlos")
            self.update_controls(console_mode_for_graphics(self.graphics) == "integrated-vnc")

    def release_input(self) -> None:
        if self.input_captured:
            self.input_captured = False
            self.pointer_mask = 0
            self.set_status("Teclado y ratón liberados")
            self.update_controls(console_mode_for_graphics(self.graphics) == "integrated-vnc")

    def on_socket_error(self, _error) -> None:
        detail = self.socket.errorString() if self.socket else "error de socket desconocido"
        self.set_status(f"Falló la consola integrada: {detail}. Usa «Abrir visor externo».")
        self.update_controls(True)

    def on_ready_read(self) -> None:
        if not self.socket:
            return
        self.buffer.extend(bytes(self.socket.readAll()))
        try:
            self.process_buffer()
        except HyperGeryError as exc:
            self.set_status(f"Falló la consola integrada: {exc}. Usa «Abrir visor externo».")
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
                    raise HyperGeryError("El servidor VNC no ha enviado la cabecera del protocolo RFB.")
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
                    raise HyperGeryError("El servidor VNC requiere autenticación; la consola integrada solo admite VNC local sin autenticación.")
                self.socket.write(b"\x01")
                self.state = "security-result"
            elif self.state == "security-result":
                data = self._take(4)
                if data is None:
                    return
                if struct.unpack(">I", data)[0] != 0:
                    raise HyperGeryError("Falló la negociación de seguridad VNC.")
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
                self.update_screen_geometry()
                self.send_pixel_format()
                self.send_set_encodings()
                self.request_update(False)
                self.state = "message"
                self.set_status(f"Conectada - {self.fb_width}x{self.fb_height} - Tecla para soltar: {HOST_KEY_NAME}")
                if self.nudge_boot_on_connect:
                    self._start_boot_nudges()
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
                    raise HyperGeryError(f"Codificación VNC no soportada: {encoding}")
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
        self.update_screen_geometry()
        self.screen.update()

    def update_screen_geometry(self) -> None:
        self.scroll_area.setWidgetResizable(self.scale_to_fit)
        if self.framebuffer and not self.scale_to_fit:
            self.screen.setMinimumSize(self.fb_width, self.fb_height)
            self.screen.resize(self.fb_width, self.fb_height)
        else:
            self.screen.setMinimumSize(480, 320)

    def set_scale_to_fit(self, enabled: bool) -> None:
        self.scale_to_fit = enabled
        self.render_framebuffer()

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

    def _start_boot_nudges(self) -> None:
        """Pulsa «espacio» repetidamente durante el arranque para cazar el
        «Press any key to boot from CD». La consola se conecta nada más encender,
        pero ese prompt no aparece hasta que OVMF termina de inicializar (varios
        segundos) y solo dura ~5 s — por eso barremos una ventana AMPLIA cada
        segundo. El espacio es inofensivo en la pantalla de idioma de Windows."""
        self.nudge_boot_on_connect = False  # solo una vez por conexión
        self._boot_nudges_left = 25  # ~30 s de barrido (1.2 s + 24×1.2 s)
        QTimer.singleShot(1200, self._boot_nudge_tick)

    def _boot_nudge_tick(self) -> None:
        if self._boot_nudges_left <= 0 or not self.socket or self.state == "idle":
            return
        # Espacio (keysym 0x20): arranca el CD en el prompt; inofensivo después.
        self.socket.write(struct.pack(">BBxxI", 4, 1, 0x20))
        self.socket.write(struct.pack(">BBxxI", 4, 0, 0x20))
        self._boot_nudges_left -= 1
        if self._boot_nudges_left > 0:
            QTimer.singleShot(1200, self._boot_nudge_tick)

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
        x, y = widget_to_framebuffer(
            pos.x(),
            pos.y(),
            self.screen.width(),
            self.screen.height(),
            self.fb_width,
            self.fb_height,
            scale_to_fit=self.scale_to_fit,
        )
        self.socket.write(struct.pack(">BBHH", 5, self.pointer_mask, x, y))


class VmConsoleWindow(QMainWindow):
    def __init__(self, backend, vm, parent=None, on_vm_changed: Callable[[str], None] | None = None,
                 remote_display: dict | None = None, remote_process=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm = vm
        self.on_vm_changed = on_vm_changed
        # Modo remoto: proceso del túnel SSH al VNC del otro equipo (se cierra al
        # cerrar la ventana) y el endpoint local ya tunelizado.
        self._remote_process = remote_process
        remote_suffix = " (remota)" if remote_display is not None else ""
        self.setWindowTitle(f"Consola HyperGery - {getattr(vm, 'name', '')}{remote_suffix}")
        self.resize(1024, 768)
        self.setMinimumSize(1024, 768)
        self.console = IntegratedConsoleWidget(backend, self)
        if remote_display is not None:
            self.console.display_override = remote_display
        self.console.status_callback = self.set_console_status
        self.console.controls_callback = self.update_action_state
        self.console.vm_updated_callback = self.on_vm_changed
        self.setCentralWidget(self.console)
        self._build_toolbar()
        self._build_status_bar()
        self.set_vm(vm)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Consola")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        self.connect_action = QAction("Conectar", self)
        self.disconnect_action = QAction("Desconectar", self)
        self.reconnect_action = QAction("Reconectar", self)
        self.cad_action = QAction("Enviar Ctrl+Alt+Supr", self)
        self.release_action = QAction("Soltar teclado/ratón", self)
        self.fullscreen_action = QAction("Pantalla completa", self)
        self.fullscreen_action.setCheckable(True)
        self.scale_action = QAction("Ajustar a la ventana", self)
        self.scale_action.setCheckable(True)
        self.scale_action.setChecked(True)
        self.external_action = QAction("Abrir visor externo", self)
        self.switch_vnc_action = QAction("Cambiar a VNC", self)
        self.close_action = QAction("Cerrar", self)

        self.connect_action.triggered.connect(self.console.connect_console)
        self.disconnect_action.triggered.connect(self.console.disconnect_console)
        self.reconnect_action.triggered.connect(self.console.reconnect_console)
        self.cad_action.triggered.connect(self.console.send_ctrl_alt_del)
        self.release_action.triggered.connect(self.console.release_input)
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.scale_action.toggled.connect(self.console.set_scale_to_fit)
        self.external_action.triggered.connect(self.console.open_external)
        self.switch_vnc_action.triggered.connect(self.console.switch_display_to_vnc)
        self.close_action.triggered.connect(self.close)

        for action in (
            self.connect_action,
            self.disconnect_action,
            self.reconnect_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.cad_action)
        toolbar.addAction(self.release_action)
        toolbar.addSeparator()
        toolbar.addAction(self.fullscreen_action)
        toolbar.addAction(self.scale_action)
        toolbar.addSeparator()
        toolbar.addAction(self.external_action)
        toolbar.addAction(self.switch_vnc_action)
        toolbar.addAction(self.close_action)

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        self.state_label = QLabel("Teclado y ratón liberados")
        self.display_label = QLabel("Pantalla: —")
        self.host_key_label = QLabel(f"Tecla para soltar: {HOST_KEY_NAME}")
        self.close_note_label = QLabel("Cerrar esta consola no apaga la VM.")
        status.addWidget(self.state_label, 1)
        status.addPermanentWidget(self.display_label)
        status.addPermanentWidget(self.close_note_label)
        status.addPermanentWidget(self.host_key_label)
        self.setStatusBar(status)

    def set_vm(self, vm) -> None:
        self.vm = vm
        self.setWindowTitle(f"Consola HyperGery - {getattr(vm, 'name', '')}")
        self.console.set_vm(vm)
        self.external_action.setEnabled(bool(getattr(vm, "name", "")))
        self.switch_vnc_action.setEnabled(can_switch_display_to_vnc(getattr(vm, "graphics", ""), getattr(vm, "state", "")))

    def set_console_status(self, text: str) -> None:
        self.state_label.setText(text)

    def update_action_state(self, vm_can_connect: bool, connected: bool) -> None:
        connecting = self.console.connecting
        self.connect_action.setEnabled(vm_can_connect and not connected and not connecting)
        # Desconectar también cancela un intento de conexión en curso.
        self.disconnect_action.setEnabled(connected or connecting)
        self.reconnect_action.setEnabled(vm_can_connect and not connecting)
        self.cad_action.setEnabled(connected)
        self.release_action.setEnabled(self.console.input_captured)
        self.external_action.setEnabled(bool(self.console.vm_name))
        self.switch_vnc_action.setEnabled(can_switch_display_to_vnc(self.console.graphics, self.console.vm_state))
        display = (self.console.graphics or "—").upper() if self.console.graphics else "—"
        if connected and self.console.fb_width and self.console.fb_height:
            display += f" · {self.console.fb_width}x{self.console.fb_height}"
        self.display_label.setText(f"Pantalla: {display}")

    def toggle_fullscreen(self, enabled: bool) -> None:
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.fullscreen_action.setChecked(False)
            self.showNormal()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.console.disconnect_console()
        # Cierra el túnel SSH de la consola remota, si lo hay.
        proc = getattr(self, "_remote_process", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        event.accept()
