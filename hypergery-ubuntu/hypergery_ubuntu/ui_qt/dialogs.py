from __future__ import annotations

import html
import os
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QToolButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..backend import HyperGeryBackend, HyperGeryError, VmSummary
from ..config import CONFIG_FIELDS, HyperGeryConfig, config_path, default_config_values, effective_config
from ..registry import RegistryClient
from ..templates import normalize_template_id
from .humanize import humanize_vm_status
from .lab_helpers import build_lab_preview
from .styles import details_block

if TYPE_CHECKING:
    from .main_window import MainWindow


FILE_DIALOG_OPTIONS = QFileDialog.Option.DontUseNativeDialog

# Qt no carga traducciones: los botones estándar saldrían en inglés
# (Save/Cancel/OK). Aquí se ponen en español sin tocar su comportamiento.
_STANDARD_BUTTON_TEXTS_ES = (
    (QDialogButtonBox.StandardButton.Save, "Guardar"),
    (QDialogButtonBox.StandardButton.Cancel, "Cancelar"),
    (QDialogButtonBox.StandardButton.Ok, "Aceptar"),
)


def spanish_buttons(buttons: QDialogButtonBox) -> QDialogButtonBox:
    """Traduce los botones estándar de un QDialogButtonBox al español."""
    for standard, text in _STANDARD_BUTTON_TEXTS_ES:
        button = buttons.button(standard)
        if button is not None:
            button.setText(text)
    return buttons


def spanish_wizard_buttons(wizard: QWizard) -> None:
    """Traduce los botones de navegación de un QWizard al español."""
    wizard.setButtonText(QWizard.WizardButton.BackButton, "< Atrás")
    wizard.setButtonText(QWizard.WizardButton.NextButton, "Siguiente >")
    wizard.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")


def confirm(parent, title: str, text: str, *, yes_text: str = "Sí", no_text: str = "No", danger: bool = False) -> bool:
    """Cuadro de confirmación con botones en español (Sí/No por defecto)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText(yes_text)
    box.button(QMessageBox.StandardButton.No).setText(no_text)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


# Por encima de este tamaño una ISO se considera sospechosamente grande: la
# creación de la máquina (copia/registro) puede tardar mucho. Es solo un aviso,
# no un bloqueo.
ISO_LARGE_BYTES = 16 * 1024**3  # 16 GiB


def humanize_bytes(size: int | float) -> str:
    """Tamaño en bytes → cadena legible en español (1.5 GiB, 700 MiB…)."""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "tamaño desconocido"
    if value < 0:
        return "tamaño desconocido"
    units = ("bytes", "KiB", "MiB", "GiB", "TiB", "PiB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[0]}"
    return f"{value:.1f}".rstrip("0").rstrip(".") + f" {units[index]}"


def validate_iso_path(path: str | None, *, required: bool = False) -> tuple[bool, str]:
    """Valida la ruta de una ISO de instalación. Función pura y testeable.

    Devuelve `(ok, mensaje)`. `ok=False` debe bloquear el avance; `ok=True` con
    un mensaje no vacío es un aviso que permite continuar. La ISO es opcional:
    arrancar sin medio de instalación está permitido salvo que `required=True`.
    """
    text = (path or "").strip()
    if not text:
        if required:
            return (False, "Selecciona una imagen ISO")
        return (True, "")
    iso = Path(text).expanduser()
    if not iso.exists():
        return (False, f"El archivo ISO no existe: {text}")
    if not iso.is_file():
        return (False, "La ruta no es un archivo válido")
    try:
        size = iso.stat().st_size
    except OSError:
        return (False, "La ruta no es un archivo válido")
    if not os.access(iso, os.R_OK):
        return (False, "La ruta no es un archivo válido")
    if size == 0:
        return (False, "El archivo ISO está vacío (0 bytes)")
    if iso.suffix.lower() != ".iso":
        return (True, "Aviso: el archivo no tiene extensión .iso")
    if size > ISO_LARGE_BYTES:
        return (True, f"Aviso: ISO muy grande ({humanize_bytes(size)}), la creación puede tardar")
    return (True, "")


class AppSettingsDialog(QDialog):
    SECTIONS = ("General", "Hub", "Agente", "NAS", "Valores por defecto", "Consola", "Apariencia", "Avanzado")

    def __init__(self, backend: HyperGeryBackend, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("Ajustes de HyperGery")
        effective = effective_config()
        saved = HyperGeryConfig.load()
        self._effective = effective
        self._initial_values = {field: effective[field].value for field in CONFIG_FIELDS}

        self.hub_url = QLineEdit(saved.hub_url or effective["hub_url"].value)
        self.host_id = QLineEdit(saved.host_id or effective["host_id"].value)
        self.host_name = QLineEdit(saved.host_name or effective["host_name"].value)
        self.nas_staging_path = QLineEdit(saved.nas_staging_path or effective["nas_staging_path"].value)
        self.default_display = QComboBox()
        self.default_display.addItems(["vnc", "spice"])
        display = saved.default_display or effective["default_display"].value
        idx = self.default_display.findText(display)
        self.default_display.setCurrentIndex(idx if idx >= 0 else 0)
        self.default_iso_folder = QLineEdit(saved.default_iso_folder or effective["default_iso_folder"].value)
        self.default_vm_storage_path = QLineEdit(saved.default_vm_storage_path or effective["default_vm_storage_path"].value)
        self.status = QLabel("")
        self.status.setObjectName("mutedLabel")
        self.status.setWordWrap(True)

        title = QLabel("Ajustes")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Hub, agente, NAS y valores por defecto. Cada campo indica si su valor viene del entorno, de la configuración o del valor por defecto."
        )
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)

        self.section_nav = QListWidget()
        self.section_nav.setObjectName("sidebarNav")
        self.section_nav.addItems(list(self.SECTIONS))
        self.section_nav.setFixedWidth(168)
        self.pages = QStackedWidget()
        self.section_nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        self.pages.addWidget(self._section_page((
            self._field("ID del equipo", self.host_id, "host_id", "Identificador único y estable de este equipo en el Hub."),
            self._field("Nombre del equipo", self.host_name, "host_name", "Nombre legible que se muestra en «Otros equipos»."),
        )))
        test_hub = QPushButton("Probar Hub")
        test_hub.clicked.connect(self.test_hub)
        self.pages.addWidget(self._section_page((
            self._field("URL del Hub", self.hub_url, "hub_url", "La variable HYPERGERY_HUB_URL tiene prioridad sobre este valor."),
            self._button_row(test_hub),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("El agente solo ejecuta órdenes de una lista permitida y rechaza rutas fuera de la carpeta del NAS.", "calloutInfo"),
            self._callout("El agente reutiliza los ajustes de Hub, identidad y NAS de las otras secciones. Habrá más opciones en una versión futura.", "calloutInfo"),
        )))
        test_nas = QPushButton("Probar escritura en NAS")
        test_nas.clicked.connect(self.test_nas)
        self.pages.addWidget(self._section_page((
            self._field("Carpeta del NAS", self.nas_staging_path, "nas_staging_path", "Carpeta compartida para los paquetes de traslado, p. ej. /mnt/hypergery-nas/hypergery."),
            self._button_row(test_nas),
            self._callout("La base de datos del Hub nunca debe vivir en NAS/SMB — déjala en el volumen Docker.", "calloutDanger"),
        )))
        self.pages.addWidget(self._section_page((
            self._field("Pantalla por defecto", self.default_display, "default_display", "vnc activa la consola integrada; spice usa el visor externo."),
            self._field("Carpeta de ISOs", self.default_iso_folder, "default_iso_folder", "Carpeta inicial al elegir una ISO en el asistente de nueva máquina."),
            self._field("Carpeta de discos", self.default_vm_storage_path, "default_vm_storage_path", "Carpeta opcional por defecto para los discos de las máquinas nuevas."),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("Tecla para soltar el ratón de la consola: Ctrl derecho. Las máquinas SPICE siempre usan el visor externo.", "calloutInfo"),
            self._callout("Más preferencias de consola (escalado, comando del visor) llegarán en una versión futura.", "calloutInfo"),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("El tema actual es el oscuro. Habrá opciones de color y densidad en una versión futura.", "calloutInfo"),
        )))
        config_file = QLineEdit(str(config_path()))
        config_file.setReadOnly(True)
        test_libvirt = QPushButton("Probar libvirt")
        test_libvirt.clicked.connect(self.test_libvirt)
        self.pages.addWidget(self._section_page((
            self._field("Archivo de configuración", config_file, None, "Los ajustes se guardan en JSON. Las variables de entorno siempre tienen prioridad."),
            self._button_row(test_libvirt),
            self._callout("«Restaurar valores» solo rellena el formulario; no se guarda nada hasta que pulses Guardar.", "calloutWarn"),
        )))
        self.section_nav.setCurrentRow(0)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.section_nav)
        pages_frame = QFrame()
        pages_frame.setObjectName("panel")
        pages_frame_layout = QVBoxLayout(pages_frame)
        pages_frame_layout.setContentsMargins(18, 16, 18, 16)
        pages_frame_layout.addWidget(self.pages)
        body.addWidget(pages_frame, 1)

        reset = QPushButton("Restaurar valores")
        reset.clicked.connect(self.reset_defaults)
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(reset)
        bottom.addStretch()
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        layout.addLayout(bottom)
        self.resize(860, 500)

    def _source_chip(self, key: str) -> QLabel:
        source = self._effective[key].source
        if source.startswith("env:"):
            text, name = "ENV", "srcChipEnv"
        elif source == "config":
            text, name = "CONFIG", "srcChipConfig"
        else:
            text, name = "POR DEFECTO", "srcChipDefault"
        chip = QLabel(text)
        chip.setObjectName(name)
        chip.setToolTip(source)
        return chip

    def _field(self, label: str, widget: QWidget, key: str | None, hint: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        label_widget = QLabel(label)
        label_widget.setObjectName("statLabel")
        head.addWidget(label_widget)
        if key is not None:
            head.addWidget(self._source_chip(key))
        head.addStretch()
        layout.addLayout(head)
        layout.addWidget(widget)
        hint_label = QLabel(hint)
        hint_label.setObjectName("mutedLabel")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        return container

    def _callout(self, text: str, tone: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(tone)
        label.setWordWrap(True)
        return label

    def _button_row(self, *buttons: QPushButton) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for button in buttons:
            layout.addWidget(button)
        layout.addStretch()
        return container

    def _section_page(self, rows: tuple[QWidget, ...]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        for row in rows:
            layout.addWidget(row)
        layout.addStretch()
        return page

    def _set_status(self, text: str, tone: str) -> None:
        self.status.setText(text)
        self.status.setObjectName({"ok": "calloutOk", "fail": "calloutDanger"}.get(tone, "mutedLabel"))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def values(self) -> dict[str, str]:
        current = {
            "hub_url": self.hub_url.text().strip(),
            "host_id": self.host_id.text().strip(),
            "host_name": self.host_name.text().strip(),
            "nas_staging_path": self.nas_staging_path.text().strip(),
            "default_display": self.default_display.currentText(),
            "default_iso_folder": self.default_iso_folder.text().strip(),
            "default_vm_storage_path": self.default_vm_storage_path.text().strip(),
        }
        return {
            field: value
            for field, value in current.items()
            if self._effective[field].source == "config" or value != self._initial_values[field]
        }

    def validate_and_accept(self) -> None:
        hub_url = self.hub_url.text().strip()
        if hub_url and not (hub_url.startswith("http://") or hub_url.startswith("https://")):
            self._set_status("La URL del Hub debe empezar por http:// o https://", "fail")
            self.section_nav.setCurrentRow(self.SECTIONS.index("Hub"))
            return
        self.accept()

    def test_hub(self) -> None:
        try:
            result = RegistryClient(self.hub_url.text().strip(), timeout=3).health()
            self._set_status(f"Hub OK: {result}", "ok")
        except HyperGeryError as exc:
            self._set_status(f"Hub FALLO: {exc}", "fail")

    def test_nas(self) -> None:
        path = Path(self.nas_staging_path.text().strip()).expanduser()
        if not path.is_dir():
            self._set_status(f"NAS FALLO: la carpeta no existe: {path}", "fail")
            return
        try:
            with tempfile.NamedTemporaryFile(prefix=".hypergery-write-", dir=path, delete=True) as fh:
                fh.write(b"ok")
                fh.flush()
            self._set_status(f"NAS OK: se puede escribir en {path}", "ok")
        except OSError as exc:
            self._set_status(f"NAS FALLO: {exc}", "fail")

    def test_libvirt(self) -> None:
        try:
            items = self.backend.preflight()
        except Exception as exc:
            self._set_status(f"libvirt FALLO: {exc}", "fail")
            return
        failures = [item for item in items if item.status == "Error" and item.name in {"libvirt connection", "virsh"}]
        if not failures:
            self._set_status("libvirt OK", "ok")
        else:
            self._set_status("libvirt FALLO: " + "; ".join(item.detail for item in failures), "fail")

    def reset_defaults(self) -> None:
        defaults = default_config_values()
        self.hub_url.setText(defaults["hub_url"])
        self.host_id.setText(defaults["host_id"])
        self.host_name.setText(defaults["host_name"])
        self.nas_staging_path.setText(defaults["nas_staging_path"])
        self.default_display.setCurrentIndex(self.default_display.findText(defaults["default_display"]))
        self.default_iso_folder.setText(defaults["default_iso_folder"])
        self.default_vm_storage_path.setText(defaults["default_vm_storage_path"])
        self._set_status("Valores por defecto cargados en el formulario (sin guardar). Pulsa Guardar para aplicarlos.", "neutral")


class IdentityPage(QWizardPage):
    def __init__(self, default_iso_folder: str = "") -> None:
        super().__init__()
        self.default_iso_folder = default_iso_folder
        self.setTitle("Identidad")
        self.setSubTitle("Elige el nombre de la máquina y la ISO de arranque.")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ubuntu-lab-01")
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("/path/to/ubuntu.iso")
        browse = QPushButton("Examinar")
        browse.clicked.connect(self.pick_iso)
        self.iso_info_label = QLabel("")
        self.iso_info_label.setObjectName("mutedLabel")
        self.iso_info_label.setWordWrap(True)
        # B1/B2: el SO se elige como PERFIL (firmware/TPM correctos por sistema).
        from .. import vm_profiles as _vp

        self.os_type = QComboBox()
        for _key in ("linux", "linux-uefi", "windows11", "windows-legacy", "other"):
            self.os_type.addItem(_vp.PROFILES[_key].label, _key)

        iso_row = QHBoxLayout()
        iso_row.addWidget(self.iso_edit, 1)
        iso_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Nombre", self.name_edit)
        form.addRow("ISO de arranque", iso_row)
        form.addRow("", self.iso_info_label)
        form.addRow("Sistema operativo", self.os_type)
        form.addRow("", self.error_label)
        wrapper = QVBoxLayout(self)
        wrapper.addLayout(form)
        wrapper.addStretch()

        self.registerField("name*", self.name_edit)
        self.registerField("iso*", self.iso_edit)
        self.registerField("os_type", self.os_type, "currentText", self.os_type.currentTextChanged)
        self.os_type.currentIndexChanged.connect(lambda _i: self._refresh_iso_info())
        self.name_edit.textChanged.connect(lambda _text: self.completeChanged.emit())
        self.iso_edit.textChanged.connect(lambda _text: self.completeChanged.emit())
        self.iso_edit.textChanged.connect(lambda _text: self._refresh_iso_info())

    def pick_iso(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Elegir ISO de arranque",
            self.default_iso_folder,
            "Imágenes ISO (*.iso);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if path:
            self.iso_edit.setText(path)
            self._refresh_iso_info()

    def _refresh_iso_info(self) -> None:
        """Muestra el tamaño de la ISO elegida (o el motivo por el que no vale)."""
        text = self.iso_edit.text().strip()
        if not text:
            self.iso_info_label.setText("")
            return
        ok, message = validate_iso_path(text, required=True)
        iso = Path(text).expanduser()
        if ok:
            try:
                size_text = humanize_bytes(iso.stat().st_size)
            except OSError:
                size_text = "tamaño desconocido"
            info = f"Tamaño: {size_text}"
            if message:
                info += f" · {message}"
            self.iso_info_label.setText(info + self._profile_dependency_note())
        else:
            self.iso_info_label.setText(message)

    def _profile_dependency_note(self) -> str:
        """B1: avisa en la propia UI si el perfil elegido (p. ej. Windows 11)
        necesita ovmf/swtpm que no están instalados, con el comando para
        instalarlos. No bloquea aquí; el preflight de create_vm es el guard real."""
        from .. import vm_profiles as _vp

        key = str(self.os_type.currentData() or _vp.DEFAULT_PROFILE)
        pf = _vp.preflight_profile(_vp.PROFILES.get(key, _vp.PROFILES[_vp.DEFAULT_PROFILE]))
        if pf.ok:
            return ""
        cmd = " && ".join(pf.suggested_commands)
        return f"\n⚠️ {' '.join(pf.errors)}" + (f"\nInstala: {cmd}" if cmd else "")

    def isComplete(self) -> bool:
        return bool(self.name_edit.text().strip() and self.iso_edit.text().strip())

    def validatePage(self) -> bool:
        self.error_label.clear()
        if not self.name_edit.text().strip():
            self.error_label.setText("El nombre de la máquina es obligatorio.")
            return False
        ok, message = validate_iso_path(self.iso_edit.text(), required=True)
        if not ok:
            self.error_label.setText(message)
            return False
        if message:
            # Aviso (extensión no .iso, ISO muy grande): se permite continuar.
            return confirm(
                self,
                "Confirmar ISO",
                f"{message}.\n\n¿Quieres continuar de todas formas?",
                yes_text="Continuar",
                no_text="Cancelar",
            )
        return True


class ResourcesPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Recursos")
        self.setSubTitle("Elige CPU, memoria y tamaño de disco.")
        self.ram = QSpinBox()
        self.ram.setRange(512, 262144)
        self.ram.setSingleStep(512)
        self.ram.setValue(4096)
        self.ram.setSuffix(" MiB")
        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(2)
        self.disk = QSpinBox()
        self.disk.setRange(1, 4096)
        self.disk.setValue(40)
        self.disk.setSuffix(" GiB")

        form = QFormLayout(self)
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Disco", self.disk)
        self.registerField("ram", self.ram)
        self.registerField("vcpus", self.vcpus)
        self.registerField("disk", self.disk)


class IntegrationPage(QWizardPage):
    def __init__(self, default_lab_id: str = "default-lab", default_disk_dir: str = "", default_display: str = "") -> None:
        super().__init__()
        self.setTitle("Almacenamiento y red")
        self.setSubTitle("Elige dónde guardar el disco, la red del laboratorio y el tipo de consola.")
        self.disk_dir = QLineEdit()
        self.disk_dir.setText(default_disk_dir)
        self.disk_dir.setPlaceholderText("Carpeta de máquinas por defecto de HyperGery")
        browse = QPushButton("Examinar")
        browse.clicked.connect(self.pick_dir)
        self.network = QComboBox()
        self.network.addItems(["nat", "isolated"])
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
        if default_display:
            idx = self.display.findText(default_display)
            if idx >= 0:
                self.display.setCurrentIndex(idx)
        self.lab_id = QLineEdit(default_lab_id or "default-lab")
        # Live migration entre equipos con CPU distinta (AMD↔Intel).
        self.migratable_cpu = QCheckBox("Preparar para migración en vivo entre equipos (CPU compatible)")

        disk_row = QHBoxLayout()
        disk_row.addWidget(self.disk_dir, 1)
        disk_row.addWidget(browse)

        form = QFormLayout(self)
        form.addRow("Carpeta del disco", disk_row)
        form.addRow("Red", self.network)
        form.addRow("Pantalla", self.display)
        form.addRow("Laboratorio", self.lab_id)
        form.addRow("Migración", self.migratable_cpu)
        cpu_hint = QLabel(
            "Márcalo si vas a mover esta máquina ENCENDIDA entre tu sobremesa y el portátil. "
            "Usa una CPU compatible (un poco menos rápida) para que funcione entre AMD e Intel."
        )
        cpu_hint.setObjectName("mutedLabel")
        cpu_hint.setWordWrap(True)
        form.addRow("", cpu_hint)
        hint = QLabel("Si dejas la carpeta vacía se usa ~/.local/share/hypergery/vms/<nombre>/")
        hint.setObjectName("mutedLabel")
        form.addRow("", hint)
        display_hint = QLabel("La consola integrada requiere VNC. SPICE usa el visor externo.")
        display_hint.setObjectName("mutedLabel")
        form.addRow("", display_hint)
        self.registerField("disk_dir", self.disk_dir)
        self.registerField("network", self.network, "currentText", self.network.currentTextChanged)
        self.registerField("display", self.display, "currentText", self.display.currentTextChanged)
        self.registerField("lab_id", self.lab_id)

    def pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta del disco", "", FILE_DIALOG_OPTIONS)
        if path:
            self.disk_dir.setText(path)


class ReviewPage(QWizardPage):
    def __init__(self, wizard: "VMWizard") -> None:
        super().__init__()
        self.vm_wizard = wizard
        self.setTitle("Resumen")
        self.setSubTitle("Confirma lo que se va a crear.")
        self.summary = QLabel()
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary.setMinimumHeight(220)
        self.summary.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addStretch()

    def initializePage(self) -> None:
        values = self.vm_wizard.values()
        self.summary.setText(
            "<pre>"
            + html.escape(
                details_block(
                    ("Nombre", values["name"]),
                    ("ISO de arranque", values["iso_path"]),
                    ("Sistema operativo", values["os_type"]),
                    ("RAM", f"{values['ram_mib']} MiB"),
                    ("vCPUs", str(values["vcpus"])),
                    ("Disco", f"{values['disk_gb']} GiB qcow2"),
                    ("Carpeta del disco", values["disk_dir"] or "~/.local/share/hypergery/vms/<nombre>/"),
                    ("Red", values["network_mode"]),
                    ("Pantalla", values["display_mode"]),
                    ("Laboratorio", values["lab_id"]),
                )
            )
            + "</pre>"
        )


class CollapsibleSection(QWidget):
    """Sección plegable estilo VirtualBox: cabecera con flecha + cuerpo."""

    def __init__(self, title: str, expanded: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setObjectName("sectionHeader")
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle)
        self.body = QWidget()
        self.body_layout = QFormLayout(self.body)
        self.body_layout.setContentsMargins(28, 8, 12, 12)
        self.body.setVisible(expanded)
        layout.addWidget(self.body)

    def _on_toggled(self, checked: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)

    def add_row(self, label: str, widget) -> None:
        self.body_layout.addRow(label, widget)


class _SliderSpin(QWidget):
    """Slider + spinbox sincronizados, estilo VirtualBox (con min/max)."""

    def __init__(self, minimum: int, maximum: int, value: int, suffix: str = "", step: int = 1) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setSingleStep(step)
        self.slider.setValue(value)
        self.spin = QSpinBox()
        self.spin.setMinimum(minimum)
        self.spin.setMaximum(maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(f" {suffix}")
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        outer.addLayout(row)
        labels = QHBoxLayout()
        lo = QLabel(f"{minimum} {suffix}".strip())
        lo.setObjectName("mutedLabel")
        hi = QLabel(f"{maximum} {suffix}".strip())
        hi.setObjectName("mutedLabel")
        labels.addWidget(lo)
        labels.addStretch()
        labels.addWidget(hi)
        outer.addLayout(labels)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, value: int) -> None:  # noqa: N802 (API Qt)
        self.spin.setValue(value)


class VBoxStyleVMCreator(QDialog):
    """Diálogo de creación de VM al estilo de VirtualBox: una ventana con
    secciones plegables (Nombre y SO · Hardware · Disco) y sliders. Expone el
    mismo `values()` que VMWizard, así que `backend.create_vm(**values)` no
    cambia."""

    # (clave de perfil, etiqueta del combo)
    OS_ITEMS = (
        ("linux", "Linux / Ubuntu"),
        ("windows11", "Windows 11"),
        ("windows-legacy", "Windows 10 / 8"),
        ("other", "Otro"),
    )

    def __init__(self, parent=None, *, default_lab_id: str = "default-lab") -> None:
        super().__init__(parent)
        from .. import vm_profiles as _vp

        self._vp = _vp
        self.setWindowTitle("Nueva máquina virtual")
        app_defaults = effective_config()
        root = QVBoxLayout(self)

        # --- Sección 1: Nombre y sistema operativo ---------------------------
        self.sec_os = CollapsibleSection("Nombre y sistema operativo", expanded=True)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nombre de la máquina")
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("/ruta/a/la/imagen.iso")
        iso_browse = QPushButton("Examinar")
        iso_browse.clicked.connect(self._pick_iso)
        iso_row = QHBoxLayout()
        iso_row.addWidget(self.iso_edit, 1)
        iso_row.addWidget(iso_browse)
        iso_holder = QWidget()
        iso_holder.setLayout(iso_row)
        self.os_combo = QComboBox()
        for key, label in self.OS_ITEMS:
            self.os_combo.addItem(label, key)
        self.os_combo.currentIndexChanged.connect(self._on_os_changed)
        self.firmware_info = QLabel("")
        self.firmware_info.setObjectName("mutedLabel")
        self.firmware_info.setWordWrap(True)
        self.sec_os.add_row("Nombre", self.name_edit)
        self.sec_os.add_row("Imagen ISO", iso_holder)
        self.sec_os.add_row("Sistema operativo", self.os_combo)
        self.sec_os.add_row("", self.firmware_info)
        root.addWidget(self.sec_os)

        # --- Sección 2: Hardware --------------------------------------------
        self.sec_hw = CollapsibleSection("Hardware", expanded=True)
        self.ram = _SliderSpin(512, 30720, 2048, "MB", step=256)
        self.cpus = _SliderSpin(1, 16, 2, "CPU")
        self.use_efi = QCheckBox("Usar EFI (UEFI)")
        self.use_efi.toggled.connect(self._sync_firmware_info)
        self.secure_tpm_info = QLabel("")
        self.secure_tpm_info.setObjectName("mutedLabel")
        self.secure_tpm_info.setWordWrap(True)
        self.migratable_cpu = QCheckBox("Preparar para migración en vivo entre equipos (CPU compatible)")
        self.sec_hw.add_row("Memoria base", self.ram)
        self.sec_hw.add_row("Número de CPUs", self.cpus)
        self.sec_hw.add_row("Firmware", self.use_efi)
        self.sec_hw.add_row("", self.secure_tpm_info)
        self.sec_hw.add_row("Migración", self.migratable_cpu)
        root.addWidget(self.sec_hw)

        # --- Sección 3: Disco duro virtual -----------------------------------
        self.sec_disk = CollapsibleSection("Disco duro virtual", expanded=True)
        self.disk = _SliderSpin(1, 2048, 25, "GB")
        self.disk_dir = QLineEdit()
        self.disk_dir.setText(app_defaults["default_vm_storage_path"].value)
        self.disk_dir.setPlaceholderText("Carpeta por defecto de HyperGery")
        disk_browse = QPushButton("Examinar")
        disk_browse.clicked.connect(self._pick_disk_dir)
        disk_row = QHBoxLayout()
        disk_row.addWidget(self.disk_dir, 1)
        disk_row.addWidget(disk_browse)
        disk_holder = QWidget()
        disk_holder.setLayout(disk_row)
        self.sec_disk.add_row("Tamaño del disco", self.disk)
        self.sec_disk.add_row("Carpeta", disk_holder)
        root.addWidget(self.sec_disk)

        # --- Red / pantalla / lab (compacto) ---------------------------------
        self.sec_more = CollapsibleSection("Red y pantalla", expanded=False)
        self.network = QComboBox()
        self.network.addItems(["nat", "isolated"])
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
        default_display = app_defaults["default_display"].value
        idx = self.display.findText(default_display)
        if idx >= 0:
            self.display.setCurrentIndex(idx)
        self.lab_id = QLineEdit(default_lab_id or "default-lab")
        self.sec_more.add_row("Red", self.network)
        self.sec_more.add_row("Pantalla", self.display)
        self.sec_more.add_row("Laboratorio", self.lab_id)
        root.addWidget(self.sec_more)

        root.addStretch()
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)
        buttons = QDialogButtonBox()
        self.finish_button = buttons.addButton("Terminar", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.resize(720, 600)

        self.iso_edit.textChanged.connect(self._sync_firmware_info)
        self._on_os_changed()
        self.resize(720, 620)

    # ---- perfil/firmware ----
    def _current_os_key(self) -> str:
        return str(self.os_combo.currentData() or "linux")

    def resolved_profile(self) -> str:
        os_key = self._current_os_key()
        if os_key == "linux":
            return "linux-uefi" if self.use_efi.isChecked() else "linux"
        return os_key

    def _on_os_changed(self, *_a) -> None:
        os_key = self._current_os_key()
        profile = self._vp.PROFILES[os_key if os_key != "linux" else "linux"]
        # EFI: Windows siempre UEFI (bloqueado); Linux elegible; Otro = BIOS.
        if os_key in {"windows11", "windows-legacy"}:
            self.use_efi.setChecked(True)
            self.use_efi.setEnabled(False)
        elif os_key == "other":
            self.use_efi.setChecked(False)
            self.use_efi.setEnabled(False)
        else:
            self.use_efi.setEnabled(True)
        # Valores recomendados por perfil.
        self.ram.setValue(max(self.ram.value(), profile.min_ram_mib))
        self.disk.setValue(max(self.disk.value(), profile.min_disk_gb))
        self.firmware_info.setText(profile.notes)
        self._sync_firmware_info()

    def _sync_firmware_info(self, *_a) -> None:
        profile = self._vp.profile_for(self.resolved_profile())
        pf = self._vp.preflight_profile(profile)
        bits = []
        if profile.firmware in {"uefi", "uefi-secure"}:
            bits.append("UEFI")
        if profile.firmware == "uefi-secure":
            bits.append("Secure Boot")
        if profile.tpm:
            bits.append("TPM 2.0")
        line = "Firmware: " + (" + ".join(bits) if bits else "BIOS")
        if not pf.ok:
            line += "  ⚠️ " + " ".join(pf.errors)
            if pf.suggested_commands:
                line += "  → " + " && ".join(pf.suggested_commands)
        self.secure_tpm_info.setText(line)

    # ---- file pickers ----
    def _pick_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir ISO", "", "Imágenes (*.iso *.img);;Todos (*)")
        if path:
            self.iso_edit.setText(path)

    def _pick_disk_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta del disco")
        if path:
            self.disk_dir.setText(path)

    # ---- contrato ----
    def values(self) -> dict:
        profile_key = self.resolved_profile()
        return {
            "name": self.name_edit.text().strip(),
            "iso_path": self.iso_edit.text().strip(),
            "os_type": self._vp.PROFILES[profile_key].os_type,
            "profile": profile_key,
            "ram_mib": self.ram.value(),
            "vcpus": self.cpus.value(),
            "disk_gb": self.disk.value(),
            "disk_dir": self.disk_dir.text().strip() or None,
            "network_mode": self.network.currentText(),
            "display_mode": self.display.currentText(),
            "lab_id": self.lab_id.text().strip() or "default-lab",
            "migratable_cpu": self.migratable_cpu.isChecked(),
        }

    def _accept_if_valid(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("Pon un nombre a la máquina.")
            return
        if not self.iso_edit.text().strip():
            self.error_label.setText("Elige una imagen ISO de arranque.")
            return
        self.accept()


class VMWizard(QWizard):
    def __init__(self, parent=None, *, default_lab_id: str = "default-lab", defaults: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crear máquina virtual")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        app_defaults = effective_config()
        self.identity_page = IdentityPage(app_defaults["default_iso_folder"].value)
        self.resources_page = ResourcesPage()
        self.integration_page = IntegrationPage(
            default_lab_id,
            app_defaults["default_vm_storage_path"].value,
            app_defaults["default_display"].value,
        )
        self.review_page = ReviewPage(self)
        self.addPage(self.identity_page)
        self.addPage(self.resources_page)
        self.addPage(self.integration_page)
        self.addPage(self.review_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Crear")
        spanish_wizard_buttons(self)
        self.resize(760, 520)
        if defaults:
            self._apply_defaults(defaults)

    def _apply_defaults(self, defaults: dict) -> None:
        if "os_type" in defaults:
            idx = self.identity_page.os_type.findText(str(defaults["os_type"]).capitalize())
            if idx >= 0:
                self.identity_page.os_type.setCurrentIndex(idx)
        if "ram_mib" in defaults:
            self.resources_page.ram.setValue(int(defaults["ram_mib"]))
        if "vcpus" in defaults:
            self.resources_page.vcpus.setValue(int(defaults["vcpus"]))
        if "disk_gb" in defaults:
            self.resources_page.disk.setValue(int(defaults["disk_gb"]))
        if "network_mode" in defaults:
            idx = self.integration_page.network.findText(str(defaults["network_mode"]))
            if idx >= 0:
                self.integration_page.network.setCurrentIndex(idx)
        if "display" in defaults:
            idx = self.integration_page.display.findText(str(defaults["display"]))
            if idx >= 0:
                self.integration_page.display.setCurrentIndex(idx)

    def values(self) -> dict:
        from .. import vm_profiles as _vp

        profile_key = str(self.identity_page.os_type.currentData() or _vp.DEFAULT_PROFILE)
        return {
            "name": self.identity_page.name_edit.text().strip(),
            "iso_path": self.identity_page.iso_edit.text().strip(),
            "os_type": _vp.PROFILES.get(profile_key, _vp.PROFILES[_vp.DEFAULT_PROFILE]).os_type,
            "profile": profile_key,
            "ram_mib": self.resources_page.ram.value(),
            "vcpus": self.resources_page.vcpus.value(),
            "disk_gb": self.resources_page.disk.value(),
            "disk_dir": self.integration_page.disk_dir.text().strip() or None,
            "network_mode": self.integration_page.network.currentText(),
            "display_mode": self.integration_page.display.currentText(),
            "lab_id": self.integration_page.lab_id.text().strip() or "default-lab",
            "migratable_cpu": self.integration_page.migratable_cpu.isChecked(),
        }


class NewLabDialog(QDialog):
    def __init__(self, existing_lab_ids: set[str], existing_subnets: set[str], parent=None) -> None:
        super().__init__(parent)
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setWindowTitle("Nuevo laboratorio")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Laboratorio de pruebas")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Descripción opcional")
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_label.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.create_button = buttons.addButton("Crear", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Nombre", self.name_edit)
        form.addRow("Descripción", self.description_edit)
        form.addRow("Modo de red", self.network_mode)
        form.addRow("Vista previa", self.preview_label)
        form.addRow("", self.error_label)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.name_edit.textChanged.connect(self.update_preview)
        self.network_mode.currentTextChanged.connect(self.update_preview)
        self.update_preview()
        self.resize(620, 300)

    def current_preview(self) -> dict:
        return build_lab_preview(
            self.name_edit.text(),
            self.network_mode.currentText(),
            self.existing_lab_ids,
            self.existing_subnets,
        )

    def update_preview(self) -> None:
        preview = self.current_preview()
        self.create_button.setEnabled(bool(preview["valid"]))
        self.error_label.setText(preview["error"])
        if preview["valid"]:
            self.preview_label.setText(
                details_block(
                    ("ID", preview["lab_id"]),
                    ("Red", preview["network_id"]),
                    ("Puente", preview["bridge_name"]),
                    ("Subred", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Escribe un nombre válido para ver la vista previa de la red.")

    def values(self) -> dict:
        preview = self.current_preview()
        return {
            "name": self.name_edit.text().strip(),
            "description": self.description_edit.text().strip(),
            "network_mode": self.network_mode.currentText(),
            "lab_id": preview["lab_id"],
        }


class RenameLabDialog(QDialog):
    def __init__(self, lab: dict, parent=None) -> None:
        super().__init__(parent)
        self.lab = lab
        self.setWindowTitle(f"Renombrar laboratorio: {lab.get('lab_id', '?')}")
        self.name_edit = QLineEdit(str(lab.get("name") or lab.get("lab_id") or ""))
        self.description_edit = QLineEdit(str(lab.get("description") or ""))
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        notice = QLabel("Solo cambia el nombre visible y la descripción. El ID del laboratorio y su red no se tocan.")
        notice.setObjectName("mutedLabel")
        notice.setWordWrap(True)
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("ID", QLabel(str(lab.get("lab_id", ""))))
        form.addRow("Nombre", self.name_edit)
        form.addRow("Descripción", self.description_edit)
        form.addRow("", self.error_label)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(620, 260)

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("El nombre del laboratorio es obligatorio.")
            return
        super().accept()

    def values(self) -> dict:
        return {"name": self.name_edit.text().strip(), "description": self.description_edit.text().strip()}


class DeleteLabDialog(QDialog):
    def __init__(self, lab: dict, parent=None) -> None:
        super().__init__(parent)
        self.lab = lab
        lab_id = str(lab.get("lab_id", ""))
        self.setWindowTitle(f"Eliminar laboratorio: {lab_id}")
        title = QLabel(f"¿Eliminar el laboratorio {lab_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("Se borra el manifiesto del laboratorio. Las máquinas no se borran por defecto.")
        warning.setWordWrap(True)
        self.delete_vms = QCheckBox("Borrar también las máquinas (aún no disponible)")
        self.delete_vms.setEnabled(False)
        self.confirm_lab = QLineEdit()
        self.confirm_lab.setPlaceholderText(lab_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.delete_button = buttons.addButton("Eliminar laboratorio", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_lab.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Escribe el ID", self.confirm_lab)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addWidget(self.delete_vms)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(560, 280)

    def update_state(self) -> None:
        self.delete_button.setEnabled(self.confirm_lab.text().strip() == str(self.lab.get("lab_id", "")))

    def accept(self) -> None:
        if self.confirm_lab.text().strip() != str(self.lab.get("lab_id", "")):
            self.error_label.setText("Escribe el ID exacto para confirmar el borrado.")
            return
        super().accept()

    def delete_vms_too(self) -> bool:
        return False


class DuplicateLabDialog(QDialog):
    def __init__(self, source_lab: dict, existing_lab_ids: set[str], existing_subnets: set[str], parent=None) -> None:
        super().__init__(parent)
        self.source_lab = source_lab
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setWindowTitle(f"Duplicar laboratorio: {source_lab.get('lab_id', '?')}")
        self.name_edit = QLineEdit(f"{source_lab.get('name') or source_lab.get('lab_id')} Copy")
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_label.setWordWrap(True)
        has_vms = bool(source_lab.get("vms"))
        self.clone_vms = QCheckBox("Clonar también las máquinas (todas deben estar apagadas; clona los discos)")
        self.clone_vms.setEnabled(has_vms)
        if not has_vms:
            self.clone_vms.setToolTip("Este laboratorio no tiene máquinas que clonar.")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.duplicate_button = buttons.addButton("Duplicar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.duplicate_button.setObjectName("primaryButton")
        self.duplicate_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Origen", QLabel(str(source_lab.get("lab_id", ""))))
        form.addRow("Nombre del nuevo laboratorio", self.name_edit)
        form.addRow("Vista previa", self.preview_label)
        form.addRow("", self.error_label)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.clone_vms)
        layout.addWidget(buttons)
        self.name_edit.textChanged.connect(self.update_preview)
        self.update_preview()
        self.resize(620, 300)

    def current_preview(self) -> dict:
        return build_lab_preview(
            self.name_edit.text(),
            str(self.source_lab.get("network_mode", "nat")),
            self.existing_lab_ids,
            self.existing_subnets,
        )

    def update_preview(self) -> None:
        preview = self.current_preview()
        self.duplicate_button.setEnabled(bool(preview["valid"]))
        self.error_label.setText(preview["error"])
        if preview["valid"]:
            self.preview_label.setText(
                details_block(
                    ("ID", preview["lab_id"]),
                    ("Red", preview["network_id"]),
                    ("Puente", preview["bridge_name"]),
                    ("Subred", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Elige un nombre válido para el nuevo laboratorio.")

    def values(self) -> dict:
        preview = self.current_preview()
        return {
            "new_name": self.name_edit.text().strip(),
            "lab_id": preview["lab_id"],
            "clone_vms": self.clone_vms.isChecked() and self.clone_vms.isEnabled(),
        }


class SettingsDialog(QDialog):
    def __init__(self, vm: VmSummary, parent=None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.setWindowTitle(f"Configuración: {vm.name}")

        # Campos (idénticos a antes; values() no cambia).
        self.name_value = QLineEdit(vm.name)
        self.name_value.setReadOnly(True)
        self.ram = QSpinBox()
        self.ram.setRange(256, 262144)
        self.ram.setSingleStep(512)
        self.ram.setValue(vm.ram_mib or 4096)
        self.ram.setSuffix(" MiB")
        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(vm.vcpus or 2)
        self.iso = QLineEdit(vm.iso_path)
        browse = QPushButton("Examinar")
        browse.clicked.connect(self.pick_iso)
        iso_row = QHBoxLayout()
        iso_row.addWidget(self.iso, 1)
        iso_row.addWidget(browse)
        self.network = QComboBox()
        self.network.addItems(["nat", "isolated"])
        self.network.setCurrentText("isolated" if vm.network.endswith("-isolated") else "nat")
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
        self.display.setCurrentText(vm.graphics if vm.graphics in {"spice", "vnc"} else "spice")
        self.lab_id = QLineEdit(vm.lab_id or "default-lab")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)

        display_hint = QLabel("La consola integrada requiere VNC. SPICE usa el visor externo.")
        display_hint.setObjectName("mutedLabel")
        display_hint.setWordWrap(True)

        # Navegación lateral con páginas, al estilo del diálogo de Ajustes de
        # VirtualBox (General / Sistema / Pantalla / Almacenamiento / Red).
        self.section_nav = QListWidget()
        self.section_nav.setObjectName("sidebarNav")
        self.section_nav.setFixedWidth(184)
        self.pages = QStackedWidget()
        self.section_nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        sections = (
            ("General", "SP_ComputerIcon", (
                ("Nombre", self.name_value),
                ("Laboratorio", self.lab_id),
            )),
            ("Sistema", "SP_DriveHDIcon", (
                ("Memoria base", self.ram),
                ("Procesadores", self.vcpus),
            )),
            ("Pantalla", "SP_DesktopIcon", (
                ("Controlador gráfico", self.display),
                ("", display_hint),
            )),
            ("Almacenamiento", "SP_DriveFDIcon", (
                ("ISO de arranque", iso_row),
            )),
            ("Red", "SP_DriveNetIcon", (
                ("Adaptador 1", self.network),
            )),
        )
        for title_text, icon_name, rows in sections:
            self.section_nav.addItem(QListWidgetItem(self._std_icon(icon_name), title_text))
            self.pages.addWidget(self._form_page(rows))
        self.section_nav.setCurrentRow(0)

        header = QLabel("Configuración")
        header.setObjectName("pageTitle")
        subtitle = QLabel(f"{vm.name} · {humanize_vm_status(vm.state)}")
        subtitle.setObjectName("mutedLabel")

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.section_nav)
        pages_frame = QFrame()
        pages_frame.setObjectName("panel")
        pages_frame_layout = QVBoxLayout(pages_frame)
        pages_frame_layout.setContentsMargins(18, 16, 18, 16)
        pages_frame_layout.addWidget(self.pages)
        body.addWidget(pages_frame, 1)

        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        hint = QLabel("Los ajustes se aplican a través de libvirt y la máquina debe estar apagada.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addLayout(body, 1)
        layout.addWidget(self.error_label)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.resize(760, 470)

    def _std_icon(self, name: str) -> QIcon:
        pixmap = getattr(QStyle.StandardPixmap, name, None)
        if pixmap is None:
            return QIcon()
        app = QApplication.instance()
        return app.style().standardIcon(pixmap) if app else QIcon()

    def _form_page(self, rows: tuple) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 6, 4, 6)
        form.setSpacing(12)
        for label, field in rows:
            form.addRow(label, field)
        return page

    def pick_iso(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Elegir ISO de arranque",
            "",
            "Imágenes ISO (*.iso);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if path:
            self.iso.setText(path)

    def accept(self) -> None:
        iso = self.iso.text().strip()
        if iso and not Path(iso).expanduser().is_file():
            self.error_label.setText(f"La ISO de arranque no existe: {iso}")
            return
        super().accept()

    def values(self) -> dict:
        return {
            "name": self.vm.name,
            "ram_mib": self.ram.value(),
            "vcpus": self.vcpus.value(),
            "boot_iso": self.iso.text().strip(),
            "network_mode": self.network.currentText(),
            "display_mode": self.display.currentText(),
            "lab_id": self.lab_id.text().strip() or "default-lab",
        }


class CloneDialog(QDialog):
    def __init__(self, source_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Clonar: {source_name}")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(f"{source_name}-clone")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        form = QFormLayout()
        form.addRow("Origen", QLabel(source_name))
        form.addRow("Nombre del clon", self.name_edit)
        form.addRow("", self.error_label)
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Clonar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("El nombre del clon es obligatorio.")
            return
        super().accept()

    def clone_name(self) -> str:
        return self.name_edit.text().strip()


class DeleteConfirmationDialog(QDialog):
    def __init__(self, vm: VmSummary, parent=None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.setWindowTitle(f"Eliminar máquina: {vm.name}")
        title = QLabel(f"¿Eliminar {vm.name}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("La máquina se elimina de libvirt. Solo se pueden borrar discos gestionados por HyperGery.")
        warning.setWordWrap(True)
        self.delete_disk = QCheckBox("Borrar también el disco gestionado por HyperGery si es seguro")
        self.confirm_name = QLineEdit()
        self.confirm_name.setPlaceholderText(vm.name)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.delete_button = buttons.addButton("Eliminar máquina", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_name.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Escribe el nombre", self.confirm_name)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addWidget(self.delete_disk)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(520, 260)

    def update_state(self) -> None:
        self.delete_button.setEnabled(self.confirm_name.text().strip() == self.vm.name)

    def accept(self) -> None:
        if self.confirm_name.text().strip() != self.vm.name:
            self.error_label.setText("Escribe el nombre exacto para confirmar el borrado.")
            return
        super().accept()

    def delete_disks(self) -> bool:
        return self.delete_disk.isChecked()


def hub_target_candidates(hosts: list[dict], source_host_id: str, source_hostname: str = "") -> list[dict]:
    """Candidatos de destino para migración mediada por el Hub (B5).

    Lógica pura y testeable: usa SOLO el registro del Hub (list_hosts), NUNCA
    descubrimiento de red ni conectividad directa PC↔portátil. Excluye el host
    de origen (por host_id o, si no, por hostname), elimina duplicados, y marca
    cada candidato como listo/no-listo con la razón concreta. Un destino es
    apto para el modo Hub si está ONLINE en el Hub y tiene KVM disponible para
    importar: no hace falta que origen y destino «se vean» entre sí."""
    seen: set[str] = set()
    out: list[dict] = []
    for host in hosts:
        host_id = str(host.get("host_id") or "")
        if not host_id or host_id in seen:
            continue
        seen.add(host_id)
        hostname = str(host.get("hostname") or "")
        is_source = host_id == source_host_id or (
            bool(source_hostname) and hostname == source_hostname and source_host_id in ("", hostname)
        )
        if is_source:
            continue
        online = str(host.get("status") or "offline") == "online"
        kvm = bool(host.get("kvm_ok"))
        libvirt = bool(host.get("libvirt_ok"))
        if not online:
            ready, reason = False, "sin conexión con el Hub"
        elif not kvm:
            ready, reason = False, "online pero sin KVM disponible para importar"
        elif not libvirt:
            ready, reason = False, "online pero libvirt no responde en ese equipo"
        else:
            ready, reason = True, ""
        address = str(host.get("address") or host.get("agent_url") or "")
        out.append(
            {
                "host": host,
                "host_id": host_id,
                "hostname": hostname,
                "address": address,
                "online": online,
                "kvm_ok": kvm,
                "libvirt_ok": libvirt,
                "ready": ready,
                "reason": reason,
                "last_seen": str(host.get("last_seen") or ""),
            }
        )
    return out


def live_uri_for_host(host: dict) -> str:
    """Deriva una URI qemu+ssh del registro de un host del Hub (B3).

    Usa agent_url/address y, si está, un usuario sugerido. Devuelve "" si no hay
    suficiente para proponer una URI (la UI deja editar a mano)."""
    address = str(host.get("address") or host.get("agent_url") or "").strip()
    # Quita esquema/puerto si vinieran de un agent_url http://host:port.
    for prefix in ("http://", "https://"):
        if address.startswith(prefix):
            address = address[len(prefix):]
    address = address.split("/")[0].split(":")[0]
    if not address:
        return ""
    user = str(host.get("ssh_user") or host.get("user") or "").strip()
    prefix = f"{user}@" if user else ""
    return f"qemu+ssh://{prefix}{address}/system"


class LiveMigrationDialog(QDialog):
    """NAS Clone Migration wizard: stepper + stacked pages over the existing v0.6 flow."""

    STEPS = ("Elegir máquina", "Equipo destino", "Opciones", "Comprobación", "Progreso", "Resultado")
    MIGRATION_STATES = ("created", "preflight", "packaging", "uploaded", "waiting_target", "importing", "defining_vm", "done")

    def __init__(self, backend: HyperGeryBackend, vm: VmSummary, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm = vm
        self.preflight_result: dict | None = None
        self.hosts: list[dict] = []
        self.last_result: dict | None = None
        self.last_status: dict | None = None
        self._jobs: list = []
        self._status_job_running = False
        self.status_poll_timer = QTimer(self)
        self.status_poll_timer.setInterval(4000)
        self.status_poll_timer.timeout.connect(self.refresh_migration_status)
        # Closing the dialog stops polling; it never touches the migration itself.
        self.finished.connect(self.status_poll_timer.stop)
        self.setWindowTitle(f"Mover a otro equipo: {vm.name}")

        app_config = effective_config()
        self.registry_url = QLineEdit(app_config["hub_url"].value)
        self.source_host_id = QLineEdit(app_config["host_id"].value)
        self.target_host = QComboBox()
        self.target_name = QLineEdit(f"{vm.name}-migrated")
        self.transfer_mode = QComboBox()
        self.transfer_mode.addItem("Por el Hub — se sube al Hub, no hace falta NAS compartido (oficial)", "hub")
        self.transfer_mode.addItem("Por carpeta NAS compartida — visible en ambos equipos", "nas")
        self.transfer_mode.addItem("Migración en vivo — VM ENCENDIDA, modo avanzado (libvirt directo)", "live")
        # B3: URI del destino para la migración en vivo (qemu+ssh/qemu+tls).
        self.live_uri = QLineEdit("")
        self.live_uri.setPlaceholderText("qemu+ssh://usuario@equipo/system")
        self.nas_path = QLineEdit(app_config["nas_staging_path"].value)
        self.include_iso = QCheckBox("Incluir la ISO conectada")
        self.include_iso.setChecked(True)
        self.include_snapshots = QCheckBox("Incluir archivos de instantáneas cuando se detecten")
        self.include_snapshots.setChecked(True)
        self.allow_paused = QCheckBox("Permitir empaquetar máquinas en pausa")
        self.start_after_import = QCheckBox("Encender al terminar")
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(170)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)

        title = QLabel(f"Mover a otro equipo · {vm.name}")
        title.setObjectName("pageTitle")
        strategy_note = QLabel(
            "Si la máquina está APAGADA se copia al otro equipo por el Hub/NAS (el original no se toca, "
            "se importa una copia con UUID y MAC nuevos). Si está ENCENDIDA se usa migración en vivo: "
            "la RAM se traspasa en caliente y solo se congela unos milisegundos al final."
        )
        strategy_note.setObjectName("calloutInfo")
        strategy_note.setWordWrap(True)

        self._step_labels: list[QLabel] = []
        stepper = QVBoxLayout()
        stepper.setSpacing(6)
        for index, step in enumerate(self.STEPS):
            label = QLabel(f"{index + 1} · {step}")
            label.setObjectName("mutedLabel")
            stepper.addWidget(label)
            self._step_labels.append(label)
        stepper.addStretch()
        stepper_frame = QFrame()
        stepper_frame.setObjectName("panel")
        stepper_frame.setFixedWidth(170)
        stepper_frame_layout = QVBoxLayout(stepper_frame)
        stepper_frame_layout.setContentsMargins(14, 14, 14, 14)
        stepper_frame_layout.addLayout(stepper)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._page_select_vm())
        self.pages.addWidget(self._page_target_host())
        self.pages.addWidget(self._page_options())
        self.pages.addWidget(self._page_preflight())
        self.pages.addWidget(self._page_progress())
        self.pages.addWidget(self._page_result())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(stepper_frame)
        body.addWidget(self.pages, 1)

        self.back_button = QPushButton("Atrás")
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("Siguiente")
        self.next_button.clicked.connect(self.go_next)
        self.preflight_button = QPushButton("Comprobar antes de empezar")
        self.preflight_button.clicked.connect(self.run_preflight)
        self.package_button = QPushButton("Empezar el traslado")
        self.package_button.setObjectName("primaryButton")
        self.package_button.setEnabled(False)
        self.package_button.clicked.connect(self.start_migration)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.back_button)
        bottom.addStretch()
        bottom.addWidget(self.preflight_button)
        bottom.addWidget(self.package_button)
        bottom.addWidget(self.next_button)
        bottom.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(strategy_note)
        layout.addLayout(body, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(bottom)
        self.resize(920, 620)

        for widget in (self.registry_url, self.source_host_id, self.target_name, self.nas_path):
            widget.textChanged.connect(self.invalidate_preflight)
        for widget in (self.include_iso, self.include_snapshots, self.allow_paused):
            widget.toggled.connect(self.invalidate_preflight)
        self.target_host.currentIndexChanged.connect(self.invalidate_preflight)
        self.target_host.currentIndexChanged.connect(self._render_target_summary)
        self.transfer_mode.currentIndexChanged.connect(self._on_transfer_mode_changed)
        # VM encendida → modo «migración en vivo» por defecto; apagada → «Hub».
        if "running" in (self.vm.state or "").lower():
            live_idx = self.transfer_mode.findData("live")
            if live_idx >= 0:
                self.transfer_mode.setCurrentIndex(live_idx)
        self._on_transfer_mode_changed()

        self._set_step(0)
        self.refresh_hosts()

    def _on_transfer_mode_changed(self, *_args) -> None:
        mode = str(self.transfer_mode.currentData() or "")
        self.nas_path.setEnabled(mode == "nas")
        if hasattr(self, "nas_browse_button"):
            self.nas_browse_button.setEnabled(mode == "nas")
        if hasattr(self, "live_uri"):
            self.live_uri.setEnabled(mode == "live")
            if mode == "live" and not self.live_uri.text():
                target = self._selected_target()
                if target:
                    self.live_uri.setText(live_uri_for_host(target))
        self.invalidate_preflight()

    # ---------- pages ----------

    def _wizard_callout(self, text: str, tone: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(tone)
        label.setWordWrap(True)
        return label

    def _page_select_vm(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        card = QFrame()
        card.setObjectName("panel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(6)
        head = QHBoxLayout()
        name = QLabel(self.vm.name)
        name.setObjectName("sectionTitle")
        running = "running" in (self.vm.state or "").lower()
        state_chip = QLabel(humanize_vm_status(self.vm.state, "table"))
        state_chip.setObjectName("statusChipBad" if running else "statusChipOk")
        mode_chip = QLabel("Migración en vivo" if running else "Copia por Hub/NAS")
        mode_chip.setObjectName("statusChipWarn")
        head.addWidget(name)
        head.addWidget(state_chip)
        head.addWidget(mode_chip)
        head.addStretch()
        card_layout.addLayout(head)
        detail = QLabel(
            f"Pantalla: {getattr(self.vm, 'graphics', '') or '?'} · "
            f"RAM: {getattr(self.vm, 'ram_mib', 0) or '?'} MiB · vCPUs: {getattr(self.vm, 'vcpus', 0) or '?'} · "
            f"Laboratorio: {getattr(self.vm, 'lab_id', '') or '-'}"
        )
        detail.setObjectName("mutedLabel")
        card_layout.addWidget(detail)
        layout.addWidget(card)
        if running:
            layout.addWidget(self._wizard_callout(
                "Máquina ENCENDIDA: se usará migración en vivo (modo avanzado). La VM sigue "
                "funcionando durante el traslado y solo se congela unos milisegundos al final. "
                "Necesita conexión libvirt directa (qemu+ssh) entre los equipos.",
                "calloutInfo",
            ))
        form = QFormLayout()
        form.addRow("URL del Hub", self.registry_url)
        form.addRow("Equipo de origen", self.source_host_id)
        layout.addLayout(form)
        layout.addStretch()
        return page

    def _page_target_host(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        refresh_hosts = QPushButton("Actualizar equipos")
        refresh_hosts.clicked.connect(self.refresh_hosts)
        host_row = QHBoxLayout()
        host_row.addWidget(self.target_host, 1)
        host_row.addWidget(refresh_hosts)
        form = QFormLayout()
        form.addRow("Equipo de destino", host_row)
        layout.addLayout(form)
        self.target_summary = QLabel("Elige un equipo de destino del Hub.")
        self.target_summary.setObjectName("mutedLabel")
        self.target_summary.setWordWrap(True)
        summary_card = QFrame()
        summary_card.setObjectName("panel")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.addWidget(self.target_summary)
        layout.addWidget(summary_card)
        layout.addStretch()
        return page

    def _page_options(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        self.nas_browse_button = QPushButton("Examinar")
        self.nas_browse_button.clicked.connect(self.pick_nas_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.nas_path, 1)
        path_row.addWidget(self.nas_browse_button)
        form = QFormLayout()
        form.addRow("Nombre en el destino", self.target_name)
        form.addRow("Forma de envío", self.transfer_mode)
        form.addRow("Carpeta del NAS", path_row)
        form.addRow("Destino en vivo (URI)", self.live_uri)
        form.addRow("", self.include_iso)
        form.addRow("", self.include_snapshots)
        form.addRow("", self.allow_paused)
        form.addRow("", self.start_after_import)
        layout.addLayout(form)
        layout.addWidget(self._wizard_callout("La máquina original y sus discos no se borran.", "calloutOk"))
        layout.addStretch()
        return page

    def _page_preflight(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        hint = QLabel("Pulsa «Comprobar antes de empezar» para validar la máquina, el destino, el NAS y el nombre.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.result_view, 1)
        return page

    def _page_progress(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        self.migration_id_label = QLabel("El traslado no ha empezado todavía.")
        self.migration_id_label.setObjectName("sectionTitle")
        layout.addWidget(self.migration_id_label)
        self.progress_states_layout = QVBoxLayout()
        self.progress_states_layout.setSpacing(4)
        states_frame = QFrame()
        states_frame.setObjectName("panel")
        states_frame_layout = QVBoxLayout(states_frame)
        states_frame_layout.setContentsMargins(14, 12, 14, 12)
        states_frame_layout.addLayout(self.progress_states_layout)
        layout.addWidget(states_frame)
        self.progress_log = QTextEdit()
        self.progress_log.setReadOnly(True)
        layout.addWidget(self.progress_log, 1)
        actions = QHBoxLayout()
        self.refresh_status_button = QPushButton("Actualizar estado")
        self.refresh_status_button.clicked.connect(self.refresh_migration_status)
        self.refresh_status_button.setEnabled(False)
        copy_id = QPushButton("Copiar ID")
        copy_id.clicked.connect(self.copy_migration_id)
        copy_logs = QPushButton("Copiar registro")
        copy_logs.clicked.connect(self.copy_progress_logs)
        actions.addWidget(self.refresh_status_button)
        actions.addWidget(copy_id)
        actions.addWidget(copy_logs)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _page_result(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        self.result_card = QFrame()
        self.result_card.setObjectName("panel")
        result_card_layout = QVBoxLayout(self.result_card)
        result_card_layout.setContentsMargins(16, 14, 16, 14)
        self.result_title = QLabel("")
        self.result_title.setObjectName("sectionTitle")
        self.result_body = QLabel("")
        self.result_body.setObjectName("mutedLabel")
        self.result_body.setWordWrap(True)
        result_card_layout.addWidget(self.result_title)
        result_card_layout.addWidget(self.result_body)
        layout.addWidget(self.result_card)
        self.result_callout = QLabel("")
        self.result_callout.setWordWrap(True)
        layout.addWidget(self.result_callout)
        actions = QHBoxLayout()
        copy_summary = QPushButton("Copiar resumen")
        copy_summary.clicked.connect(self.copy_summary)
        self.back_to_preflight_button = QPushButton("Volver a la comprobación")
        self.back_to_preflight_button.clicked.connect(lambda: self._set_step(3))
        actions.addWidget(copy_summary)
        actions.addWidget(self.back_to_preflight_button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return page

    # ---------- navigation ----------

    def _set_step(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for step_index, label in enumerate(self._step_labels):
            if step_index == index:
                label.setObjectName("okLabel")
                label.setText(f"{step_index + 1} · {self.STEPS[step_index]}  ◀")
            else:
                label.setObjectName("mutedLabel")
                label.setText(f"{step_index + 1} · {self.STEPS[step_index]}")
            label.style().unpolish(label)
            label.style().polish(label)
        self._update_buttons()

    def current_step(self) -> int:
        return self.pages.currentIndex()

    def _vm_running(self) -> bool:
        return "running" in (self.vm.state or "").lower()

    def _selected_target(self) -> dict | None:
        target_id = str(self.target_host.currentData() or "")
        return next((host for host in self.hosts if host.get("host_id") == target_id), None)

    def _is_live_mode(self) -> bool:
        return str(self.transfer_mode.currentData() or "") == "live"

    def _target_ready(self) -> bool:
        target = self._selected_target()
        if not target:
            return False
        if str(target.get("host_id") or "") == self.source_host_id.text().strip():
            return False
        # Modo en vivo: el destino solo necesita estar online en el Hub; la
        # conectividad qemu+ssh la valida el preflight de la migración en vivo.
        if self._is_live_mode():
            return target.get("status") == "online"
        # Modo Hub/NAS: online + KVM/libvirt en el destino (lo coordina el Hub;
        # NO hace falta que origen y destino se vean entre sí).
        return bool(
            target.get("status") == "online"
            and target.get("kvm_ok")
            and target.get("libvirt_ok")
        )

    def _update_buttons(self) -> None:
        step = self.current_step()
        self.back_button.setVisible(1 <= step <= 3)
        self.next_button.setVisible(step <= 2)
        self.preflight_button.setVisible(step == 3)
        self.package_button.setVisible(step == 3)
        self.back_to_preflight_button.setVisible(
            step == 5 and bool(self.last_status) and str(self.last_status.get("status")) == "failed"
        )
        if step == 0:
            # Una VM ENCENDIDA puede avanzar: el único modo válido será la
            # migración en vivo (los modos Hub/NAS la rechazan en su preflight).
            # Una VM APAGADA también avanza (modos Hub/NAS). Nunca se bloquea aquí.
            self.next_button.setEnabled(True)
        elif step == 1:
            self.next_button.setEnabled(self._target_ready())
        elif step == 2:
            nas_ok = str(self.transfer_mode.currentData() or "") != "nas" or bool(self.nas_path.text().strip())
            self.next_button.setEnabled(bool(self.target_name.text().strip()) and nas_ok)

    def go_next(self) -> None:
        step = self.current_step()
        # VM encendida → fuerza el modo «migración en vivo» (es el único que la
        # acepta sin apagarla); VM apagada → deja los modos de copia (Hub/NAS).
        if step == 0 and self._vm_running():
            live_idx = self.transfer_mode.findData("live")
            if live_idx >= 0 and str(self.transfer_mode.currentData() or "") != "live":
                self.transfer_mode.setCurrentIndex(live_idx)
        if step == 1 and not self._target_ready():
            target = self._selected_target()
            if not target:
                msg = "Elige un equipo de destino del Hub. Si solo sale este equipo, arranca el agente en el otro."
            elif str(target.get("host_id") or "") == self.source_host_id.text().strip():
                msg = "El destino debe ser un equipo distinto del de origen."
            elif target.get("status") != "online":
                msg = "Ese equipo está sin conexión con el Hub. Arranca su agente."
            elif self._is_live_mode():
                msg = "El destino debe estar en línea en el Hub."
            else:
                msg = "El destino está en línea pero su KVM/libvirt no está listo para importar (lo coordina el Hub; no hace falta conectividad directa entre los equipos)."
            self.error_label.setText(msg)
            return
        if step < 3:
            self.error_label.clear()
            self._set_step(step + 1)

    def go_back(self) -> None:
        step = self.current_step()
        if 1 <= step <= 3:
            self.error_label.clear()
            self._set_step(step - 1)

    # ---------- hub/hosts ----------

    def refresh_hosts(self) -> None:
        from ..registry import RegistryClient

        self.error_label.clear()
        self.target_host.clear()
        self.hosts = []
        try:
            hosts = RegistryClient(self.registry_url.text().strip()).list_hosts()
        except HyperGeryError as exc:
            self.result_view.setPlainText(
                "No se puede contactar con el Hub. Revisa HYPERGERY_HUB_URL o arranca docker compose en docker/.\n"
                f"{exc}"
            )
            if hasattr(self, "target_summary"):
                self.target_summary.setText("No se puede contactar con el Hub — no hay equipos de destino.")
            self.invalidate_preflight()
            return
        self.hosts = hosts
        import socket as _socket

        # B5: destinos = hosts del Hub (excluido el origen). Sin descubrimiento
        # de red ni conectividad directa: el Hub coordina.
        candidates = hub_target_candidates(
            hosts, self.source_host_id.text().strip(), source_hostname=_socket.gethostname()
        )
        self.target_candidates = candidates
        for cand in candidates:
            online = "en línea" if cand["online"] else "sin conexión"
            label = f"{cand['host_id']} ({online})"
            if cand["hostname"]:
                label += f" · {cand['hostname']}"
            if cand["address"]:
                label += f" · {cand['address']}"
            if cand["online"] and not cand["ready"]:
                label += f" — {cand['reason']}"
            self.target_host.addItem(label, cand["host_id"])
            index = self.target_host.count() - 1
            item = self.target_host.model().item(index)
            item.setEnabled(cand["ready"])
            if not cand["ready"]:
                item.setToolTip(cand["reason"])
        if not hosts:
            self.result_view.setPlainText("El Hub no tiene equipos. Arranca antes los agentes en el origen y el destino.")
        elif not candidates:
            self.result_view.setPlainText(
                "El Hub solo conoce este equipo. Arranca el agente en el OTRO equipo y emparéjalo con el mismo Hub."
            )
        else:
            self.result_view.setPlainText(self._format_hosts(hosts))
        self._render_target_summary()
        self.invalidate_preflight()

    def _render_target_summary(self) -> None:
        if not hasattr(self, "target_summary"):
            return
        target = self._selected_target()
        if not target:
            self.target_summary.setText("Elige un equipo de destino del Hub.")
            return
        status = str(target.get("status") or "offline")
        lines = [
            f"Estado: {status.upper()}" ,
            f"KVM: {'OK' if target.get('kvm_ok') else 'FALLO'} · libvirt: {'OK' if target.get('libvirt_ok') else 'FALLO'}",
            f"RAM libre: {target.get('ram_free_mib', 0)} de {target.get('ram_total_mib', 0)} MiB · Disco libre: {target.get('disk_free_mib', 0)} MiB",
            f"Máquinas activas: {len(target.get('active_vms') or [])} · Última señal: {target.get('last_seen') or 'desconocida'}",
        ]
        if status != "online":
            lines.append("Un destino sin conexión bloquea el traslado.")
        if str(target.get("host_id") or "") == self.source_host_id.text().strip():
            lines.append("El destino debe ser distinto del origen.")
        self.target_summary.setText("\n".join(lines))

    def pick_nas_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta del NAS", self.nas_path.text(), FILE_DIALOG_OPTIONS)
        if path:
            self.nas_path.setText(path)

    def invalidate_preflight(self) -> None:
        self.preflight_result = None
        self.package_button.setEnabled(False)
        self._update_buttons()

    def values(self) -> dict:
        return {
            "vm_name": self.vm.name,
            "registry_url": self.registry_url.text().strip(),
            "source_host_id": self.source_host_id.text().strip(),
            "target_host_id": str(self.target_host.currentData() or ""),
            "target_vm_name": self.target_name.text().strip(),
            "transfer": str(self.transfer_mode.currentData() or "nas"),
            "nas_path": self.nas_path.text().strip(),
            "live_uri": self.live_uri.text().strip() if hasattr(self, "live_uri") else "",
            "include_iso": self.include_iso.isChecked(),
            "include_snapshots": self.include_snapshots.isChecked(),
            "allow_paused": self.allow_paused.isChecked(),
            "start_after_import": self.start_after_import.isChecked(),
        }

    # ---------- preflight ----------

    def run_preflight(self) -> None:
        from ..migration import migration_preflight

        self.error_label.clear()
        values = self.values()
        if not values["target_vm_name"]:
            self.error_label.setText("El nombre en el destino es obligatorio.")
            return
        if not values["source_host_id"]:
            self.error_label.setText("El ID del equipo de origen es obligatorio.")
            return
        if not values["target_host_id"]:
            self.error_label.setText("Elige un equipo de destino en línea.")
            return
        if values["transfer"] == "nas" and not values["nas_path"]:
            self.error_label.setText("La carpeta del NAS es obligatoria para el envío por NAS compartido.")
            return
        if values["target_host_id"] == values["source_host_id"]:
            self.error_label.setText("El destino debe ser distinto del origen.")
            self.package_button.setEnabled(False)
            return
        if values["transfer"] == "live":
            self._run_live_preflight(values)
            return
        target = self._selected_target()
        if not target or target.get("status") != "online":
            self.error_label.setText("El equipo de destino elegido está sin conexión.")
            self.package_button.setEnabled(False)
            return
        if not target.get("kvm_ok") or not target.get("libvirt_ok"):
            self.error_label.setText(
                "El destino está online en el Hub pero su KVM/libvirt no está listo para importar. "
                "Esto NO es un problema de conectividad entre los equipos: el Hub coordina el traslado."
            )
            self.package_button.setEnabled(False)
            return
        if values["transfer"] == "hub":
            from ..migration import hub_transfer_staging_dir

            staging_path = str(hub_transfer_staging_dir(self.backend) / "outgoing")
        else:
            staging_path = values["nas_path"]
        try:
            result = migration_preflight(
                self.backend,
                self.vm.name,
                target_host=values["target_host_id"],
                target_vm_name=values["target_vm_name"],
                nas_path=staging_path,
                allow_paused=values["allow_paused"],
                include_iso=values["include_iso"],
                include_snapshots=values["include_snapshots"],
            )
        except HyperGeryError as exc:
            self.error_label.setText(str(exc))
            self.package_button.setEnabled(False)
            return
        self.preflight_result = result
        self.result_view.setPlainText(self._format_preflight(result))
        self.package_button.setEnabled(bool(result.get("ok")))

    def _run_live_preflight(self, values: dict) -> None:
        """B3 modo B: comprobación ligera antes de la live migration. La VM
        debe estar ENCENDIDA y la URI ser segura (qemu+ssh/qemu+tls). El
        preflight profundo lo hace el propio LiveMigrator al arrancar."""
        from ..v1.live_migration import SECURE_URI_SCHEMES

        uri = values.get("live_uri", "")
        errors = []
        if "running" not in (self.vm.state or "").lower():
            errors.append("La migración en vivo necesita la VM ENCENDIDA (este modo NO la apaga).")
        if not uri:
            errors.append("Indica la URI del destino (qemu+ssh://usuario@equipo/system).")
        elif not uri.startswith(SECURE_URI_SCHEMES):
            errors.append("Solo se permiten URIs seguras: qemu+ssh:// o qemu+tls:// (qemu+tcp está prohibido).")
        if errors:
            self.preflight_result = {"ok": False, "errors": errors, "warnings": [], "assets": []}
            self.error_label.setText(" ".join(errors))
            self.result_view.setPlainText("\n".join(f"✗ {e}" for e in errors))
            self.package_button.setEnabled(False)
            return
        self.preflight_result = {"ok": True, "errors": [], "warnings": [], "assets": [], "live": True}
        self.result_view.setPlainText(
            "Modo: MIGRACIÓN EN VIVO (avanzado, libvirt directo).\n"
            f"VM: {self.vm.name} (encendida)\n"
            f"Destino: {uri}\n"
            "La VM sigue encendida durante el traslado; el downtime real se mide al terminar. "
            "Si falla, el origen queda intacto y corriendo (rollback)."
        )
        self.package_button.setEnabled(True)

    def _format_preflight(self, result: dict) -> str:
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        assets = result.get("assets", [])
        transfer = str(self.transfer_mode.currentData() or "nas")
        transfer_line = (
            "Envío: por el Hub (el paquete se sube al Hub y se borra de allí tras importarse)"
            if transfer == "hub"
            else "Envío: carpeta NAS compartida (debe verse en la misma ruta en ambos equipos)"
        )
        lines = [
            f"Estado: {'OK' if result.get('ok') else 'Bloqueado'}",
            f"Método: {result.get('strategy', 'offline-copy')} (copia, no migración en vivo)",
            transfer_line,
            f"¿Se borra el original?: {result.get('source_will_be_deleted')}",
            "Identidad en destino: el UUID y la MAC se regeneran al importar.",
            f"Tamaño estimado del paquete: {result.get('estimated_size_bytes', 0)} bytes",
            "",
            "Errores:",
            *(f"- {item}" for item in errors),
            "" if errors else "- ninguno",
            "",
            "Avisos:",
            *(f"- {item}" for item in warnings),
            "" if warnings else "- ninguno",
            "",
            "Archivos incluidos:",
        ]
        if assets:
            lines.extend(
                f"- {asset.get('type')} {asset.get('path')} ({asset.get('size_bytes', 0)} bytes)"
                for asset in assets
            )
        else:
            lines.append("- ninguno")
        return "\n".join(lines)

    def _format_hosts(self, hosts: list[dict]) -> str:
        lines = ["Equipos remotos:"]
        for host in hosts:
            active = ", ".join(host.get("active_vms") or []) or "ninguna"
            status = "en línea" if str(host.get("status")) == "online" else "sin conexión"
            lines.append(
                f"- {host.get('host_id')} · {status} · última señal {host.get('last_seen')} · "
                f"RAM libre {host.get('ram_free_mib')}/{host.get('ram_total_mib')} MiB · "
                f"disco libre {host.get('disk_free_mib')} MiB · "
                f"KVM {'sí' if host.get('kvm_ok') else 'NO'} · libvirt {'sí' if host.get('libvirt_ok') else 'NO'} · "
                f"máquinas activas: {active}"
            )
        return "\n".join(lines)

    # ---------- migration ----------

    def start_migration(self) -> None:
        if not self.preflight_result or not self.preflight_result.get("ok"):
            self.error_label.setText("Pasa la comprobación antes de empezar el traslado.")
            return
        values = self.values()
        self.error_label.clear()
        self.package_button.setEnabled(False)
        self._set_step(4)
        self.migration_id_label.setText("Empezando el traslado…")
        if values["transfer"] == "live":
            self._start_live_migration(values)
            return
        if values["transfer"] == "hub":
            progress_intro = (
                f"Empaquetando {values['vm_name']} y subiéndolo por el Hub hacia {values['target_host_id']}.\n"
                "La copia del Hub es temporal y se borra cuando el destino la importa.\n"
                "La máquina original y sus discos no se tocan."
            )
        else:
            progress_intro = (
                f"Empaquetando {values['vm_name']} en el NAS y encolando la importación en {values['target_host_id']}.\n"
                "La máquina original y sus discos no se tocan."
            )
        self.progress_log.setPlainText(progress_intro)
        self._render_progress_states("created")

        def do_migration() -> dict:
            from ..migration import start_remote_migration
            from ..registry import RegistryClient

            return start_remote_migration(
                self.backend,
                RegistryClient(values["registry_url"]),
                values["vm_name"],
                values["nas_path"],
                source_host_id=values["source_host_id"],
                target_host_id=values["target_host_id"],
                target_vm_name=values["target_vm_name"],
                allow_paused=values["allow_paused"],
                include_iso=values["include_iso"],
                include_snapshots=values["include_snapshots"],
                start_after_import=values["start_after_import"],
                transfer=values["transfer"],
            )

        from .workers import BackendJob

        job = BackendJob("start migration", do_migration)
        self._jobs.append(job)

        def succeeded() -> None:
            self.last_result = job.result or {}
            migration_id = str(self.last_result.get("migration_id") or "")
            self.migration_id_label.setText(f"ID del traslado: {migration_id}")
            self.progress_log.append(
                f"\nTraslado encolado.\nmigration_id: {migration_id}\n"
                f"package: {self.last_result.get('package_dir', '')}\n"
                f"orden en destino: {self.last_result.get('command_id', '')}\n"
                "Esperando a que el destino importe (el estado se actualiza solo)."
            )
            self.refresh_status_button.setEnabled(True)
            self._render_progress_states("uploaded")
            self.status_poll_timer.start()

        def failed() -> None:
            self.last_status = {"status": "failed", "error": job.error_message}
            self.progress_log.append(f"\nEl traslado no ha podido empezar: {job.error_message}")
            self._render_progress_states("failed")
            self._show_result_failure(job.error_message)

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.start()

    def _start_live_migration(self, values: dict) -> None:
        """B3 modo B: ejecuta la live migration directa (VM encendida) con
        LiveMigrator. El origen no se toca si falla (rollback del motor)."""
        uri = values.get("live_uri", "")
        self.progress_log.setPlainText(
            f"Migración EN VIVO de {self.vm.name} → {uri}.\n"
            "La VM sigue encendida; preflight → transferencia → conmutación → activación.\n"
            "Si algo falla, el origen queda corriendo e intacto."
        )
        self._render_progress_states("preflight")

        def do_live() -> dict:
            from ..v1.live_migration import LiveMigrationPlan, LiveMigrator

            plan = LiveMigrationPlan(
                vm_name=self.vm.name,
                target_uri=uri,
                shared_storage=None,  # autodetecta; el guard CIFS actúa en preflight
            )
            return LiveMigrator(self.backend, plan).run()

        from .workers import BackendJob

        job = BackendJob("live migration", do_live)
        self._jobs.append(job)

        def succeeded() -> None:
            self.last_result = job.result or {}
            self._show_live_result(self.last_result)

        def failed() -> None:
            self.last_status = {"status": "failed", "error": job.error_message}
            self.progress_log.append(f"\nLa migración en vivo no ha podido empezar: {job.error_message}")
            self._render_progress_states("failed")
            self._show_result_failure(job.error_message)

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.start()

    def _show_live_result(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        downtime = result.get("measured_downtime_ms")
        self._render_progress_states("done" if ok else "failed")
        if ok:
            self.result_title.setText("Migración en vivo completada")
            self.result_body.setText(
                f"Máquina: {self.vm.name}\n"
                f"Destino: {self.live_uri.text().strip()}\n"
                f"Downtime medido: {downtime if downtime is not None else '—'} ms\n"
                "El destino quedó ENCENDIDO; el origen ya no corre (nunca activa en dos equipos)."
            )
            self.result_callout.setText("Migración en caliente correcta · journal sin entradas pendientes.")
            self.result_callout.setObjectName("calloutOk")
        else:
            self.result_title.setText("La migración en vivo ha fallado")
            self.result_body.setText(
                f"Estado: {result.get('status', 'failed')}\n"
                f"Error: {result.get('error', '')}\n"
                f"Fases revertidas: {', '.join(result.get('rolled_back_phases') or []) or 'ninguna'}"
            )
            self.result_callout.setText("El origen quedó corriendo e intacto (rollback). Revisa el error y reinténtalo.")
            self.result_callout.setObjectName("calloutDanger")
        self.result_callout.style().unpolish(self.result_callout)
        self.result_callout.style().polish(self.result_callout)
        self._set_step(5)

    def _render_progress_states(self, current: str) -> None:
        while self.progress_states_layout.count():
            item = self.progress_states_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        failed = current == "failed"
        reached = True
        for state in self.MIGRATION_STATES:
            if failed:
                marker, name = ("✗", "errorLabel") if state == "done" else ("·", "mutedLabel")
            elif state == current:
                marker, name = "▶", "okLabel"
                reached = False
            elif reached:
                marker, name = "✓", "okLabel"
            else:
                marker, name = "·", "mutedLabel"
            label = QLabel(f"{marker} {state}")
            label.setObjectName(name)
            self.progress_states_layout.addWidget(label)

    def refresh_migration_status(self) -> None:
        migration_id = str((self.last_result or {}).get("migration_id") or "")
        if not migration_id:
            self.error_label.setText("Todavía no hay ningún traslado en marcha.")
            return
        if self._status_job_running:
            return
        url = self.registry_url.text().strip()

        def fetch() -> dict:
            from ..registry import RegistryClient

            return RegistryClient(url).migration(migration_id)

        from .workers import BackendJob

        job = BackendJob("migration status", fetch)
        self._jobs.append(job)
        self._status_job_running = True

        def succeeded() -> None:
            self._status_job_running = False
            record = job.result or {}
            previous = str((self.last_status or {}).get("status") or "")
            self.last_status = record
            status = str(record.get("status") or "unknown")
            if status != previous:
                self.progress_log.append(f"estado: {status}")
            self._render_progress_states(status if status in self.MIGRATION_STATES or status == "failed" else "created")
            if status == "done":
                self.status_poll_timer.stop()
                self._show_result_success(record)
            elif status == "failed":
                self.status_poll_timer.stop()
                errors = record.get("errors") or []
                self._show_result_failure("; ".join(str(item) for item in errors) or str(record.get("error") or "mira el registro del traslado"))

        def failed() -> None:
            self._status_job_running = False
            self.progress_log.append(f"no se ha podido consultar el estado: {job.error_message}")

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.start()

    # ---------- result ----------

    def _show_result_success(self, record: dict) -> None:
        migration_id = str((self.last_result or {}).get("migration_id") or record.get("migration_id") or "")
        package = str((self.last_result or {}).get("package_dir") or "")
        self.result_title.setText("Traslado completado")
        self.result_body.setText(
            f"ID del traslado: {migration_id}\n"
            f"Paquete: {package or 'en el NAS'} (se conserva)\n"
            f"Máquina en destino: {self.target_name.text().strip()} importada con UUID y MAC nuevos.\n"
            f"¿Encendida en destino?: {'sí' if self.start_after_import.isChecked() else 'no'}"
        )
        self.result_callout.setText("La máquina original no se ha tocado · UUID y MAC regenerados en destino.")
        self.result_callout.setObjectName("calloutOk")
        self.result_callout.style().unpolish(self.result_callout)
        self.result_callout.style().polish(self.result_callout)
        self._set_step(5)

    def _show_result_failure(self, error: str) -> None:
        self.result_title.setText("El traslado ha fallado")
        last = str((self.last_status or {}).get("status") or "failed")
        self.result_body.setText(f"Último estado: {last}\nError: {error}")
        self.result_callout.setText("La máquina original y sus discos no se han modificado. Revisa el error y reinténtalo desde la comprobación.")
        self.result_callout.setObjectName("calloutDanger")
        self.result_callout.style().unpolish(self.result_callout)
        self.result_callout.style().polish(self.result_callout)
        self._set_step(5)

    # ---------- clipboard ----------

    def _copy_text(self, text: str, empty_message: str) -> None:
        from PySide6.QtWidgets import QApplication

        if not text:
            self.error_label.setText(empty_message)
            return
        QApplication.clipboard().setText(text)
        self.error_label.clear()

    def copy_migration_id(self) -> None:
        self._copy_text(str((self.last_result or {}).get("migration_id") or ""), "Aún no hay ID. Empieza un traslado primero.")

    def copy_progress_logs(self) -> None:
        self._copy_text(self.progress_log.toPlainText(), "Aún no hay registro del traslado.")

    def copy_summary(self) -> None:
        summary = f"{self.result_title.text()}\n{self.result_body.text()}\n{self.result_callout.text()}".strip()
        self._copy_text(summary if self.result_title.text() else "", "Aún no hay resultado que copiar.")


class SnapshotDialog(QDialog):
    def __init__(self, backend: HyperGeryBackend, vm_name: str, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm_name = vm_name
        self.main_window = parent
        self.setWindowTitle(f"Instantáneas: {vm_name}")
        title = QLabel(vm_name)
        title.setObjectName("sectionTitle")
        self.snapshots = QListWidget()
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh)
        create = QPushButton("Crear")
        create.clicked.connect(self.create_snapshot)
        revert = QPushButton("Restaurar")
        revert.clicked.connect(self.revert_snapshot)
        delete = QPushButton("Eliminar")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self.delete_snapshot)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        actions = QHBoxLayout()
        actions.addWidget(create)
        actions.addWidget(revert)
        actions.addWidget(delete)
        actions.addStretch()
        actions.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.snapshots, 1)
        layout.addLayout(actions)
        self.resize(620, 420)
        self.refresh()

    def selected_snapshot(self) -> str:
        item = self.snapshots.currentItem()
        if item is None:
            raise HyperGeryError("Selecciona una instantánea primero.")
        return item.text()

    def refresh(self) -> None:
        self.snapshots.clear()
        try:
            for snapshot in self.backend.list_snapshots(self.vm_name):
                self.snapshots.addItem(snapshot)
        except Exception as exc:
            self.main_window.show_error(str(exc))

    def create_snapshot(self) -> None:
        name, ok = QInputDialog.getText(self, "Crear instantánea", "Nombre:")
        if not ok or not name.strip():
            return
        description, _ok = QInputDialog.getText(self, "Crear instantánea", "Descripción:")
        if QMessageBox.question(self, "Crear instantánea", f"¿Crear la instantánea {name.strip()} de {self.vm_name}?") != QMessageBox.StandardButton.Yes:
            return
        self.main_window.run_operation(
            f"Creando instantánea {name.strip()}",
            lambda: self.backend.create_snapshot(self.vm_name, name.strip(), description),
            on_success=lambda _result: self.refresh(),
        )

    def revert_snapshot(self) -> None:
        try:
            snapshot = self.selected_snapshot()
        except HyperGeryError as exc:
            self.main_window.show_error(str(exc))
            return
        if not confirm(
            self,
            "Restaurar instantánea",
            f"¿Devolver {self.vm_name} al estado de {snapshot}?\n\nEl disco volverá al estado de esa instantánea.",
        ):
            return
        self.main_window.run_operation(
            f"Restaurando {self.vm_name} a {snapshot}",
            lambda: self.backend.revert_snapshot(self.vm_name, snapshot),
            on_success=lambda _result: self.refresh(),
        )

    def delete_snapshot(self) -> None:
        try:
            snapshot = self.selected_snapshot()
        except HyperGeryError as exc:
            self.main_window.show_error(str(exc))
            return
        if not confirm(self, "Eliminar instantánea", f"¿Eliminar la instantánea {snapshot} de {self.vm_name}?"):
            return
        self.main_window.run_operation(
            f"Eliminando instantánea {snapshot}",
            lambda: self.backend.delete_snapshot(self.vm_name, snapshot),
            on_success=lambda _result: self.refresh(),
        )


class NewVmTemplateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nueva plantilla de máquina")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.validate)
        form.addRow("Nombre:", self.name_edit)

        self.id_preview = QLabel()
        self.id_preview.setObjectName("mutedLabel")
        form.addRow("ID de plantilla:", self.id_preview)

        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "otro"])
        form.addRow("Sistema operativo:", self.os_type)

        self.ram_mib = QSpinBox()
        self.ram_mib.setRange(512, 65536)
        self.ram_mib.setSingleStep(1024)
        self.ram_mib.setValue(4096)
        self.ram_mib.setSuffix(" MiB")
        form.addRow("RAM:", self.ram_mib)

        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(2)
        form.addRow("vCPUs:", self.vcpus)

        self.disk_gb = QSpinBox()
        self.disk_gb.setRange(1, 1024)
        self.disk_gb.setValue(40)
        self.disk_gb.setSuffix(" GiB")
        form.addRow("Disco:", self.disk_gb)

        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        form.addRow("Red:", self.network_mode)

        self.display_mode = QComboBox()
        self.display_mode.addItems(["spice", "vnc"])
        form.addRow("Pantalla:", self.display_mode)

        self.notes_edit = QLineEdit()
        form.addRow("Notas:", self.notes_edit)

        layout.addLayout(form)

        self.buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.validate()

    def validate(self) -> None:
        try:
            tid = normalize_template_id(self.name_edit.text())
            self.id_preview.setText(tid)
            self.id_preview.setStyleSheet("")
            valid = True
        except (ValueError, HyperGeryError):
            self.id_preview.setText("ID no válido")
            self.id_preview.setStyleSheet("color: #ff5555;")
            valid = False

        if not self.name_edit.text().strip():
            valid = False

        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "os_type": self.os_type.currentText(),
            "ram_mib": self.ram_mib.value(),
            "vcpus": self.vcpus.value(),
            "disk_gb": self.disk_gb.value(),
            "network_mode": self.network_mode.currentText(),
            "display": self.display_mode.currentText(),
            "notes": self.notes_edit.text().strip(),
        }


class NewLabTemplateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nueva plantilla de laboratorio")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.validate)
        form.addRow("Nombre:", self.name_edit)

        self.id_preview = QLabel()
        self.id_preview.setObjectName("mutedLabel")
        form.addRow("ID de plantilla:", self.id_preview)

        self.desc_edit = QLineEdit()
        form.addRow("Descripción:", self.desc_edit)

        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        form.addRow("Red:", self.network_mode)

        self.notes_edit = QLineEdit()
        form.addRow("Notas:", self.notes_edit)

        layout.addLayout(form)

        self.buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.validate()

    def validate(self) -> None:
        try:
            tid = normalize_template_id(self.name_edit.text())
            self.id_preview.setText(tid)
            self.id_preview.setStyleSheet("")
            valid = True
        except (ValueError, HyperGeryError):
            self.id_preview.setText("ID no válido")
            self.id_preview.setStyleSheet("color: #ff5555;")
            valid = False

        if not self.name_edit.text().strip():
            valid = False

        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
            "network_mode": self.network_mode.currentText(),
            "notes": self.notes_edit.text().strip(),
            "vms": [],
        }


class DeleteVmTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        template_id = str(template.get("template_id", ""))
        self.setWindowTitle(f"Eliminar plantilla de máquina: {template_id}")
        title = QLabel(f"¿Eliminar la plantilla de máquina {template_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("Solo se borra el archivo de la plantilla. No se borra ninguna máquina ni disco.")
        warning.setWordWrap(True)
        self.confirm_id = QLineEdit()
        self.confirm_id.setPlaceholderText(template_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.delete_button = buttons.addButton("Eliminar plantilla", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_id.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Escribe el ID", self.confirm_id)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(520, 240)

    def update_state(self) -> None:
        self.delete_button.setEnabled(self.confirm_id.text().strip() == str(self.template.get("template_id", "")))

    def accept(self) -> None:
        if self.confirm_id.text().strip() != str(self.template.get("template_id", "")):
            self.error_label.setText("Escribe el ID exacto para confirmar el borrado.")
            return
        super().accept()


class DeleteLabTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        template_id = str(template.get("template_id", ""))
        self.setWindowTitle(f"Eliminar plantilla de laboratorio: {template_id}")
        title = QLabel(f"¿Eliminar la plantilla de laboratorio {template_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("Solo se borra el archivo de la plantilla. No se borra ningún laboratorio ni máquina.")
        warning.setWordWrap(True)
        self.confirm_id = QLineEdit()
        self.confirm_id.setPlaceholderText(template_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.delete_button = buttons.addButton("Eliminar plantilla", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_id.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Escribe el ID", self.confirm_id)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(520, 240)

    def update_state(self) -> None:
        self.delete_button.setEnabled(self.confirm_id.text().strip() == str(self.template.get("template_id", "")))

    def accept(self) -> None:
        if self.confirm_id.text().strip() != str(self.template.get("template_id", "")):
            self.error_label.setText("Escribe el ID exacto para confirmar el borrado.")
            return
        super().accept()


class CreateLabFromTemplateDialog(QDialog):
    def __init__(self, template: dict, existing_lab_ids: set[str], existing_subnets: set[str], parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setWindowTitle(f"Crear laboratorio desde plantilla: {template.get('template_id', '')}")

        vms = template.get("vms", [])
        if vms:
            vm_names = ", ".join(str(v.get("name", "?")) for v in vms[:5])
            suffix = f" (+{len(vms) - 5} más)" if len(vms) > 5 else ""
            planned_text = f"Máquinas previstas ({len(vms)}): {vm_names}{suffix}"
        else:
            planned_text = "Esta plantilla no define máquinas."
        planned_label = QLabel(planned_text)
        planned_label.setObjectName("mutedLabel")
        planned_label.setWordWrap(True)

        caveat = QLabel(
            "Las máquinas no se crean automáticamente. "
            "Cuando el laboratorio esté listo, crea cada máquina a mano o desde una plantilla."
        )
        caveat.setObjectName("mutedLabel")
        caveat.setWordWrap(True)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(str(template.get("name", "Lab")) + " Instance")
        self.description_edit = QLineEdit(str(template.get("description", "")))
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        tmpl_net = str(template.get("network_mode", "nat"))
        net_idx = self.network_mode.findText(tmpl_net)
        if net_idx >= 0:
            self.network_mode.setCurrentIndex(net_idx)

        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_label.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")

        buttons = spanish_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.create_button = buttons.addButton("Crear laboratorio", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Plantilla", QLabel(f"{template.get('name', '')} ({template.get('template_id', '')})"))
        form.addRow("Nombre del nuevo laboratorio", self.name_edit)
        form.addRow("Descripción", self.description_edit)
        form.addRow("Modo de red", self.network_mode)
        form.addRow("Vista previa", self.preview_label)
        form.addRow("", self.error_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(planned_label)
        layout.addWidget(caveat)
        layout.addWidget(buttons)

        self.name_edit.textChanged.connect(self.update_preview)
        self.network_mode.currentTextChanged.connect(self.update_preview)
        self.update_preview()
        self.resize(640, 420)

    def current_preview(self) -> dict:
        return build_lab_preview(
            self.name_edit.text(),
            self.network_mode.currentText(),
            self.existing_lab_ids,
            self.existing_subnets,
        )

    def update_preview(self) -> None:
        preview = self.current_preview()
        self.create_button.setEnabled(bool(preview["valid"]))
        self.error_label.setText(preview["error"])
        if preview["valid"]:
            self.preview_label.setText(
                details_block(
                    ("ID", preview["lab_id"]),
                    ("Red", preview["network_id"]),
                    ("Puente", preview["bridge_name"]),
                    ("Subred", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Escribe un nombre válido para ver la vista previa de la red.")

    def values(self) -> dict:
        preview = self.current_preview()
        return {
            "name": self.name_edit.text().strip(),
            "description": self.description_edit.text().strip(),
            "network_mode": self.network_mode.currentText(),
            "lab_id": preview["lab_id"],
        }


# ---------------------------------------------------------------------------
# InstantiateLabTemplateWizard — Fase 2
# ---------------------------------------------------------------------------

class _LabIdentityPage(QWizardPage):
    def __init__(self, template: dict, existing_lab_ids: set, existing_subnets: set) -> None:
        super().__init__()
        self.template = template
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setTitle("Identidad del laboratorio")
        self.setSubTitle("Elige el nombre del nuevo laboratorio.")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(f"{template.get('name', 'Lab')} Instance")
        self.description_edit = QLineEdit(str(template.get("description", "")))
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        tmpl_net = str(template.get("network_mode", "nat"))
        net_idx = self.network_mode.findText(tmpl_net)
        if net_idx >= 0:
            self.network_mode.setCurrentIndex(net_idx)
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form = QFormLayout(self)
        form.addRow("Plantilla", QLabel(f"{template.get('name', '')} ({template.get('template_id', '')})"))
        form.addRow("Nombre del laboratorio *", self.name_edit)
        form.addRow("Descripción", self.description_edit)
        form.addRow("Modo de red", self.network_mode)
        form.addRow("Vista previa", self.preview_label)
        self.name_edit.textChanged.connect(self._refresh)
        self.network_mode.currentTextChanged.connect(self._refresh)
        self._refresh()

    def _preview(self) -> dict:
        return build_lab_preview(
            self.name_edit.text(),
            self.network_mode.currentText(),
            self.existing_lab_ids,
            self.existing_subnets,
        )

    def _refresh(self) -> None:
        p = self._preview()
        if p["valid"]:
            self.preview_label.setText(
                details_block(
                    ("Lab ID", p["lab_id"]),
                    ("Network", p["network_id"]),
                    ("Bridge", p["bridge_name"]),
                    ("Subnet", p["subnet"]),
                )
            )
        else:
            self.preview_label.setText(p["error"] or "Escribe un nombre válido.")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self._preview()["valid"])

    def lab_name(self) -> str:
        return self.name_edit.text().strip()

    def lab_description(self) -> str:
        return self.description_edit.text().strip()

    def lab_id(self) -> str:
        return self._preview()["lab_id"]


class _IsoMappingPage(QWizardPage):
    def __init__(self, template: dict) -> None:
        super().__init__()
        self.setTitle("ISOs de arranque")
        self.setSubTitle(
            "Elige una ISO de arranque para cada máquina que la necesite. "
            "Las máquinas marcadas con «No» pueden crearse sin imagen de arranque."
        )
        vms = template.get("vms", [])
        self.vm_rows: list[dict] = []
        self.iso_edits: list[QLineEdit] = []

        self.table = QTableWidget(len(vms), 5)
        self.table.setHorizontalHeaderLabels(["Ruta de la ISO", "Máquina", "Rol", "RAM MiB", "¿Necesita ISO?"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        for row, vm in enumerate(vms):
            iso_edit = QLineEdit()
            iso_edit.setPlaceholderText("/path/to/ubuntu.iso")
            iso_edit.textChanged.connect(self.completeChanged)
            browse_btn = QPushButton("…")
            browse_btn.setFixedWidth(30)
            browse_btn.clicked.connect(lambda _checked, e=iso_edit: self._browse(e))
            iso_cell = QHBoxLayout()
            iso_cell.setContentsMargins(2, 2, 2, 2)
            iso_cell.addWidget(iso_edit)
            iso_cell.addWidget(browse_btn)
            iso_widget = QFrame()
            iso_widget.setLayout(iso_cell)
            self.table.setCellWidget(row, 0, iso_widget)
            self.table.setItem(row, 1, QTableWidgetItem(str(vm.get("name", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(vm.get("role", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(vm.get("ram_mib", ""))))
            required_text = "Sí" if vm.get("iso_required", True) else "No"
            req_item = QTableWidgetItem(required_text)
            req_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, req_item)
            self.iso_edits.append(iso_edit)
            self.vm_rows.append({"name": str(vm.get("name", "")), "iso_required": vm.get("iso_required", True)})
            self.table.setRowHeight(row, 44)

        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        if not vms:
            layout.addWidget(QLabel("Esta plantilla no tiene máquinas previstas. Se creará solo la estructura del laboratorio."))
        else:
            apply_all_btn = QPushButton("Usar la misma ISO para todas…")
            apply_all_btn.clicked.connect(self._apply_all_iso)
            apply_all_row = QHBoxLayout()
            apply_all_row.addWidget(apply_all_btn)
            apply_all_row.addStretch()
            layout.addLayout(apply_all_row)
            layout.addWidget(self.table)
        layout.addWidget(self.status_label)

    def _apply_all_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir ISO para todas las máquinas", "", "Imágenes ISO (*.iso);;Todos los archivos (*)", "", FILE_DIALOG_OPTIONS
        )
        if path:
            for edit in self.iso_edits:
                edit.setText(path)

    def _browse(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir ISO", "", "Imágenes ISO (*.iso);;Todos los archivos (*)", "", FILE_DIALOG_OPTIONS
        )
        if path:
            edit.setText(path)

    def isComplete(self) -> bool:
        missing = [
            row_info["name"]
            for row_info, iso_edit in zip(self.vm_rows, self.iso_edits)
            if row_info["iso_required"] and not iso_edit.text().strip()
        ]
        if missing:
            self.status_label.setText(f"Falta la ISO de: {', '.join(missing)}")
            return False
        self.status_label.setText("")
        return True

    def iso_map(self) -> dict:
        return {row_info["name"]: iso_edit.text().strip()
                for row_info, iso_edit in zip(self.vm_rows, self.iso_edits)}


class _InstantiateReviewPage(QWizardPage):
    def __init__(self, template: dict, identity_page: _LabIdentityPage, iso_page: _IsoMappingPage) -> None:
        super().__init__()
        self.template = template
        self.identity_page = identity_page
        self.iso_page = iso_page
        self.setTitle("Resumen")
        self.setSubTitle("Confirma el laboratorio y las máquinas que se van a crear.")
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)

    def initializePage(self) -> None:
        vms = self.template.get("vms", [])
        iso_map = self.iso_page.iso_map()
        lines = [
            f"Plantilla:   {self.template.get('name', '')} ({self.template.get('template_id', '')})",
            f"Nombre:      {self.identity_page.lab_name()}",
            f"ID:          {self.identity_page.lab_id()}",
            f"Red:         {self.template.get('network_mode', 'nat')}",
            f"Descripción: {self.identity_page.lab_description()}",
            "",
            f"Máquinas que se crearán ({len(vms)}):",
        ]
        for vm in vms:
            name = str(vm.get("name", ""))
            iso = iso_map.get(name, "")
            role = vm.get("role", "")
            role_str = f"  rol={role}" if role else ""
            lines.append(
                f"  • {name}{role_str}  RAM={vm.get('ram_mib', '?')}MiB"
                f"  vCPUs={vm.get('vcpus', '?')}  Disco={vm.get('disk_gb', '?')}GB"
            )
            lines.append(f"    ISO: {iso or '(ninguna)'}")
        if not vms:
            lines.append("  (sin máquinas previstas — solo la estructura del laboratorio)")
        lines += [
            "",
            "Pulsa «Crear laboratorio» para empezar. Las máquinas se crean una a una.",
            "Si algo falla a medias, las máquinas ya creadas se eliminan.",
        ]
        self.summary.setPlainText("\n".join(lines))


class InstantiateLabTemplateWizard(QWizard):
    def __init__(self, template: dict, existing_lab_ids: set, existing_subnets: set, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Crear laboratorio desde plantilla: {template.get('template_id', '')}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.identity_page = _LabIdentityPage(template, existing_lab_ids, existing_subnets)
        self.iso_page = _IsoMappingPage(template)
        self.review_page = _InstantiateReviewPage(template, self.identity_page, self.iso_page)
        self.addPage(self.identity_page)
        self.addPage(self.iso_page)
        self.addPage(self.review_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Crear laboratorio")
        spanish_wizard_buttons(self)
        self.resize(760, 500)

    def values(self) -> dict:
        return {
            "lab_name": self.identity_page.lab_name(),
            "lab_description": self.identity_page.lab_description(),
            "lab_id": self.identity_page.lab_id(),
            "vm_iso_map": self.iso_page.iso_map(),
        }


# ---------------------------------------------------------------------------
# EditVmTemplateDialog — Fase 3
# ---------------------------------------------------------------------------

class EditVmTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.setWindowTitle(f"Editar plantilla de máquina: {template.get('template_id', '')}")
        self.name_edit = QLineEdit(str(template.get("name", "")))
        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "otro"])
        idx = self.os_type.findText(str(template.get("os_type", "linux")))
        if idx >= 0:
            self.os_type.setCurrentIndex(idx)
        self.ram = QSpinBox()
        self.ram.setRange(256, 262144)
        self.ram.setSingleStep(512)
        self.ram.setSuffix(" MiB")
        self.ram.setValue(int(template.get("ram_mib", 4096)))
        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(int(template.get("vcpus", 2)))
        self.disk = QSpinBox()
        self.disk.setRange(1, 65536)
        self.disk.setSuffix(" GB")
        self.disk.setValue(int(template.get("disk_gb", 40)))
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        net_idx = self.network_mode.findText(str(template.get("network_mode", "nat")))
        if net_idx >= 0:
            self.network_mode.setCurrentIndex(net_idx)
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
        disp_idx = self.display.findText(str(template.get("display", "spice")))
        if disp_idx >= 0:
            self.display.setCurrentIndex(disp_idx)
        self.notes_edit = QTextEdit(str(template.get("notes", "")))
        self.notes_edit.setMaximumHeight(80)
        buttons = spanish_buttons(QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        ))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("ID de plantilla", QLabel(str(template.get("template_id", ""))))
        form.addRow("Nombre", self.name_edit)
        form.addRow("Sistema operativo", self.os_type)
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Disco", self.disk)
        form.addRow("Red", self.network_mode)
        form.addRow("Pantalla", self.display)
        form.addRow("Notas", self.notes_edit)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(540, 420)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or self.template.get("template_id", ""),
            "os_type": self.os_type.currentText(),
            "ram_mib": self.ram.value(),
            "vcpus": self.vcpus.value(),
            "disk_gb": self.disk.value(),
            "network_mode": self.network_mode.currentText(),
            "display": self.display.currentText(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


# ---------------------------------------------------------------------------
# PlannedVmDialog — add or edit a planned VM (Fase 2 v0.5.0)
# ---------------------------------------------------------------------------

class PlannedVmDialog(QDialog):
    """Add or edit a planned VM entry in a Lab Template."""

    def __init__(self, existing: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar máquina prevista" if existing else "Añadir máquina prevista")
        self._original_name = str(existing.get("name", "")) if existing else ""
        self.name_edit = QLineEdit(self._original_name)
        self.name_edit.setPlaceholderText("server-01")
        self.role_edit = QLineEdit(str(existing.get("role", "")) if existing else "")
        self.role_edit.setPlaceholderText("servidor / cliente / router (opcional)")
        self.vm_template_edit = QLineEdit(str(existing.get("template_id", "")) if existing else "")
        self.vm_template_edit.setPlaceholderText("ubuntu-base (ID de plantilla, opcional)")
        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "otro"])
        os_idx = self.os_type.findText(str(existing.get("os_type", "linux")) if existing else "linux")
        if os_idx >= 0:
            self.os_type.setCurrentIndex(os_idx)
        self.ram = QSpinBox()
        self.ram.setRange(256, 262144)
        self.ram.setSingleStep(512)
        self.ram.setSuffix(" MiB")
        self.ram.setValue(int(existing.get("ram_mib", 2048)) if existing else 2048)
        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(int(existing.get("vcpus", 2)) if existing else 2)
        self.disk = QSpinBox()
        self.disk.setRange(1, 65536)
        self.disk.setSuffix(" GB")
        self.disk.setValue(int(existing.get("disk_gb", 20)) if existing else 20)
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
        disp_idx = self.display.findText(str(existing.get("display", "spice")) if existing else "spice")
        if disp_idx >= 0:
            self.display.setCurrentIndex(disp_idx)
        self.notes_edit = QLineEdit(str(existing.get("notes", "")) if existing else "")
        self.iso_required = QCheckBox("Necesita ISO al crear el laboratorio")
        self.iso_required.setChecked(bool(existing.get("iso_required", True)) if existing else True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = spanish_buttons(QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        ))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Nombre de la máquina *", self.name_edit)
        form.addRow("Rol", self.role_edit)
        form.addRow("Plantilla de máquina", self.vm_template_edit)
        form.addRow("Sistema operativo", self.os_type)
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Disco", self.disk)
        form.addRow("Pantalla", self.display)
        form.addRow("Notas", self.notes_edit)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.iso_required)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(480, 420)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.error_label.setText("El nombre de la máquina no puede estar vacío.")
            return
        import re as _re
        if not _re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_\-]{0,61}", name):
            self.error_label.setText("El nombre debe empezar por letra o número, y solo puede llevar letras, números, guiones y guiones bajos.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "role": self.role_edit.text().strip(),
            "template_id": self.vm_template_edit.text().strip(),
            "os_type": self.os_type.currentText(),
            "ram_mib": self.ram.value(),
            "vcpus": self.vcpus.value(),
            "disk_gb": self.disk.value(),
            "display": self.display.currentText(),
            "notes": self.notes_edit.text().strip(),
            "iso_required": self.iso_required.isChecked(),
        }


# ---------------------------------------------------------------------------
# EditLabTemplateDialog — improved (Fase 2 v0.5.0)
# ---------------------------------------------------------------------------

_VM_TABLE_COLS = ["Nombre", "Rol", "SO", "RAM MiB", "vCPUs", "Disco GB", "Pantalla", "¿ISO?"]


class EditLabTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.setWindowTitle(f"Editar plantilla de laboratorio: {template.get('template_id', '')}")
        self.name_edit = QLineEdit(str(template.get("name", "")))
        self.description_edit = QLineEdit(str(template.get("description", "")))
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        net_idx = self.network_mode.findText(str(template.get("network_mode", "nat")))
        if net_idx >= 0:
            self.network_mode.setCurrentIndex(net_idx)
        self.notes_edit = QTextEdit(str(template.get("notes", "")))
        self.notes_edit.setMaximumHeight(70)

        # --- Planned VMs table ---
        vms = template.get("vms", [])
        self._vms: list[dict] = list(vms)
        self.vm_table = QTableWidget(0, len(_VM_TABLE_COLS))
        self.vm_table.setHorizontalHeaderLabels(_VM_TABLE_COLS)
        self.vm_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vm_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.vm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vm_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_VM_TABLE_COLS)):
            self.vm_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.vm_table.verticalHeader().setVisible(False)
        self.vm_table.setAlternatingRowColors(True)
        self.vm_table.itemDoubleClicked.connect(self._edit_vm)
        for vm in vms:
            self._append_vm_row(vm)

        add_btn = QPushButton("Añadir máquina…")
        edit_btn = QPushButton("Editar seleccionada…")
        remove_btn = QPushButton("Quitar seleccionada")
        add_btn.clicked.connect(self._add_vm)
        edit_btn.clicked.connect(self._edit_vm)
        remove_btn.clicked.connect(self._remove_vm)
        vm_buttons = QHBoxLayout()
        vm_buttons.addWidget(add_btn)
        vm_buttons.addWidget(edit_btn)
        vm_buttons.addWidget(remove_btn)
        vm_buttons.addStretch()

        buttons = spanish_buttons(QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        ))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("ID de plantilla", QLabel(str(template.get("template_id", ""))))
        form.addRow("Nombre", self.name_edit)
        form.addRow("Descripción", self.description_edit)
        form.addRow("Modo de red", self.network_mode)
        form.addRow("Notas", self.notes_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Máquinas previstas (doble clic para editar):"))
        layout.addWidget(self.vm_table)
        layout.addLayout(vm_buttons)
        layout.addWidget(buttons)
        self.resize(720, 560)

    def _append_vm_row(self, vm: dict) -> None:
        row = self.vm_table.rowCount()
        self.vm_table.insertRow(row)
        items = [
            str(vm.get("name", "")),
            str(vm.get("role", "")),
            str(vm.get("os_type", "")),
            str(vm.get("ram_mib", "")),
            str(vm.get("vcpus", "")),
            str(vm.get("disk_gb", "")),
            str(vm.get("display", "")),
            "Sí" if vm.get("iso_required", True) else "No",
        ]
        for col, text in enumerate(items):
            self.vm_table.setItem(row, col, QTableWidgetItem(text))

    def _refresh_row(self, row: int, vm: dict) -> None:
        items = [
            str(vm.get("name", "")),
            str(vm.get("role", "")),
            str(vm.get("os_type", "")),
            str(vm.get("ram_mib", "")),
            str(vm.get("vcpus", "")),
            str(vm.get("disk_gb", "")),
            str(vm.get("display", "")),
            "Sí" if vm.get("iso_required", True) else "No",
        ]
        for col, text in enumerate(items):
            self.vm_table.setItem(row, col, QTableWidgetItem(text))

    def _add_vm(self) -> None:
        dialog = PlannedVmDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vm = dialog.values()
        existing_names = {v["name"] for v in self._vms}
        if vm["name"] in existing_names:
            QMessageBox.warning(self, "Nombre repetido", f"Ya existe una máquina prevista llamada '{vm['name']}'.")
            return
        self._vms.append(vm)
        self._append_vm_row(vm)

    def _edit_vm(self, *_args: object) -> None:
        row = self.vm_table.currentRow()
        if row < 0 or row >= len(self._vms):
            return
        existing = self._vms[row]
        dialog = PlannedVmDialog(existing=existing, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.values()
        if updated["name"] != existing["name"]:
            other_names = {v["name"] for i, v in enumerate(self._vms) if i != row}
            if updated["name"] in other_names:
                QMessageBox.warning(self, "Nombre repetido", f"Ya existe una máquina prevista llamada '{updated['name']}'.")
                return
        self._vms[row] = updated
        self._refresh_row(row, updated)

    def _remove_vm(self) -> None:
        row = self.vm_table.currentRow()
        if row < 0 or row >= len(self._vms):
            return
        self._vms.pop(row)
        self.vm_table.removeRow(row)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or self.template.get("template_id", ""),
            "description": self.description_edit.text().strip(),
            "network_mode": self.network_mode.currentText(),
            "vms": list(self._vms),
            "notes": self.notes_edit.toPlainText().strip(),
        }


# ---------------------------------------------------------------------------
# CleanupPreviewDialog — Fase 4 v0.5.0
# ---------------------------------------------------------------------------

class CleanupPreviewDialog(QDialog):
    """Read-only preview of HyperGery-managed resources. Nothing is deleted here."""

    def __init__(self, vms: list, labs: list, vm_templates: list, lab_templates: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recursos de HyperGery")
        self.resize(760, 520)

        lines = ["Recursos gestionados por HyperGery\n"]
        lines.append(f"Máquinas ({len(vms)}):")
        for vm in vms:
            state = getattr(vm, "state", "?")
            lab = getattr(vm, "lab_id", "") or "default-lab"
            lines.append(f"  • {vm.name}  estado={state}  laboratorio={lab}")
        lines.append("")
        lines.append(f"Laboratorios ({len(labs)}):")
        for lab in labs:
            vm_count = len(lab.get("vms", []))
            subnet = lab.get("subnet", "")
            lines.append(f"  • {lab.get('lab_id', '?')}  nombre={lab.get('name', '')}  máquinas={vm_count}  subred={subnet}")
        lines.append("")
        lines.append(f"Plantillas de máquina ({len(vm_templates)}):")
        for tmpl in vm_templates:
            lines.append(f"  • {tmpl.get('template_id', '?')}  ({tmpl.get('os_type', '')}  {tmpl.get('ram_mib', '')} MiB)")
        lines.append("")
        lines.append(f"Plantillas de laboratorio ({len(lab_templates)}):")
        for tmpl in lab_templates:
            vm_count = len(tmpl.get("vms", []))
            lines.append(f"  • {tmpl.get('template_id', '?')}  máquinas previstas={vm_count}")
        lines.append("")
        lines.append("Para borrar recursos usa los botones «Eliminar» de la ventana principal.")
        lines.append("Esta ventana no modifica nada.")

        text = QTextEdit("\n".join(lines))
        text.setReadOnly(True)
        text.setFont(QFont("monospace", 9))

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Resumen de todos los recursos gestionados por HyperGery (solo lectura):"))
        layout.addWidget(text)
        layout.addLayout(btn_row)
