from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..backend import HyperGeryBackend, HyperGeryError, VmSummary
from .dialogs import CloneDialog, DeleteConfirmationDialog, SettingsDialog, SnapshotDialog, VMWizard
from .styles import APP_DISPLAY_VERSION, APP_STYLESHEET, STATE_COLORS, details_block, format_mib, state_kind
from .workers import BackendJob


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.backend = HyperGeryBackend()
        self.vms: list[VmSummary] = []
        self.selected_vm: VmSummary | None = None
        self.jobs: list[BackendJob] = []
        self.setWindowTitle(f"HyperGery v{APP_DISPLAY_VERSION}")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_top_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        brand = QVBoxLayout()
        title = QLabel("HyperGery")
        title.setObjectName("brandTitle")
        subtitle = QLabel(f"v{APP_DISPLAY_VERSION}  KVM / QEMU / libvirt")
        subtitle.setObjectName("brandSubtle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.new_button = self._button("New VM", self.new_vm, primary=True)
        self.settings_button = self._button("Settings", self.settings_vm)
        self.start_button = self._button("Start", self.start_vm)
        self.shutdown_button = self._button("ACPI Shutdown", self.shutdown_vm)
        self.console_button = self._button("Console", self.open_console)
        self.snapshots_button = self._button("Snapshots", self.snapshots_vm)
        self.clone_button = self._button("Clone", self.clone_vm)
        self.refresh_button = self._button("Refresh", self.refresh_all)
        self.force_button = self._button("Force Off", self.force_off_vm, danger=True)
        self.delete_button = self._button("Delete", self.delete_vm, danger=True)
        for button in (
            self.new_button,
            self.settings_button,
            self.start_button,
            self.shutdown_button,
            self.console_button,
            self.snapshots_button,
            self.clone_button,
            self.refresh_button,
        ):
            layout.addWidget(button)
        layout.addStretch()
        layout.addWidget(self.force_button)
        layout.addWidget(self.delete_button)
        return bar

    def _button(self, text: str, callback: Callable[[], None], *, primary: bool = False, danger: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primaryButton")
        if danger:
            button.setObjectName("dangerButton")
        button.clicked.connect(callback)
        return button

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 10, 14)
        header = QHBoxLayout()
        title = QLabel("Virtual Machines")
        title.setObjectName("sectionTitle")
        self.vm_count_label = QLabel("No VMs")
        self.vm_count_label.setObjectName("mutedLabel")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.vm_count_label)
        layout.addLayout(header)

        self.vm_table = QTableWidget(0, 5)
        self.vm_table.setHorizontalHeaderLabels(["Name", "State", "Lab", "CPU", "RAM"])
        self.vm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vm_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.vm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vm_table.setAlternatingRowColors(True)
        self.vm_table.verticalHeader().setVisible(False)
        self.vm_table.horizontalHeader().setStretchLastSection(True)
        self.vm_table.setColumnWidth(0, 190)
        self.vm_table.setColumnWidth(1, 100)
        self.vm_table.setColumnWidth(2, 130)
        self.vm_table.setColumnWidth(3, 52)
        self.vm_table.itemSelectionChanged.connect(self.on_vm_selection_changed)
        layout.addWidget(self.vm_table, 1)

        labs_title = QLabel("Labs")
        labs_title.setObjectName("sectionTitle")
        layout.addWidget(labs_title)
        self.lab_table = QTableWidget(0, 3)
        self.lab_table.setHorizontalHeaderLabels(["Lab", "VMs", "Network"])
        self.lab_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lab_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_table.verticalHeader().setVisible(False)
        self.lab_table.horizontalHeader().setStretchLastSection(True)
        self.lab_table.setMaximumHeight(180)
        self.lab_table.setColumnWidth(0, 140)
        self.lab_table.setColumnWidth(1, 55)
        layout.addWidget(self.lab_table)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 14, 14, 14)
        self.selection_label = QLabel("No VM selected")
        self.selection_label.setObjectName("sectionTitle")
        layout.addWidget(self.selection_label)

        self.preflight_summary = QLabel("Preflight not run yet")
        self.preflight_summary.setObjectName("mutedLabel")
        self.preflight_table = QTableWidget(0, 3)
        self.preflight_table.setHorizontalHeaderLabels(["Status", "Detail", "Suggested command"])
        self.preflight_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preflight_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preflight_table.verticalHeader().setVisible(False)
        self.preflight_table.horizontalHeader().setStretchLastSection(True)
        self.preflight_table.setMaximumHeight(190)
        self.preflight_table.setColumnWidth(0, 95)
        self.preflight_table.setColumnWidth(1, 520)

        preflight_box = QFrame()
        preflight_box.setObjectName("panel")
        preflight_layout = QVBoxLayout(preflight_box)
        preflight_layout.addWidget(self.preflight_summary)
        preflight_layout.addWidget(self.preflight_table)
        layout.addWidget(preflight_box)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(self._build_detail_tabs())
        vertical.addWidget(self._build_logs_panel())
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 1)
        layout.addWidget(vertical, 1)
        return panel

    def _build_detail_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        self.detail_views: dict[str, QTextEdit] = {}
        for name in ("General", "System", "Display", "Storage", "Network", "Snapshots", "Logs"):
            text = QTextEdit()
            text.setReadOnly(True)
            text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.tabs.addTab(text, name)
            self.detail_views[name] = text
        return self.tabs

    def _build_logs_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        header = QHBoxLayout()
        title = QLabel("Activity Log")
        title.setObjectName("sectionTitle")
        refresh = QPushButton("Refresh Logs")
        refresh.clicked.connect(self.refresh_logs)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addLayout(header)
        layout.addWidget(self.activity_log, 1)
        return panel

    def set_busy(self, busy: bool, label: str = "Ready") -> None:
        for button in (
            self.new_button,
            self.settings_button,
            self.start_button,
            self.shutdown_button,
            self.console_button,
            self.snapshots_button,
            self.clone_button,
            self.refresh_button,
            self.force_button,
            self.delete_button,
        ):
            button.setEnabled(not busy)
        if busy:
            self.status.showMessage(label)
        else:
            self.status.showMessage("Ready")
            self.update_actions()

    def update_actions(self) -> None:
        vm = self.selected_vm
        has_vm = vm is not None
        state = vm.state.lower() if vm else ""
        running = "running" in state or "paused" in state
        shut_off = "shut" in state or "off" in state
        self.settings_button.setEnabled(has_vm and shut_off)
        self.start_button.setEnabled(has_vm and not running)
        self.shutdown_button.setEnabled(has_vm and running)
        self.console_button.setEnabled(has_vm and running)
        self.snapshots_button.setEnabled(has_vm)
        self.clone_button.setEnabled(has_vm and shut_off)
        self.force_button.setEnabled(has_vm and running)
        self.delete_button.setEnabled(has_vm and shut_off)

    def refresh_all(self) -> None:
        self.refresh_preflight()
        self.refresh_vms()
        self.refresh_labs()
        self.refresh_logs()
        self.render_selected()

    def refresh_preflight(self) -> None:
        self.preflight_table.setRowCount(0)
        counts = {"OK": 0, "Warning": 0, "Error": 0}
        try:
            items = self.backend.preflight()
        except Exception as exc:
            self.preflight_summary.setText(f"Preflight unavailable: {exc}")
            return
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
            row = self.preflight_table.rowCount()
            self.preflight_table.insertRow(row)
            self._set_table_item(self.preflight_table, row, 0, item.status, status=item.status)
            self._set_table_item(self.preflight_table, row, 1, f"{item.name}: {item.detail}")
            self._set_table_item(self.preflight_table, row, 2, item.fix)
        if counts["Error"]:
            self.preflight_summary.setText(f"{counts['Error']} error(s), {counts['Warning']} warning(s). VM operations may fail.")
            self.preflight_summary.setObjectName("errorLabel")
        elif counts["Warning"]:
            self.preflight_summary.setText(f"Ready with {counts['Warning']} warning(s). Review before creating production VMs.")
            self.preflight_summary.setObjectName("mutedLabel")
        else:
            self.preflight_summary.setText("All required host checks passed.")
            self.preflight_summary.setObjectName("okLabel")
        self.preflight_summary.style().unpolish(self.preflight_summary)
        self.preflight_summary.style().polish(self.preflight_summary)

    def refresh_vms(self) -> None:
        current = self.selected_vm.name if self.selected_vm else ""
        try:
            self.vms = self.backend.list_vms()
        except HyperGeryError as exc:
            self.vms = []
            self.show_error(str(exc))
        self.vm_table.setRowCount(0)
        selected_row = -1
        for vm in self.vms:
            row = self.vm_table.rowCount()
            self.vm_table.insertRow(row)
            self._set_table_item(self.vm_table, row, 0, vm.name)
            self._set_table_item(self.vm_table, row, 1, vm.state, status=vm.state)
            self._set_table_item(self.vm_table, row, 2, vm.lab_id or "unknown")
            self._set_table_item(self.vm_table, row, 3, str(vm.vcpus or "-"))
            self._set_table_item(self.vm_table, row, 4, format_mib(vm.ram_mib))
            if vm.name == current:
                selected_row = row
        if selected_row < 0 and self.vms:
            selected_row = 0
        if selected_row >= 0:
            self.vm_table.selectRow(selected_row)
        else:
            self.selected_vm = None
        running = sum(1 for vm in self.vms if state_kind(vm.state) == "running")
        suffix = "" if len(self.vms) == 1 else "s"
        self.vm_count_label.setText(f"{len(self.vms)} VM{suffix}, {running} running")
        self.update_actions()

    def refresh_labs(self) -> None:
        self.lab_table.setRowCount(0)
        try:
            labs = self.backend.load_labs()
        except Exception as exc:
            row = self.lab_table.rowCount()
            self.lab_table.insertRow(row)
            self._set_table_item(self.lab_table, row, 0, "unavailable")
            self._set_table_item(self.lab_table, row, 1, "-")
            self._set_table_item(self.lab_table, row, 2, str(exc))
            return
        for manifest in labs:
            row = self.lab_table.rowCount()
            self.lab_table.insertRow(row)
            self._set_table_item(self.lab_table, row, 0, manifest.get("lab_id", "unknown"))
            self._set_table_item(self.lab_table, row, 1, str(len(manifest.get("vms", []))))
            self._set_table_item(self.lab_table, row, 2, manifest.get("network_id", ""))

    def refresh_logs(self) -> None:
        try:
            logs = self.backend.recent_logs()
        except Exception as exc:
            logs = f"Logs unavailable: {exc}"
        self.activity_log.setPlainText(logs)
        self.activity_log.moveCursor(QTextCursor.MoveOperation.End)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, text: str, *, status: str = "") -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if status:
            item.setForeground(QColor(STATE_COLORS.get(state_kind(status), "#c7d0dd")))
        table.setItem(row, column, item)

    def on_vm_selection_changed(self) -> None:
        indexes = self.vm_table.selectionModel().selectedRows()
        if not indexes:
            self.selected_vm = None
        else:
            row = indexes[0].row()
            self.selected_vm = self.vms[row] if 0 <= row < len(self.vms) else None
        self.render_selected()
        self.update_actions()

    def render_selected(self) -> None:
        vm = self.selected_vm
        if vm is None:
            self.selection_label.setText("No VM selected")
            empty = "No VM selected.\n\nCreate a VM or select one from the list."
            for view in self.detail_views.values():
                view.setPlainText(empty)
            return
        self.selection_label.setText(f"{vm.name}  -  {vm.state}  -  {vm.lab_id or 'unknown lab'}")
        self.detail_views["General"].setPlainText(
            details_block(
                ("Name", vm.name),
                ("State", vm.state),
                ("Lab", vm.lab_id or "unknown"),
                ("Libvirt URI", "qemu:///system"),
            )
        )
        self.detail_views["System"].setPlainText(details_block(("RAM", format_mib(vm.ram_mib)), ("vCPUs", str(vm.vcpus or "unknown"))))
        self.detail_views["Display"].setPlainText(
            details_block(("Graphics", vm.graphics or "unknown"), ("Console", "virt-viewer or remote-viewer"))
        )
        self.detail_views["Storage"].setPlainText(
            details_block(
                ("Disk path", vm.disk_path or "unknown"),
                ("Virtual size", vm.disk_virtual or "unknown"),
                ("Actual size", vm.disk_actual or "unknown"),
                ("Boot ISO", vm.iso_path or "none"),
            )
        )
        self.detail_views["Network"].setPlainText(details_block(("Network", vm.network or "unknown"), ("Lab", vm.lab_id or "unknown")))
        try:
            snapshots = self.backend.list_snapshots(vm.name)
            body = "\n".join(f"- {snapshot}" for snapshot in snapshots) if snapshots else "No snapshots."
        except Exception as exc:
            body = f"Snapshot status unavailable:\n{exc}"
        self.detail_views["Snapshots"].setPlainText(body)
        self.detail_views["Logs"].setPlainText(self.backend.recent_logs(80))

    def selected_name(self) -> str:
        if self.selected_vm is None:
            raise HyperGeryError("Select a VM first.")
        return self.selected_vm.name

    def show_error(self, message: str) -> None:
        self.status.showMessage(message)
        QMessageBox.critical(self, "HyperGery", message)
        self.refresh_logs()

    def run_operation(self, label: str, fn: Callable[[], Any], *, on_success: Callable[[Any], None] | None = None) -> None:
        self.set_busy(True, label)
        job = BackendJob(label, fn)
        self.jobs.append(job)

        def succeeded(result: Any) -> None:
            if on_success:
                on_success(result)
            self.refresh_all()
            self.status.showMessage("Ready")

        def failed(message: str) -> None:
            self.show_error(message)
            self.status.showMessage("Ready")

        def finished() -> None:
            if job in self.jobs:
                self.jobs.remove(job)
            self.set_busy(False)
            job.deleteLater()

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.finished.connect(finished)
        job.start()

    def new_vm(self) -> None:
        wizard = VMWizard(self)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        if (
            QMessageBox.question(
                self,
                "Create VM",
                (
                    f"Create {values['name']}?\n\n"
                    f"ISO: {values['iso_path']}\n"
                    f"RAM: {values['ram_mib']} MiB\n"
                    f"vCPUs: {values['vcpus']}\n"
                    f"Disk: {values['disk_gb']} GiB\n"
                    f"Network: {values['network_mode']}\n"
                    f"Lab: {values['lab_id']}"
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.run_operation(f"Creating {values['name']}", lambda: self.backend.create_vm(**values))

    def settings_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        dialog = SettingsDialog(self.selected_vm, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if QMessageBox.question(self, "Save Settings", f"Apply settings to {self.selected_vm.name}?") != QMessageBox.StandardButton.Yes:
            return
        self.run_operation(f"Saving settings for {self.selected_vm.name}", lambda: self.backend.update_settings(**values))

    def start_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Starting {name}", lambda: self.backend.start_vm(name))

    def shutdown_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Requesting ACPI shutdown for {name}", lambda: self.backend.shutdown_vm(name))

    def force_off_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        if (
            QMessageBox.warning(
                self,
                "Force Off",
                f"Force power off {name}?\n\nThis is equivalent to pulling power and can corrupt guest data.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.run_operation(f"Forcing off {name}", lambda: self.backend.force_off_vm(name))

    def open_console(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Opening console for {name}", lambda: self.backend.open_console(name))

    def snapshots_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        SnapshotDialog(self.backend, self.selected_vm.name, self).exec()

    def clone_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        dialog = CloneDialog(self.selected_vm.name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        clone_name = dialog.clone_name()
        if QMessageBox.question(self, "Clone VM", f"Create clone {clone_name} from {self.selected_vm.name}?") != QMessageBox.StandardButton.Yes:
            return
        source = self.selected_vm.name
        self.run_operation(f"Cloning {source}", lambda: self.backend.clone_vm(source, clone_name))

    def delete_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        vm = self.selected_vm
        dialog = DeleteConfirmationDialog(vm, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.run_operation(f"Deleting {vm.name}", lambda: self.backend.delete_vm(vm.name, delete_disks=dialog.delete_disks()))
