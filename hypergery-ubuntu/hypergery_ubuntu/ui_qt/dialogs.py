from __future__ import annotations

import html
import os
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
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
from .lab_helpers import build_lab_preview
from .styles import details_block

if TYPE_CHECKING:
    from .main_window import MainWindow


FILE_DIALOG_OPTIONS = QFileDialog.Option.DontUseNativeDialog


class AppSettingsDialog(QDialog):
    SECTIONS = ("General", "Hub", "Host Agent", "NAS", "VM Defaults", "Console", "Appearance", "Advanced")

    def __init__(self, backend: HyperGeryBackend, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("HyperGery Settings")
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

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Hub, agent, NAS, and VM defaults. Each field shows whether its value comes from environment, config, or default."
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
            self._field("Host ID", self.host_id, "host_id", "Stable, unique identifier for this host in the Hub."),
            self._field("Host name", self.host_name, "host_name", "Readable name shown in Remote Hosts."),
        )))
        test_hub = QPushButton("Test Hub")
        test_hub.clicked.connect(self.test_hub)
        self.pages.addWidget(self._section_page((
            self._field("Hub URL", self.hub_url, "hub_url", "HYPERGERY_HUB_URL overrides this saved value."),
            self._button_row(test_hub),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("The agent only runs allowlisted commands and rejects package paths outside the NAS staging root.", "calloutInfo"),
            self._callout("The agent reuses the Hub, Host identity, and NAS settings from the other sections. Extra agent options are planned for v0.7.x.", "calloutInfo"),
        )))
        test_nas = QPushButton("Test NAS Write")
        test_nas.clicked.connect(self.test_nas)
        self.pages.addWidget(self._section_page((
            self._field("NAS staging path", self.nas_staging_path, "nas_staging_path", "Shared Linux mount for migration packages, e.g. /mnt/hypergery-nas/hypergery."),
            self._button_row(test_nas),
            self._callout("The Hub SQLite DB must never live on NAS/SMB — keep it in the Docker volume.", "calloutDanger"),
        )))
        self.pages.addWidget(self._section_page((
            self._field("Default display", self.default_display, "default_display", "vnc enables the integrated console; spice uses the external viewer."),
            self._field("Default ISO folder", self.default_iso_folder, "default_iso_folder", "Starting folder for ISO selection in the New VM wizard."),
            self._field("Default VM storage path", self.default_vm_storage_path, "default_vm_storage_path", "Optional default disk directory for new VMs."),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("Host Key to release console input: Right Ctrl. SPICE VMs always use the external viewer.", "calloutInfo"),
            self._callout("Console preferences (Scale to Fit default, viewer command) are planned for v0.7.x.", "calloutInfo"),
        )))
        self.pages.addWidget(self._section_page((
            self._callout("Dark is the v0.7 theme. Accent and density options are planned for v0.7.x.", "calloutInfo"),
        )))
        config_file = QLineEdit(str(config_path()))
        config_file.setReadOnly(True)
        test_libvirt = QPushButton("Test libvirt")
        test_libvirt.clicked.connect(self.test_libvirt)
        self.pages.addWidget(self._section_page((
            self._field("Config file", config_file, None, "Settings are stored as JSON. Environment variables always take priority."),
            self._button_row(test_libvirt),
            self._callout("Reset Defaults only fills the form; nothing changes until you Save. Environment variables keep priority.", "calloutWarn"),
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

        reset = QPushButton("Reset Defaults")
        reset.clicked.connect(self.reset_defaults)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
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
            text, name = "DEFAULT", "srcChipDefault"
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
            self._set_status("Hub URL must start with http:// or https://", "fail")
            self.section_nav.setCurrentRow(self.SECTIONS.index("Hub"))
            return
        self.accept()

    def test_hub(self) -> None:
        try:
            result = RegistryClient(self.hub_url.text().strip(), timeout=3).health()
            self._set_status(f"Hub OK: {result}", "ok")
        except HyperGeryError as exc:
            self._set_status(f"Hub FAIL: {exc}", "fail")

    def test_nas(self) -> None:
        path = Path(self.nas_staging_path.text().strip()).expanduser()
        if not path.is_dir():
            self._set_status(f"NAS FAIL: path does not exist: {path}", "fail")
            return
        try:
            with tempfile.NamedTemporaryFile(prefix=".hypergery-write-", dir=path, delete=True) as fh:
                fh.write(b"ok")
                fh.flush()
            self._set_status(f"NAS OK: writable {path}", "ok")
        except OSError as exc:
            self._set_status(f"NAS FAIL: {exc}", "fail")

    def test_libvirt(self) -> None:
        try:
            items = self.backend.preflight()
        except Exception as exc:
            self._set_status(f"libvirt FAIL: {exc}", "fail")
            return
        failures = [item for item in items if item.status == "Error" and item.name in {"libvirt connection", "virsh"}]
        if not failures:
            self._set_status("libvirt OK", "ok")
        else:
            self._set_status("libvirt FAIL: " + "; ".join(item.detail for item in failures), "fail")

    def reset_defaults(self) -> None:
        defaults = default_config_values()
        self.hub_url.setText(defaults["hub_url"])
        self.host_id.setText(defaults["host_id"])
        self.host_name.setText(defaults["host_name"])
        self.nas_staging_path.setText(defaults["nas_staging_path"])
        self.default_display.setCurrentIndex(self.default_display.findText(defaults["default_display"]))
        self.default_iso_folder.setText(defaults["default_iso_folder"])
        self.default_vm_storage_path.setText(defaults["default_vm_storage_path"])
        self._set_status("Defaults loaded into the form (non-destructive). Select Save to persist them.", "neutral")


class IdentityPage(QWizardPage):
    def __init__(self, default_iso_folder: str = "") -> None:
        super().__init__()
        self.default_iso_folder = default_iso_folder
        self.setTitle("Identity")
        self.setSubTitle("Choose the VM name and boot ISO.")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ubuntu-lab-01")
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("/path/to/ubuntu.iso")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.pick_iso)
        self.os_type = QComboBox()
        self.os_type.addItems(["Linux", "Windows", "Other"])

        iso_row = QHBoxLayout()
        iso_row.addWidget(self.iso_edit, 1)
        iso_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Boot ISO", iso_row)
        form.addRow("OS type", self.os_type)
        form.addRow("", self.error_label)
        wrapper = QVBoxLayout(self)
        wrapper.addLayout(form)
        wrapper.addStretch()

        self.registerField("name*", self.name_edit)
        self.registerField("iso*", self.iso_edit)
        self.registerField("os_type", self.os_type, "currentText", self.os_type.currentTextChanged)
        self.name_edit.textChanged.connect(lambda _text: self.completeChanged.emit())
        self.iso_edit.textChanged.connect(lambda _text: self.completeChanged.emit())

    def pick_iso(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select boot ISO",
            self.default_iso_folder,
            "ISO images (*.iso);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if path:
            self.iso_edit.setText(path)

    def isComplete(self) -> bool:
        return bool(self.name_edit.text().strip() and self.iso_edit.text().strip())

    def validatePage(self) -> bool:
        self.error_label.clear()
        if not self.name_edit.text().strip():
            self.error_label.setText("VM name is required.")
            return False
        iso = Path(self.iso_edit.text()).expanduser()
        if not iso.is_file():
            self.error_label.setText(f"Boot ISO does not exist: {iso}")
            return False
        return True


class ResourcesPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Resources")
        self.setSubTitle("Set CPU, memory and disk size.")
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
        form.addRow("Disk", self.disk)
        self.registerField("ram", self.ram)
        self.registerField("vcpus", self.vcpus)
        self.registerField("disk", self.disk)


class IntegrationPage(QWizardPage):
    def __init__(self, default_lab_id: str = "default-lab", default_disk_dir: str = "", default_display: str = "") -> None:
        super().__init__()
        self.setTitle("Storage & Network")
        self.setSubTitle("Choose disk location, lab network and console type.")
        self.disk_dir = QLineEdit()
        self.disk_dir.setText(default_disk_dir)
        self.disk_dir.setPlaceholderText("Default HyperGery VM directory")
        browse = QPushButton("Browse")
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

        disk_row = QHBoxLayout()
        disk_row.addWidget(self.disk_dir, 1)
        disk_row.addWidget(browse)

        form = QFormLayout(self)
        form.addRow("Disk directory", disk_row)
        form.addRow("Network", self.network)
        form.addRow("Display", self.display)
        form.addRow("Lab ID", self.lab_id)
        hint = QLabel("Empty disk directory uses ~/.local/share/hypergery/vms/<vm-name>/")
        hint.setObjectName("mutedLabel")
        form.addRow("", hint)
        display_hint = QLabel("Integrated console requires VNC. SPICE uses external viewer.")
        display_hint.setObjectName("mutedLabel")
        form.addRow("", display_hint)
        self.registerField("disk_dir", self.disk_dir)
        self.registerField("network", self.network, "currentText", self.network.currentTextChanged)
        self.registerField("display", self.display, "currentText", self.display.currentTextChanged)
        self.registerField("lab_id", self.lab_id)

    def pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select disk directory", "", FILE_DIALOG_OPTIONS)
        if path:
            self.disk_dir.setText(path)


class ReviewPage(QWizardPage):
    def __init__(self, wizard: "VMWizard") -> None:
        super().__init__()
        self.vm_wizard = wizard
        self.setTitle("Review")
        self.setSubTitle("Confirm what HyperGery will create.")
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
                    ("Name", values["name"]),
                    ("Boot ISO", values["iso_path"]),
                    ("OS type", values["os_type"]),
                    ("RAM", f"{values['ram_mib']} MiB"),
                    ("vCPUs", str(values["vcpus"])),
                    ("Disk", f"{values['disk_gb']} GiB qcow2"),
                    ("Disk directory", values["disk_dir"] or "~/.local/share/hypergery/vms/<vm-name>/"),
                    ("Network", values["network_mode"]),
                    ("Display", values["display_mode"]),
                    ("Lab", values["lab_id"]),
                )
            )
            + "</pre>"
        )


class VMWizard(QWizard):
    def __init__(self, parent=None, *, default_lab_id: str = "default-lab", defaults: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Virtual Machine")
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
        self.setButtonText(QWizard.WizardButton.FinishButton, "Create")
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
        return {
            "name": self.identity_page.name_edit.text().strip(),
            "iso_path": self.identity_page.iso_edit.text().strip(),
            "os_type": self.identity_page.os_type.currentText(),
            "ram_mib": self.resources_page.ram.value(),
            "vcpus": self.resources_page.vcpus.value(),
            "disk_gb": self.resources_page.disk.value(),
            "disk_dir": self.integration_page.disk_dir.text().strip() or None,
            "network_mode": self.integration_page.network.currentText(),
            "display_mode": self.integration_page.display.currentText(),
            "lab_id": self.integration_page.lab_id.text().strip() or "default-lab",
        }


class NewLabDialog(QDialog):
    def __init__(self, existing_lab_ids: set[str], existing_subnets: set[str], parent=None) -> None:
        super().__init__(parent)
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setWindowTitle("New Lab")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Security Lab")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional description")
        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_label.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Network mode", self.network_mode)
        form.addRow("Preview", self.preview_label)
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
                    ("Lab ID", preview["lab_id"]),
                    ("Network", preview["network_id"]),
                    ("Bridge", preview["bridge_name"]),
                    ("Subnet", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Complete a valid lab name to preview network resources.")

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
        self.setWindowTitle(f"Rename Lab: {lab.get('lab_id', 'unknown')}")
        self.name_edit = QLineEdit(str(lab.get("name") or lab.get("lab_id") or ""))
        self.description_edit = QLineEdit(str(lab.get("description") or ""))
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        notice = QLabel("This changes only the visible name and description. The lab ID and network resources stay unchanged.")
        notice.setObjectName("mutedLabel")
        notice.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Lab ID", QLabel(str(lab.get("lab_id", ""))))
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("", self.error_label)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(620, 260)

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("Lab name is required.")
            return
        super().accept()

    def values(self) -> dict:
        return {"name": self.name_edit.text().strip(), "description": self.description_edit.text().strip()}


class DeleteLabDialog(QDialog):
    def __init__(self, lab: dict, parent=None) -> None:
        super().__init__(parent)
        self.lab = lab
        lab_id = str(lab.get("lab_id", ""))
        self.setWindowTitle(f"Delete Lab: {lab_id}")
        title = QLabel(f"Delete lab {lab_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("This removes the lab manifest. VMs are not deleted by default.")
        warning.setWordWrap(True)
        self.delete_vms = QCheckBox("Delete VMs too (disk cloning not yet implemented)")
        self.delete_vms.setEnabled(False)
        self.confirm_lab = QLineEdit()
        self.confirm_lab.setPlaceholderText(lab_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton("Delete Lab", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_lab.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Type lab ID", self.confirm_lab)
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
            self.error_label.setText("Type the exact lab ID to confirm deletion.")
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
        self.setWindowTitle(f"Duplicate Lab: {source_lab.get('lab_id', 'unknown')}")
        self.name_edit = QLineEdit(f"{source_lab.get('name') or source_lab.get('lab_id')} Copy")
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("mutedLabel")
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_label.setWordWrap(True)
        has_vms = bool(source_lab.get("vms"))
        self.clone_vms = QCheckBox("Clone VMs too (requires all VMs shut off; clones qcow2 disks)")
        self.clone_vms.setEnabled(has_vms)
        if not has_vms:
            self.clone_vms.setToolTip("No VMs in this lab to clone.")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.duplicate_button = buttons.addButton("Duplicate", QDialogButtonBox.ButtonRole.AcceptRole)
        self.duplicate_button.setObjectName("primaryButton")
        self.duplicate_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Source", QLabel(str(source_lab.get("lab_id", ""))))
        form.addRow("New lab name", self.name_edit)
        form.addRow("Preview", self.preview_label)
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
                    ("Lab ID", preview["lab_id"]),
                    ("Network", preview["network_id"]),
                    ("Bridge", preview["bridge_name"]),
                    ("Subnet", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Choose a valid new lab name.")

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
        self.setWindowTitle(f"Settings: {vm.name}")
        self.ram = QSpinBox()
        self.ram.setRange(256, 262144)
        self.ram.setSingleStep(512)
        self.ram.setValue(vm.ram_mib or 4096)
        self.ram.setSuffix(" MiB")
        self.vcpus = QSpinBox()
        self.vcpus.setRange(1, 128)
        self.vcpus.setValue(vm.vcpus or 2)
        self.iso = QLineEdit(vm.iso_path)
        browse = QPushButton("Browse")
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

        form = QFormLayout()
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Boot ISO", iso_row)
        form.addRow("Network", self.network)
        form.addRow("Display", self.display)
        form.addRow("Lab ID", self.lab_id)
        display_hint = QLabel("Integrated console requires VNC. SPICE uses external viewer.")
        display_hint.setObjectName("mutedLabel")
        form.addRow("", display_hint)
        form.addRow("", self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        hint = QLabel("Settings are applied through libvirt and require the VM to be shut off.")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.resize(640, 360)

    def pick_iso(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select boot ISO",
            "",
            "ISO images (*.iso);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if path:
            self.iso.setText(path)

    def accept(self) -> None:
        iso = self.iso.text().strip()
        if iso and not Path(iso).expanduser().is_file():
            self.error_label.setText(f"Boot ISO does not exist: {iso}")
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
        self.setWindowTitle(f"Clone: {source_name}")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(f"{source_name}-clone")
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        form = QFormLayout()
        form.addRow("Source", QLabel(source_name))
        form.addRow("New VM name", self.name_edit)
        form.addRow("", self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Clone")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("Clone name is required.")
            return
        super().accept()

    def clone_name(self) -> str:
        return self.name_edit.text().strip()


class DeleteConfirmationDialog(QDialog):
    def __init__(self, vm: VmSummary, parent=None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.setWindowTitle(f"Delete VM: {vm.name}")
        title = QLabel(f"Delete {vm.name}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("This undefines the VM from libvirt. Disk deletion is limited to HyperGery-managed disks.")
        warning.setWordWrap(True)
        self.delete_disk = QCheckBox("Also remove the HyperGery-managed disk when safe")
        self.confirm_name = QLineEdit()
        self.confirm_name.setPlaceholderText(vm.name)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton("Delete VM", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_name.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Type VM name", self.confirm_name)
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
            self.error_label.setText("Type the exact VM name to confirm deletion.")
            return
        super().accept()

    def delete_disks(self) -> bool:
        return self.delete_disk.isChecked()


class LiveMigrationDialog(QDialog):
    """NAS Clone Migration wizard: stepper + stacked pages over the existing v0.6 flow."""

    STEPS = ("Select VM", "Target Host", "Options", "Preflight", "Progress", "Result")
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
        self.setWindowTitle(f"NAS Clone Migration: {vm.name}")

        app_config = effective_config()
        self.registry_url = QLineEdit(app_config["hub_url"].value)
        self.source_host_id = QLineEdit(app_config["host_id"].value)
        self.target_host = QComboBox()
        self.target_name = QLineEdit(f"{vm.name}-migrated")
        self.transfer_mode = QComboBox()
        self.transfer_mode.addItem("Hub transfer — upload through the Hub, no shared NAS mount needed", "hub")
        self.transfer_mode.addItem("Shared NAS path — same mount visible on both hosts", "nas")
        self.nas_path = QLineEdit(app_config["nas_staging_path"].value)
        self.include_iso = QCheckBox("Include attached ISO")
        self.include_iso.setChecked(True)
        self.include_snapshots = QCheckBox("Include snapshot file assets when detectable")
        self.include_snapshots.setChecked(True)
        self.allow_paused = QCheckBox("Allow paused VM packaging")
        self.start_after_import = QCheckBox("Start after import")
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(170)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)

        title = QLabel(f"NAS Clone Migration · {vm.name}")
        title.setObjectName("pageTitle")
        strategy_note = QLabel(
            "This is NAS Clone Migration, not live RAM migration. The source VM and source disks remain untouched; "
            "the target VM is imported from a NAS package with a regenerated UUID and MAC."
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

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.go_next)
        self.preflight_button = QPushButton("Run Preflight")
        self.preflight_button.clicked.connect(self.run_preflight)
        self.package_button = QPushButton("Start Migration")
        self.package_button.setObjectName("primaryButton")
        self.package_button.setEnabled(False)
        self.package_button.clicked.connect(self.start_migration)
        close_button = QPushButton("Close")
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
        self._on_transfer_mode_changed()

        self._set_step(0)
        self.refresh_hosts()

    def _on_transfer_mode_changed(self, *_args) -> None:
        nas_selected = str(self.transfer_mode.currentData() or "") == "nas"
        self.nas_path.setEnabled(nas_selected)
        if hasattr(self, "nas_browse_button"):
            self.nas_browse_button.setEnabled(nas_selected)
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
        state_chip = QLabel(self.vm.state.upper() if self.vm.state else "UNKNOWN")
        state_chip.setObjectName("statusChipBad" if running else "statusChipOk")
        must_off = QLabel("Must be shut off")
        must_off.setObjectName("statusChipWarn")
        head.addWidget(name)
        head.addWidget(state_chip)
        head.addWidget(must_off)
        head.addStretch()
        card_layout.addLayout(head)
        detail = QLabel(
            f"Display: {getattr(self.vm, 'graphics', '') or 'unknown'} · "
            f"RAM: {getattr(self.vm, 'ram_mib', 0) or '?'} MiB · vCPUs: {getattr(self.vm, 'vcpus', 0) or '?'} · "
            f"Lab: {getattr(self.vm, 'lab_id', '') or '-'}"
        )
        detail.setObjectName("mutedLabel")
        card_layout.addWidget(detail)
        layout.addWidget(card)
        if running:
            layout.addWidget(self._wizard_callout(
                "Running VM migration is blocked for NAS Clone Migration. Shut the VM down with ACPI Shutdown first.",
                "calloutDanger",
            ))
        form = QFormLayout()
        form.addRow("Hub URL", self.registry_url)
        form.addRow("Source host ID", self.source_host_id)
        layout.addLayout(form)
        layout.addStretch()
        return page

    def _page_target_host(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        refresh_hosts = QPushButton("Refresh Hosts")
        refresh_hosts.clicked.connect(self.refresh_hosts)
        host_row = QHBoxLayout()
        host_row.addWidget(self.target_host, 1)
        host_row.addWidget(refresh_hosts)
        form = QFormLayout()
        form.addRow("Target host", host_row)
        layout.addLayout(form)
        self.target_summary = QLabel("Select a target host from the Hub.")
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
        self.nas_browse_button = QPushButton("Browse")
        self.nas_browse_button.clicked.connect(self.pick_nas_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.nas_path, 1)
        path_row.addWidget(self.nas_browse_button)
        form = QFormLayout()
        form.addRow("Target VM name", self.target_name)
        form.addRow("Transfer mode", self.transfer_mode)
        form.addRow("NAS staging path", path_row)
        form.addRow("", self.include_iso)
        form.addRow("", self.include_snapshots)
        form.addRow("", self.allow_paused)
        form.addRow("", self.start_after_import)
        layout.addLayout(form)
        layout.addWidget(self._wizard_callout("Source VM and source disks will not be deleted.", "calloutOk"))
        layout.addStretch()
        return page

    def _page_preflight(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        hint = QLabel("Run Preflight to validate the source VM, target host, NAS staging, and target name before starting.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.result_view, 1)
        return page

    def _page_progress(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        self.migration_id_label = QLabel("Migration not started yet.")
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
        self.refresh_status_button = QPushButton("Refresh Status")
        self.refresh_status_button.clicked.connect(self.refresh_migration_status)
        self.refresh_status_button.setEnabled(False)
        copy_id = QPushButton("Copy Migration ID")
        copy_id.clicked.connect(self.copy_migration_id)
        copy_logs = QPushButton("Copy Logs")
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
        copy_summary = QPushButton("Copy Summary")
        copy_summary.clicked.connect(self.copy_summary)
        self.back_to_preflight_button = QPushButton("Back to Preflight")
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

    def _target_ready(self) -> bool:
        target = self._selected_target()
        return bool(
            target
            and target.get("status") == "online"
            and target.get("kvm_ok")
            and target.get("libvirt_ok")
            and str(target.get("host_id") or "") != self.source_host_id.text().strip()
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
            self.next_button.setEnabled(not self._vm_running() and not self.allow_paused.isChecked() or self.allow_paused.isChecked() and not self._vm_running())
            self.next_button.setEnabled(not self._vm_running())
        elif step == 1:
            self.next_button.setEnabled(self._target_ready())
        elif step == 2:
            nas_ok = str(self.transfer_mode.currentData() or "") != "nas" or bool(self.nas_path.text().strip())
            self.next_button.setEnabled(bool(self.target_name.text().strip()) and nas_ok)

    def go_next(self) -> None:
        step = self.current_step()
        if step == 0 and self._vm_running():
            self.error_label.setText("Running VM migration is blocked for NAS Clone Migration.")
            return
        if step == 1 and not self._target_ready():
            self.error_label.setText("Select an online, KVM/libvirt-ready target host that differs from the source host.")
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
                "Hub not reachable. Set HYPERGERY_HUB_URL or start docker compose in docker/.\n"
                f"{exc}"
            )
            if hasattr(self, "target_summary"):
                self.target_summary.setText("Hub not reachable — no target hosts available.")
            self.invalidate_preflight()
            return
        self.hosts = hosts
        for host in hosts:
            host_id = str(host.get("host_id") or "")
            status = str(host.get("status") or "offline")
            label = f"{host_id} ({status})"
            if host.get("hostname"):
                label += f" - {host.get('hostname')}"
            self.target_host.addItem(label, host_id)
            index = self.target_host.count() - 1
            self.target_host.model().item(index).setEnabled(status == "online")
        if not hosts:
            self.result_view.setPlainText("Hub returned no hosts. Start agents on source and target hosts first.")
        else:
            self.result_view.setPlainText(self._format_hosts(hosts))
        self._render_target_summary()
        self.invalidate_preflight()

    def _render_target_summary(self) -> None:
        if not hasattr(self, "target_summary"):
            return
        target = self._selected_target()
        if not target:
            self.target_summary.setText("Select a target host from the Hub.")
            return
        status = str(target.get("status") or "offline")
        lines = [
            f"Status: {status.upper()}" ,
            f"KVM: {'OK' if target.get('kvm_ok') else 'FAIL'} · libvirt: {'OK' if target.get('libvirt_ok') else 'FAIL'}",
            f"RAM free: {target.get('ram_free_mib', 0)} / {target.get('ram_total_mib', 0)} MiB · Disk free: {target.get('disk_free_mib', 0)} MiB",
            f"Active VMs: {len(target.get('active_vms') or [])} · Last heartbeat: {target.get('last_seen') or 'unknown'}",
        ]
        if status != "online":
            lines.append("Offline target hosts block the migration.")
        if str(target.get("host_id") or "") == self.source_host_id.text().strip():
            lines.append("Target host must differ from the source host.")
        self.target_summary.setText("\n".join(lines))

    def pick_nas_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select NAS staging directory", self.nas_path.text(), FILE_DIALOG_OPTIONS)
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
            self.error_label.setText("Target VM name is required.")
            return
        if not values["source_host_id"]:
            self.error_label.setText("Source host ID is required.")
            return
        if not values["target_host_id"]:
            self.error_label.setText("Select an online target host from the Hub.")
            return
        if values["transfer"] == "nas" and not values["nas_path"]:
            self.error_label.setText("NAS staging path is required for shared NAS transfer.")
            return
        if values["target_host_id"] == values["source_host_id"]:
            self.error_label.setText("Target host must differ from the source host.")
            self.package_button.setEnabled(False)
            return
        target = self._selected_target()
        if not target or target.get("status") != "online":
            self.error_label.setText("Selected target host is offline.")
            self.package_button.setEnabled(False)
            return
        if not target.get("kvm_ok") or not target.get("libvirt_ok"):
            self.error_label.setText("Selected target host is not ready: KVM/libvirt check failed.")
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

    def _format_preflight(self, result: dict) -> str:
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        assets = result.get("assets", [])
        transfer = str(self.transfer_mode.currentData() or "nas")
        transfer_line = (
            "Transfer: hub (package uploaded through the Hub, removed from the Hub after import)"
            if transfer == "hub"
            else "Transfer: shared NAS path (must be visible at the same path on both hosts)"
        )
        lines = [
            f"Status: {'OK' if result.get('ok') else 'Blocked'}",
            f"Strategy: {result.get('strategy', 'offline-copy')} (NAS Clone Migration)",
            transfer_line,
            f"Source will be deleted: {result.get('source_will_be_deleted')}",
            "Target identity: UUID and MAC will be regenerated on import.",
            f"Estimated package size: {result.get('estimated_size_bytes', 0)} bytes",
            "",
            "Errors:",
            *(f"- {item}" for item in errors),
            "" if errors else "- none",
            "",
            "Warnings:",
            *(f"- {item}" for item in warnings),
            "" if warnings else "- none",
            "",
            "Assets:",
        ]
        if assets:
            lines.extend(
                f"- {asset.get('type')} {asset.get('path')} ({asset.get('size_bytes', 0)} bytes)"
                for asset in assets
            )
        else:
            lines.append("- none")
        return "\n".join(lines)

    def _format_hosts(self, hosts: list[dict]) -> str:
        lines = ["Remote hosts:"]
        for host in hosts:
            active = ", ".join(host.get("active_vms") or []) or "none"
            lines.append(
                f"- {host.get('host_id')} status={host.get('status')} last_seen={host.get('last_seen')} "
                f"ram={host.get('ram_free_mib')}/{host.get('ram_total_mib')} MiB "
                f"disk_free={host.get('disk_free_mib')} MiB "
                f"kvm={host.get('kvm_ok')} libvirt={host.get('libvirt_ok')} active_vms={active}"
            )
        return "\n".join(lines)

    # ---------- migration ----------

    def start_migration(self) -> None:
        if not self.preflight_result or not self.preflight_result.get("ok"):
            self.error_label.setText("Run a successful preflight before starting migration.")
            return
        values = self.values()
        self.error_label.clear()
        self.package_button.setEnabled(False)
        self._set_step(4)
        self.migration_id_label.setText("Starting migration…")
        if values["transfer"] == "hub":
            progress_intro = (
                f"Packaging {values['vm_name']} locally and uploading it through the Hub for {values['target_host_id']}.\n"
                "The Hub copy is temporary and is removed after the target imports it.\n"
                "The source VM and source disks remain untouched."
            )
        else:
            progress_intro = (
                f"Packaging {values['vm_name']} into NAS staging and queueing import on {values['target_host_id']}.\n"
                "The source VM and source disks remain untouched."
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
            self.migration_id_label.setText(f"Migration ID: {migration_id}")
            self.progress_log.append(
                f"\nMigration queued.\nmigration_id: {migration_id}\n"
                f"package: {self.last_result.get('package_dir', '')}\n"
                f"target command: {self.last_result.get('command_id', '')}\n"
                "Use Refresh Status to poll the Hub until the target agent finishes the import."
            )
            self.refresh_status_button.setEnabled(True)
            self._render_progress_states("uploaded")

        def failed() -> None:
            self.last_status = {"status": "failed", "error": job.error_message}
            self.progress_log.append(f"\nMigration failed to start: {job.error_message}")
            self._render_progress_states("failed")
            self._show_result_failure(job.error_message)

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.start()

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
            self.error_label.setText("No migration started yet.")
            return
        url = self.registry_url.text().strip()

        def fetch() -> dict:
            from ..registry import RegistryClient

            return RegistryClient(url).migration(migration_id)

        from .workers import BackendJob

        job = BackendJob("migration status", fetch)
        self._jobs.append(job)

        def succeeded() -> None:
            record = job.result or {}
            self.last_status = record
            status = str(record.get("status") or "unknown")
            self.progress_log.append(f"status: {status}")
            self._render_progress_states(status if status in self.MIGRATION_STATES or status == "failed" else "created")
            if status == "done":
                self._show_result_success(record)
            elif status == "failed":
                self._show_result_failure(str(record.get("error") or "see migration log"))

        def failed() -> None:
            self.progress_log.append(f"status check failed: {job.error_message}")

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.start()

    # ---------- result ----------

    def _show_result_success(self, record: dict) -> None:
        migration_id = str((self.last_result or {}).get("migration_id") or record.get("migration_id") or "")
        package = str((self.last_result or {}).get("package_dir") or "")
        self.result_title.setText("Migration completed")
        self.result_body.setText(
            f"Migration ID: {migration_id}\n"
            f"Package path: {package or 'on NAS staging'} (conserved)\n"
            f"Target VM: {self.target_name.text().strip()} imported with regenerated UUID and MAC.\n"
            f"Target started: {'yes' if self.start_after_import.isChecked() else 'no'}"
        )
        self.result_callout.setText("Source VM remains untouched · UUID & MAC regenerated on target.")
        self.result_callout.setObjectName("calloutOk")
        self.result_callout.style().unpolish(self.result_callout)
        self.result_callout.style().polish(self.result_callout)
        self._set_step(5)

    def _show_result_failure(self, error: str) -> None:
        self.result_title.setText("Migration failed")
        last = str((self.last_status or {}).get("status") or "failed")
        self.result_body.setText(f"Last status: {last}\nError: {error}")
        self.result_callout.setText("The source VM and source disks were not modified. Review the error and retry from Preflight.")
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
        self._copy_text(str((self.last_result or {}).get("migration_id") or ""), "No migration ID yet. Start a migration first.")

    def copy_progress_logs(self) -> None:
        self._copy_text(self.progress_log.toPlainText(), "No migration logs yet.")

    def copy_summary(self) -> None:
        summary = f"{self.result_title.text()}\n{self.result_body.text()}\n{self.result_callout.text()}".strip()
        self._copy_text(summary if self.result_title.text() else "", "No result to copy yet.")


class SnapshotDialog(QDialog):
    def __init__(self, backend: HyperGeryBackend, vm_name: str, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.backend = backend
        self.vm_name = vm_name
        self.main_window = parent
        self.setWindowTitle(f"Snapshots: {vm_name}")
        title = QLabel(vm_name)
        title.setObjectName("sectionTitle")
        self.snapshots = QListWidget()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        create = QPushButton("Create")
        create.clicked.connect(self.create_snapshot)
        revert = QPushButton("Revert")
        revert.clicked.connect(self.revert_snapshot)
        delete = QPushButton("Delete")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self.delete_snapshot)
        close = QPushButton("Close")
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
            raise HyperGeryError("Select a snapshot first.")
        return item.text()

    def refresh(self) -> None:
        self.snapshots.clear()
        try:
            for snapshot in self.backend.list_snapshots(self.vm_name):
                self.snapshots.addItem(snapshot)
        except Exception as exc:
            self.main_window.show_error(str(exc))

    def create_snapshot(self) -> None:
        name, ok = QInputDialog.getText(self, "Create snapshot", "Snapshot name:")
        if not ok or not name.strip():
            return
        description, _ok = QInputDialog.getText(self, "Create snapshot", "Description:")
        if QMessageBox.question(self, "Create snapshot", f"Create snapshot {name.strip()} for {self.vm_name}?") != QMessageBox.StandardButton.Yes:
            return
        self.main_window.run_operation(
            f"Creating snapshot {name.strip()}",
            lambda: self.backend.create_snapshot(self.vm_name, name.strip(), description),
            on_success=lambda _result: self.refresh(),
        )

    def revert_snapshot(self) -> None:
        try:
            snapshot = self.selected_snapshot()
        except HyperGeryError as exc:
            self.main_window.show_error(str(exc))
            return
        if (
            QMessageBox.question(
                self,
                "Revert snapshot",
                f"Revert {self.vm_name} to {snapshot}?\n\nCurrent guest disk state will move back to that snapshot.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.main_window.run_operation(
            f"Reverting {self.vm_name} to {snapshot}",
            lambda: self.backend.revert_snapshot(self.vm_name, snapshot),
            on_success=lambda _result: self.refresh(),
        )

    def delete_snapshot(self) -> None:
        try:
            snapshot = self.selected_snapshot()
        except HyperGeryError as exc:
            self.main_window.show_error(str(exc))
            return
        if QMessageBox.question(self, "Delete snapshot", f"Delete snapshot {snapshot} from {self.vm_name}?") != QMessageBox.StandardButton.Yes:
            return
        self.main_window.run_operation(
            f"Deleting snapshot {snapshot}",
            lambda: self.backend.delete_snapshot(self.vm_name, snapshot),
            on_success=lambda _result: self.refresh(),
        )


class NewVmTemplateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New VM Template")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.validate)
        form.addRow("Name:", self.name_edit)

        self.id_preview = QLabel()
        self.id_preview.setObjectName("mutedLabel")
        form.addRow("Template ID:", self.id_preview)

        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "other"])
        form.addRow("OS Type:", self.os_type)

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
        form.addRow("Disk:", self.disk_gb)

        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        form.addRow("Network:", self.network_mode)

        self.display_mode = QComboBox()
        self.display_mode.addItems(["spice", "vnc"])
        form.addRow("Display:", self.display_mode)

        self.notes_edit = QLineEdit()
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
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
            self.id_preview.setText("Invalid ID")
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
        self.setWindowTitle("New Lab Template")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.validate)
        form.addRow("Name:", self.name_edit)

        self.id_preview = QLabel()
        self.id_preview.setObjectName("mutedLabel")
        form.addRow("Template ID:", self.id_preview)

        self.desc_edit = QLineEdit()
        form.addRow("Description:", self.desc_edit)

        self.network_mode = QComboBox()
        self.network_mode.addItems(["nat", "isolated"])
        form.addRow("Network:", self.network_mode)

        self.notes_edit = QLineEdit()
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
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
            self.id_preview.setText("Invalid ID")
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
        self.setWindowTitle(f"Delete VM Template: {template_id}")
        title = QLabel(f"Delete VM template {template_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("This removes the template JSON file. No VMs or disks will be deleted.")
        warning.setWordWrap(True)
        self.confirm_id = QLineEdit()
        self.confirm_id.setPlaceholderText(template_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton("Delete Template", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_id.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Type template ID", self.confirm_id)
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
            self.error_label.setText("Type the exact template ID to confirm deletion.")
            return
        super().accept()


class DeleteLabTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        template_id = str(template.get("template_id", ""))
        self.setWindowTitle(f"Delete Lab Template: {template_id}")
        title = QLabel(f"Delete lab template {template_id}?")
        title.setObjectName("sectionTitle")
        warning = QLabel("This removes the template JSON file. No labs or VMs will be deleted.")
        warning.setWordWrap(True)
        self.confirm_id = QLineEdit()
        self.confirm_id.setPlaceholderText(template_id)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton("Delete Template", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        self.confirm_id.textChanged.connect(self.update_state)
        form = QFormLayout()
        form.addRow("Type template ID", self.confirm_id)
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
            self.error_label.setText("Type the exact template ID to confirm deletion.")
            return
        super().accept()


class CreateLabFromTemplateDialog(QDialog):
    def __init__(self, template: dict, existing_lab_ids: set[str], existing_subnets: set[str], parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.existing_lab_ids = existing_lab_ids
        self.existing_subnets = existing_subnets
        self.setWindowTitle(f"Create Lab from Template: {template.get('template_id', '')}")

        vms = template.get("vms", [])
        if vms:
            vm_names = ", ".join(str(v.get("name", "?")) for v in vms[:5])
            suffix = f" (+{len(vms) - 5} more)" if len(vms) > 5 else ""
            planned_text = f"Planned VMs ({len(vms)}): {vm_names}{suffix}"
        else:
            planned_text = "No VMs defined in this template."
        planned_label = QLabel(planned_text)
        planned_label.setObjectName("mutedLabel")
        planned_label.setWordWrap(True)

        caveat = QLabel(
            "VMs are not created automatically. "
            "After the lab is set up, create each VM manually or via a VM template."
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = buttons.addButton("Create Lab", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Template", QLabel(f"{template.get('name', '')} ({template.get('template_id', '')})"))
        form.addRow("New lab name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Network mode", self.network_mode)
        form.addRow("Preview", self.preview_label)
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
                    ("Lab ID", preview["lab_id"]),
                    ("Network", preview["network_id"]),
                    ("Bridge", preview["bridge_name"]),
                    ("Subnet", preview["subnet"]),
                )
            )
        else:
            self.preview_label.setText("Enter a valid lab name to preview network resources.")

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
        self.setTitle("Lab Identity")
        self.setSubTitle("Choose a name for the new lab instance.")
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
        form.addRow("Template", QLabel(f"{template.get('name', '')} ({template.get('template_id', '')})"))
        form.addRow("New lab name *", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Network mode", self.network_mode)
        form.addRow("Preview", self.preview_label)
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
            self.preview_label.setText(p["error"] or "Enter a valid lab name.")
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
        self.setTitle("ISO Mapping")
        self.setSubTitle(
            "Select a boot ISO for each VM that requires one. "
            "VMs with ISO Required = No can be created without a boot image."
        )
        vms = template.get("vms", [])
        self.vm_rows: list[dict] = []
        self.iso_edits: list[QLineEdit] = []

        self.table = QTableWidget(len(vms), 5)
        self.table.setHorizontalHeaderLabels(["ISO Path", "VM Name", "Role", "RAM MiB", "Required"])
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
            required_text = "Yes" if vm.get("iso_required", True) else "No"
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
            layout.addWidget(QLabel("This template has no planned VMs. The lab structure will be created."))
        else:
            apply_all_btn = QPushButton("Apply same ISO to all VMs…")
            apply_all_btn.clicked.connect(self._apply_all_iso)
            apply_all_row = QHBoxLayout()
            apply_all_row.addWidget(apply_all_btn)
            apply_all_row.addStretch()
            layout.addLayout(apply_all_row)
            layout.addWidget(self.table)
        layout.addWidget(self.status_label)

    def _apply_all_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ISO for all VMs", "", "ISO images (*.iso);;All files (*)", "", FILE_DIALOG_OPTIONS
        )
        if path:
            for edit in self.iso_edits:
                edit.setText(path)

    def _browse(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ISO", "", "ISO images (*.iso);;All files (*)", "", FILE_DIALOG_OPTIONS
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
            self.status_label.setText(f"ISO required for: {', '.join(missing)}")
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
        self.setTitle("Review")
        self.setSubTitle("Confirm the lab and VMs that will be created.")
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)

    def initializePage(self) -> None:
        vms = self.template.get("vms", [])
        iso_map = self.iso_page.iso_map()
        lines = [
            f"Template:    {self.template.get('name', '')} ({self.template.get('template_id', '')})",
            f"Lab name:    {self.identity_page.lab_name()}",
            f"Lab ID:      {self.identity_page.lab_id()}",
            f"Network:     {self.template.get('network_mode', 'nat')}",
            f"Description: {self.identity_page.lab_description()}",
            "",
            f"VMs to create ({len(vms)}):",
        ]
        for vm in vms:
            name = str(vm.get("name", ""))
            iso = iso_map.get(name, "")
            role = vm.get("role", "")
            role_str = f"  role={role}" if role else ""
            lines.append(
                f"  • {name}{role_str}  RAM={vm.get('ram_mib', '?')}MiB"
                f"  vCPUs={vm.get('vcpus', '?')}  Disk={vm.get('disk_gb', '?')}GB"
            )
            lines.append(f"    ISO: {iso or '(none)'}")
        if not vms:
            lines.append("  (no planned VMs — lab structure only)")
        lines += [
            "",
            "Click 'Create Lab' to start. VMs are created sequentially.",
            "If creation fails partway, already-created VMs will be removed.",
        ]
        self.summary.setPlainText("\n".join(lines))


class InstantiateLabTemplateWizard(QWizard):
    def __init__(self, template: dict, existing_lab_ids: set, existing_subnets: set, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Create Lab from Template: {template.get('template_id', '')}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.identity_page = _LabIdentityPage(template, existing_lab_ids, existing_subnets)
        self.iso_page = _IsoMappingPage(template)
        self.review_page = _InstantiateReviewPage(template, self.identity_page, self.iso_page)
        self.addPage(self.identity_page)
        self.addPage(self.iso_page)
        self.addPage(self.review_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Create Lab")
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
        self.setWindowTitle(f"Edit VM Template: {template.get('template_id', '')}")
        self.name_edit = QLineEdit(str(template.get("name", "")))
        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "other"])
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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Template ID", QLabel(str(template.get("template_id", ""))))
        form.addRow("Name", self.name_edit)
        form.addRow("OS type", self.os_type)
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Disk", self.disk)
        form.addRow("Network", self.network_mode)
        form.addRow("Display", self.display)
        form.addRow("Notes", self.notes_edit)
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
        self.setWindowTitle("Edit Planned VM" if existing else "Add Planned VM")
        self._original_name = str(existing.get("name", "")) if existing else ""
        self.name_edit = QLineEdit(self._original_name)
        self.name_edit.setPlaceholderText("server-01")
        self.role_edit = QLineEdit(str(existing.get("role", "")) if existing else "")
        self.role_edit.setPlaceholderText("server / client / router (optional)")
        self.vm_template_edit = QLineEdit(str(existing.get("template_id", "")) if existing else "")
        self.vm_template_edit.setPlaceholderText("ubuntu-base (optional VM template id)")
        self.os_type = QComboBox()
        self.os_type.addItems(["linux", "windows", "other"])
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
        self.iso_required = QCheckBox("ISO required at instantiation time")
        self.iso_required.setChecked(bool(existing.get("iso_required", True)) if existing else True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("VM name *", self.name_edit)
        form.addRow("Role", self.role_edit)
        form.addRow("VM template id", self.vm_template_edit)
        form.addRow("OS type", self.os_type)
        form.addRow("RAM", self.ram)
        form.addRow("vCPUs", self.vcpus)
        form.addRow("Disk", self.disk)
        form.addRow("Display", self.display)
        form.addRow("Notes", self.notes_edit)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.iso_required)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(480, 420)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.error_label.setText("VM name cannot be empty.")
            return
        import re as _re
        if not _re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_\-]{0,61}", name):
            self.error_label.setText("VM name must start with a letter/digit, only letters, digits, dashes, underscores.")
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

_VM_TABLE_COLS = ["Name", "Role", "OS", "RAM MiB", "vCPUs", "Disk GB", "Display", "ISO req."]


class EditLabTemplateDialog(QDialog):
    def __init__(self, template: dict, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.setWindowTitle(f"Edit Lab Template: {template.get('template_id', '')}")
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

        add_btn = QPushButton("Add VM…")
        edit_btn = QPushButton("Edit Selected…")
        remove_btn = QPushButton("Remove Selected")
        add_btn.clicked.connect(self._add_vm)
        edit_btn.clicked.connect(self._edit_vm)
        remove_btn.clicked.connect(self._remove_vm)
        vm_buttons = QHBoxLayout()
        vm_buttons.addWidget(add_btn)
        vm_buttons.addWidget(edit_btn)
        vm_buttons.addWidget(remove_btn)
        vm_buttons.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Template ID", QLabel(str(template.get("template_id", ""))))
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Network mode", self.network_mode)
        form.addRow("Notes", self.notes_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Planned VMs (double-click to edit):"))
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
            "Yes" if vm.get("iso_required", True) else "No",
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
            "Yes" if vm.get("iso_required", True) else "No",
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
            QMessageBox.warning(self, "Duplicate name", f"A planned VM named '{vm['name']}' already exists.")
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
                QMessageBox.warning(self, "Duplicate name", f"A planned VM named '{updated['name']}' already exists.")
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
        self.setWindowTitle("HyperGery Resource Overview")
        self.resize(760, 520)

        lines = ["HyperGery-managed resources\n"]
        lines.append(f"VMs ({len(vms)}):")
        for vm in vms:
            state = getattr(vm, "state", "?")
            lab = getattr(vm, "lab_id", "") or "default-lab"
            lines.append(f"  • {vm.name}  state={state}  lab={lab}")
        lines.append("")
        lines.append(f"Labs ({len(labs)}):")
        for lab in labs:
            vm_count = len(lab.get("vms", []))
            subnet = lab.get("subnet", "")
            lines.append(f"  • {lab.get('lab_id', '?')}  name={lab.get('name', '')}  vms={vm_count}  subnet={subnet}")
        lines.append("")
        lines.append(f"VM Templates ({len(vm_templates)}):")
        for tmpl in vm_templates:
            lines.append(f"  • {tmpl.get('template_id', '?')}  ({tmpl.get('os_type', '')}  {tmpl.get('ram_mib', '')} MiB)")
        lines.append("")
        lines.append(f"Lab Templates ({len(lab_templates)}):")
        for tmpl in lab_templates:
            vm_count = len(tmpl.get("vms", []))
            lines.append(f"  • {tmpl.get('template_id', '?')}  planned VMs={vm_count}")
        lines.append("")
        lines.append("To delete resources, use the Delete buttons in the main window.")
        lines.append("No resources are modified by this dialog.")

        text = QTextEdit("\n".join(lines))
        text.setReadOnly(True)
        text.setFont(QFont("monospace", 9))

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Overview of all HyperGery-managed resources (read-only):"))
        layout.addWidget(text)
        layout.addLayout(btn_row)
