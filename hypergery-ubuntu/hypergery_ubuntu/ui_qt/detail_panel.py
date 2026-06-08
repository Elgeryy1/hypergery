from __future__ import annotations

"""Panel de detalle de la VM al estilo VirtualBox.

Muestra grupos (General, Sistema, Pantalla, Almacenamiento, Red, Instantáneas)
con filas etiqueta/valor, más una pantalla de bienvenida cuando no hay máquina
seleccionada. Emite señales para las acciones rápidas (consola, instantáneas,
ajustes, nueva máquina) que la ventana principal conecta a sus métodos.
"""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .formatting import format_mib
from .icons import os_icon
from .humanize import humanize_vm_status
from .styles import state_kind

if TYPE_CHECKING:
    from ..backend import VmSummary


class VmDetailPanel(QStackedWidget):
    consoleRequested = Signal()
    snapshotsRequested = Signal()
    settingsRequested = Signal()
    newVmRequested = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.addWidget(self._build_welcome())   # index 0
        self.addWidget(self._build_detail())     # index 1
        self.setCurrentIndex(0)

    # ---- Pantalla de bienvenida -----------------------------------------
    def _build_welcome(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)
        layout.addStretch()
        title = QLabel("Bienvenido a HyperGery")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "Selecciona una máquina del panel de la izquierda para ver sus "
            "detalles, o crea una nueva."
        )
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)
        new_button = QPushButton("Nueva máquina")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self.newVmRequested.emit)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(new_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return panel

    # ---- Página de detalle ----------------------------------------------
    def _build_detail(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header = QHBoxLayout()
        self._title_icon = QLabel()
        self._title = QLabel("—")
        self._title.setObjectName("pageTitle")
        self._status_chip = QLabel("")
        self._status_chip.setObjectName("statusChip")
        header.addWidget(self._title_icon)
        header.addWidget(self._title)
        header.addSpacing(8)
        header.addWidget(self._status_chip)
        header.addStretch()
        self._console_button = QPushButton("Consola")
        self._console_button.setObjectName("primaryButton")
        self._console_button.clicked.connect(self.consoleRequested.emit)
        self._snapshots_button = QPushButton("Instantáneas")
        self._snapshots_button.clicked.connect(self.snapshotsRequested.emit)
        self._settings_button = QPushButton("Configuración")
        self._settings_button.clicked.connect(self.settingsRequested.emit)
        header.addWidget(self._settings_button)
        header.addWidget(self._snapshots_button)
        header.addWidget(self._console_button)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(2, 2, 2, 2)
        self._content_layout.setSpacing(12)
        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)
        return page

    # ---- API pública -----------------------------------------------------
    def show_welcome(self) -> None:
        self.setCurrentIndex(0)

    def show_vm(self, vm: VmSummary, snapshots: list[str] | None = None) -> None:
        self.setCurrentIndex(1)
        self._title_icon.setPixmap(
            os_icon(vm.name, getattr(vm, "os_type", None), 22).pixmap(22, 22)
        )
        self._title.setText(vm.name)
        status = humanize_vm_status(vm.state)
        self._status_chip.setText(status)
        chip_obj = {"running": "statusChipOk", "paused": "statusChipWarn"}.get(
            state_kind(vm.state), "statusChip"
        )
        self._status_chip.setObjectName(chip_obj)
        self._status_chip.style().unpolish(self._status_chip)
        self._status_chip.style().polish(self._status_chip)
        self._clear_content()

        graphics = (vm.graphics or "").lower()
        self._add_group(
            "General",
            [
                ("Nombre", vm.name),
                ("Estado", status),
                ("Laboratorio", vm.lab_id or "Sin laboratorio"),
                ("URI de libvirt", "qemu:///system"),
            ],
        )
        self._add_group(
            "Sistema",
            [
                ("Memoria base", format_mib(vm.ram_mib)),
                ("Procesadores", str(vm.vcpus or "desconocido")),
            ],
        )
        self._add_group(
            "Pantalla",
            [
                ("Controlador gráfico", (vm.graphics or "desconocido").upper()),
                (
                    "Consola integrada",
                    "Disponible (VNC)" if graphics == "vnc" else "No disponible — requiere VNC",
                ),
                ("Visor externo", "virt-viewer / remote-viewer"),
                ("Tecla anfitrión", "Ctrl derecho (soltar ratón)"),
            ],
        )
        self._add_group(
            "Almacenamiento",
            [
                ("Ruta del disco", vm.disk_path or "desconocida"),
                ("Tamaño virtual", vm.disk_virtual or "desconocido"),
                ("Tamaño real", vm.disk_actual or "desconocido"),
                ("ISO de arranque", vm.iso_path or "ninguna"),
            ],
        )
        self._add_group(
            "Red",
            [
                ("Red", vm.network or "desconocida"),
                ("Laboratorio", vm.lab_id or "Sin laboratorio"),
            ],
        )
        if snapshots is not None:
            if snapshots:
                rows = [(f"#{i + 1}", snap) for i, snap in enumerate(snapshots)]
            else:
                rows = [("", "Sin instantáneas.")]
            self._add_group("Instantáneas", rows)

        self._content_layout.addStretch()

    def set_console_enabled(self, enabled: bool) -> None:
        self._console_button.setEnabled(enabled)

    def set_settings_enabled(self, enabled: bool) -> None:
        self._settings_button.setEnabled(enabled)

    # ---- Helpers de construcción ----------------------------------------
    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_group(self, title: str, rows: list[tuple[str, str]]) -> None:
        box = QFrame()
        box.setObjectName("panel")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)
        header = QLabel(title)
        header.setObjectName("detailGroup")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        for row, (key, value) in enumerate(rows):
            key_label = QLabel(key)
            key_label.setObjectName("detailKey")
            key_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            value_label = QLabel(str(value))
            value_label.setObjectName("detailValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key_label, row, 0)
            grid.addWidget(value_label, row, 1)
        layout.addLayout(grid)
        self._content_layout.addWidget(box)
