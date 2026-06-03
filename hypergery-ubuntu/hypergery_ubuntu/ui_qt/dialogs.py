from __future__ import annotations

import html
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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..backend import HyperGeryBackend, HyperGeryError, VmSummary
from ..templates import normalize_template_id
from .lab_helpers import build_lab_preview
from .styles import details_block

if TYPE_CHECKING:
    from .main_window import MainWindow


FILE_DIALOG_OPTIONS = QFileDialog.Option.DontUseNativeDialog


class IdentityPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
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
            "",
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
    def __init__(self, default_lab_id: str = "default-lab") -> None:
        super().__init__()
        self.setTitle("Storage & Network")
        self.setSubTitle("Choose disk location, lab network and console type.")
        self.disk_dir = QLineEdit()
        self.disk_dir.setPlaceholderText("Default HyperGery VM directory")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.pick_dir)
        self.network = QComboBox()
        self.network.addItems(["nat", "isolated"])
        self.display = QComboBox()
        self.display.addItems(["spice", "vnc"])
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
        self.identity_page = IdentityPage()
        self.resources_page = ResourcesPage()
        self.integration_page = IntegrationPage(default_lab_id)
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
