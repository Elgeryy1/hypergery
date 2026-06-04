from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..backend import HyperGeryBackend, HyperGeryError, VmSummary, now_iso
from ..labs import LabStore
from ..templates import TemplateStore
from .dialogs import (
    CleanupPreviewDialog,
    CloneDialog,
    DeleteConfirmationDialog,
    DeleteLabDialog,
    DeleteLabTemplateDialog,
    DeleteVmTemplateDialog,
    DuplicateLabDialog,
    EditLabTemplateDialog,
    EditVmTemplateDialog,
    FILE_DIALOG_OPTIONS,
    InstantiateLabTemplateWizard,
    NewLabDialog,
    NewLabTemplateDialog,
    NewVmTemplateDialog,
    RenameLabDialog,
    SettingsDialog,
    SnapshotDialog,
    VMWizard,
)
from .lab_helpers import build_lab_topology, filter_vms_for_lab, vm_count_for_lab
from .topology import LabTopologyWidget
from .styles import (
    APP_DISPLAY_VERSION,
    APP_STYLESHEET,
    STATE_BACKGROUNDS,
    STATE_COLORS,
    STATE_LABELS,
    details_block,
    format_mib,
    state_kind,
)
from .workers import BackendJob


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.backend = HyperGeryBackend()
        self.template_store = TemplateStore(self.backend.data_dir, backend=self.backend, lab_store=self.lab_store())
        self.all_vms: list[VmSummary] = []
        self.vms: list[VmSummary] = []
        self.selected_vm: VmSummary | None = None
        self.labs: list[dict[str, Any]] = []
        self.selected_lab: dict[str, Any] | None = None
        self.vm_templates: list[dict] = []
        self.lab_templates: list[dict] = []
        self.selected_vm_template: dict | None = None
        self.selected_lab_template: dict | None = None
        self.jobs: list[BackendJob] = []
        self.completed_jobs: list[BackendJob] = []
        self.setWindowTitle(f"HyperGery v{APP_DISPLAY_VERSION}")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        QTimer.singleShot(0, self.refresh_all)

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
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)
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
        self.overview_button = self._button("Resources…", self.show_cleanup_preview)
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
        layout.addWidget(self.overview_button)
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
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        
        self.main_tabs = QTabWidget()
        panel_layout.addWidget(self.main_tabs)

        instances_tab = QWidget()
        layout = QVBoxLayout(instances_tab)
        layout.setContentsMargins(18, 18, 12, 18)
        layout.setSpacing(12)
        
        header = QHBoxLayout()
        title = QLabel("Virtual Machines")
        title.setObjectName("sectionTitle")
        self.vm_count_label = QLabel("No VMs")
        self.vm_count_label.setObjectName("mutedLabel")
        self.vm_filter = QComboBox()
        self.vm_filter.addItems(["All VMs", "Selected Lab"])
        self.vm_filter.currentIndexChanged.connect(self.on_vm_filter_changed)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.vm_filter)
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
        self.vm_stack = QStackedWidget()
        self.vm_stack.addWidget(self.vm_table)
        self.vm_stack.addWidget(self._build_vm_empty_state())
        layout.addWidget(self.vm_stack, 1)

        labs_header = QHBoxLayout()
        labs_title = QLabel("Labs")
        labs_title.setObjectName("sectionTitle")
        self.refresh_labs_button = self._button("Refresh Labs", self.refresh_labs)
        labs_header.addWidget(labs_title)
        labs_header.addStretch()
        labs_header.addWidget(self.refresh_labs_button)
        layout.addLayout(labs_header)
        self.lab_table = QTableWidget(0, 6)
        self.lab_table.setHorizontalHeaderLabels(["Name", "Lab ID", "Mode", "Subnet", "Bridge", "VMs"])
        self.lab_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lab_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lab_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_table.setAlternatingRowColors(True)
        self.lab_table.verticalHeader().setVisible(False)
        self.lab_table.horizontalHeader().setStretchLastSection(True)
        self.lab_table.setMaximumHeight(230)
        self.lab_table.setColumnWidth(0, 150)
        self.lab_table.setColumnWidth(1, 150)
        self.lab_table.setColumnWidth(2, 80)
        self.lab_table.setColumnWidth(3, 130)
        self.lab_table.setColumnWidth(4, 110)
        self.lab_table.itemSelectionChanged.connect(self.on_lab_selection_changed)
        layout.addWidget(self.lab_table)

        lab_actions = QGridLayout()
        lab_actions.setHorizontalSpacing(8)
        lab_actions.setVerticalSpacing(8)
        self.new_lab_button = self._button("New Lab", self.new_lab, primary=True)
        self.rename_lab_button = self._button("Rename Lab", self.rename_lab)
        self.delete_lab_button = self._button("Delete Lab", self.delete_lab, danger=True)
        self.duplicate_lab_button = self._button("Duplicate Lab", self.duplicate_lab)
        self.export_lab_button = self._button("Export Lab", self.export_lab)
        self.import_lab_button = self._button("Import Lab", self.import_lab)
        lab_actions.addWidget(self.new_lab_button, 0, 0)
        lab_actions.addWidget(self.rename_lab_button, 0, 1)
        lab_actions.addWidget(self.delete_lab_button, 1, 0)
        lab_actions.addWidget(self.duplicate_lab_button, 1, 1)
        lab_actions.addWidget(self.export_lab_button, 2, 0)
        lab_actions.addWidget(self.import_lab_button, 2, 1)
        layout.addLayout(lab_actions)

        self.main_tabs.addTab(instances_tab, "Instances")

        templates_tab = QWidget()
        templates_layout = QVBoxLayout(templates_tab)
        templates_layout.setContentsMargins(18, 18, 12, 18)
        templates_layout.setSpacing(12)

        self.templates_tabs = QTabWidget()
        templates_layout.addWidget(self.templates_tabs)

        # --- VM Templates Tab ---
        vm_templates_tab = QWidget()
        vm_templates_layout = QVBoxLayout(vm_templates_tab)
        vm_templates_layout.setContentsMargins(8, 8, 8, 8)
        vm_templates_layout.setSpacing(8)

        self.vm_template_table = QTableWidget(0, 8)
        self.vm_template_table.setHorizontalHeaderLabels(["Name", "ID", "OS", "RAM", "vCPUs", "Disk", "Net", "Display"])
        self.vm_template_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vm_template_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.vm_template_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vm_template_table.setAlternatingRowColors(True)
        self.vm_template_table.verticalHeader().setVisible(False)
        self.vm_template_table.horizontalHeader().setStretchLastSection(True)
        self.vm_template_table.itemSelectionChanged.connect(self.on_vm_template_selection_changed)
        vm_templates_layout.addWidget(self.vm_template_table)

        vm_template_actions = QGridLayout()
        vm_template_actions.setHorizontalSpacing(8)
        vm_template_actions.setVerticalSpacing(8)
        self.new_vm_template_button = self._button("New VM Template", self.new_vm_template, primary=True)
        self.delete_vm_template_button = self._button("Delete", self.delete_vm_template, danger=True)
        self.edit_vm_template_button = self._button("Edit", self.edit_vm_template)
        self.edit_vm_template_button.setEnabled(False)
        self.export_vm_template_button = self._button("Export", self.export_vm_template)
        self.import_vm_template_button = self._button("Import", self.import_vm_template)
        self.refresh_vm_templates_button = self._button("Refresh", self.refresh_templates)
        self.create_vm_from_template_button = self._button("Create VM from Template", self.create_vm_from_template, primary=True)
        self.create_vm_from_template_button.setEnabled(False)

        vm_template_actions.addWidget(self.new_vm_template_button, 0, 0)
        vm_template_actions.addWidget(self.import_vm_template_button, 0, 1)
        vm_template_actions.addWidget(self.refresh_vm_templates_button, 0, 2)
        vm_template_actions.addWidget(self.delete_vm_template_button, 1, 0)
        vm_template_actions.addWidget(self.edit_vm_template_button, 1, 1)
        vm_template_actions.addWidget(self.export_vm_template_button, 1, 2)
        vm_template_actions.addWidget(self.create_vm_from_template_button, 2, 0, 1, 3)

        vm_templates_layout.addLayout(vm_template_actions)

        self.vm_template_detail = QTextEdit()
        self.vm_template_detail.setReadOnly(True)
        self.vm_template_detail.setPlaceholderText("Select a VM template to see details.")
        self.vm_template_detail.setMaximumHeight(120)
        vm_templates_layout.addWidget(self.vm_template_detail)

        self.templates_tabs.addTab(vm_templates_tab, "VM Templates")

        # --- Lab Templates Tab ---
        lab_templates_tab = QWidget()
        lab_templates_layout = QVBoxLayout(lab_templates_tab)
        lab_templates_layout.setContentsMargins(8, 8, 8, 8)
        lab_templates_layout.setSpacing(8)

        self.lab_template_table = QTableWidget(0, 5)
        self.lab_template_table.setHorizontalHeaderLabels(["Name", "ID", "Net", "VMs", "Desc/Notes"])
        self.lab_template_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lab_template_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lab_template_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_template_table.setAlternatingRowColors(True)
        self.lab_template_table.verticalHeader().setVisible(False)
        self.lab_template_table.horizontalHeader().setStretchLastSection(True)
        self.lab_template_table.itemSelectionChanged.connect(self.on_lab_template_selection_changed)
        lab_templates_layout.addWidget(self.lab_template_table)

        lab_template_actions = QGridLayout()
        lab_template_actions.setHorizontalSpacing(8)
        lab_template_actions.setVerticalSpacing(8)
        self.new_lab_template_button = self._button("New Lab Template", self.new_lab_template, primary=True)
        self.delete_lab_template_button = self._button("Delete", self.delete_lab_template, danger=True)
        self.edit_lab_template_button = self._button("Edit", self.edit_lab_template)
        self.edit_lab_template_button.setEnabled(False)
        self.export_lab_template_button = self._button("Export", self.export_action_lab_template)
        self.import_lab_template_button = self._button("Import", self.import_action_lab_template)
        self.refresh_lab_templates_button = self._button("Refresh", self.refresh_templates)
        self.create_lab_from_template_button = self._button("Create Lab from Template", self.create_lab_from_template, primary=True)
        self.create_lab_from_template_button.setEnabled(False)

        lab_template_actions.addWidget(self.new_lab_template_button, 0, 0)
        lab_template_actions.addWidget(self.import_lab_template_button, 0, 1)
        lab_template_actions.addWidget(self.refresh_lab_templates_button, 0, 2)
        lab_template_actions.addWidget(self.delete_lab_template_button, 1, 0)
        lab_template_actions.addWidget(self.edit_lab_template_button, 1, 1)
        lab_template_actions.addWidget(self.export_lab_template_button, 1, 2)
        lab_template_actions.addWidget(self.create_lab_from_template_button, 2, 0, 1, 3)

        lab_templates_layout.addLayout(lab_template_actions)

        self.lab_template_detail = QTextEdit()
        self.lab_template_detail.setReadOnly(True)
        self.lab_template_detail.setPlaceholderText("Select a lab template to see details.")
        self.lab_template_detail.setMaximumHeight(120)
        lab_templates_layout.addWidget(self.lab_template_detail)

        self.templates_tabs.addTab(lab_templates_tab, "Lab Templates")

        self.main_tabs.addTab(templates_tab, "Templates")
        
        return panel

    def _build_vm_empty_state(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        self.vm_empty_title = QLabel("No virtual machines yet")
        self.vm_empty_title.setObjectName("heroTitle")
        self.vm_empty_subtitle = QLabel("Create a VM from an ISO to get started")
        self.vm_empty_subtitle.setObjectName("heroSubtitle")
        self.vm_empty_subtitle.setWordWrap(True)
        self.vm_empty_button = self._button("New VM", self.new_vm_from_empty, primary=True)
        layout.addStretch()
        layout.addWidget(self.vm_empty_title)
        layout.addWidget(self.vm_empty_subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.vm_empty_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 18, 18, 18)
        layout.setSpacing(12)
        self.selection_label = QLabel("No VM selected")
        self.selection_label.setObjectName("sectionTitle")
        layout.addWidget(self.selection_label)

        self.preflight_summary = QLabel("Preflight not run yet")
        self.preflight_summary.setObjectName("preflightSummary")
        self.preflight_details_button = QPushButton("View details")
        self.preflight_details_button.setObjectName("ghostButton")
        self.preflight_details_button.setCheckable(True)
        self.preflight_details_button.toggled.connect(self.toggle_preflight_details)
        self.preflight_table = QTableWidget(0, 3)
        self.preflight_table.setHorizontalHeaderLabels(["Status", "Detail", "Suggested command"])
        self.preflight_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preflight_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preflight_table.verticalHeader().setVisible(False)
        self.preflight_table.horizontalHeader().setStretchLastSection(True)
        self.preflight_table.setMaximumHeight(190)
        self.preflight_table.setColumnWidth(0, 95)
        self.preflight_table.setColumnWidth(1, 520)
        self.preflight_table.setVisible(False)

        preflight_box = QFrame()
        preflight_box.setObjectName("panel")
        preflight_layout = QVBoxLayout(preflight_box)
        preflight_layout.setContentsMargins(16, 14, 16, 14)
        preflight_header = QHBoxLayout()
        preflight_header.addWidget(self.preflight_summary)
        preflight_header.addStretch()
        preflight_header.addWidget(self.preflight_details_button)
        preflight_layout.addLayout(preflight_header)
        preflight_layout.addWidget(self.preflight_table)
        layout.addWidget(preflight_box)

        lab_box = QFrame()
        lab_box.setObjectName("panel")
        lab_layout = QVBoxLayout(lab_box)
        lab_layout.setContentsMargins(16, 14, 16, 14)
        lab_layout.setSpacing(8)
        lab_header = QHBoxLayout()
        lab_title = QLabel("Lab Details")
        lab_title.setObjectName("sectionTitle")
        self.new_vm_in_lab_button = self._button("New VM in Lab", self.new_vm_in_selected_lab, primary=True)
        lab_header.addWidget(lab_title)
        lab_header.addStretch()
        lab_header.addWidget(self.new_vm_in_lab_button)
        self.lab_details_text = QTextEdit()
        self.lab_details_text.setReadOnly(True)
        self.lab_details_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.lab_topology = LabTopologyWidget()
        self.lab_topology.vm_selected.connect(self._select_vm_by_name)
        self.lab_detail_tabs = QTabWidget()
        self.lab_detail_tabs.setMaximumHeight(220)
        self.lab_detail_tabs.addTab(self.lab_details_text, "Details")
        self.lab_detail_tabs.addTab(self.lab_topology, "Topology")
        lab_layout.addLayout(lab_header)
        lab_layout.addWidget(self.lab_detail_tabs)
        layout.addWidget(lab_box)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(self._build_detail_area())
        vertical.addWidget(self._build_logs_panel())
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 1)
        vertical.setSizes([620, 170])
        layout.addWidget(vertical, 1)
        return panel

    def toggle_preflight_details(self, checked: bool) -> None:
        self.preflight_table.setVisible(checked)
        self.preflight_details_button.setText("Hide details" if checked else "View details")

    def _build_detail_area(self) -> QWidget:
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self._build_main_empty_state())
        self.detail_stack.addWidget(self._build_detail_tabs())
        return self.detail_stack

    def _build_main_empty_state(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(34, 34, 34, 34)
        layout.setSpacing(18)
        title = QLabel("No VM selected")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Select a virtual machine from the list or start a new one.")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        cards.addWidget(self._quick_card("New VM", "Create from a local ISO", self.new_vm, primary=True), 0, 0)
        cards.addWidget(self._quick_card("Refresh", "Reload VM, lab and host state", self.refresh_all), 0, 1)
        cards.addWidget(self._quick_card("View Logs", "Jump to recent HyperGery activity", self.focus_logs), 0, 2)
        layout.addLayout(cards)
        layout.addStretch()
        return panel

    def _quick_card(self, title: str, subtitle: str, callback: Callable[[], None], *, primary: bool = False) -> QWidget:
        card = QFrame()
        card.setObjectName("quickCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("mutedLabel")
        subtitle_label.setWordWrap(True)
        button = self._button(title, callback, primary=primary)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addStretch()
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        return card

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
        panel.setMaximumHeight(235)
        panel.setMinimumHeight(135)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("Activity Log")
        title.setObjectName("sectionTitle")
        copy = QPushButton("Copy")
        copy.setObjectName("ghostButton")
        copy.clicked.connect(self.copy_logs)
        refresh = QPushButton("Refresh Logs")
        refresh.setObjectName("ghostButton")
        refresh.clicked.connect(self.refresh_logs)
        clear = QPushButton("Clear View")
        clear.setObjectName("ghostButton")
        clear.clicked.connect(self.clear_log_view)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(copy)
        header.addWidget(refresh)
        header.addWidget(clear)
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addLayout(header)
        layout.addWidget(self.activity_log, 1)
        return panel

    def copy_logs(self) -> None:
        QApplication.clipboard().setText(self.activity_log.toPlainText())
        self.status.showMessage("Activity log copied to clipboard", 2500)

    def clear_log_view(self) -> None:
        self.activity_log.clear()
        self.status.showMessage("Activity log view cleared", 2500)

    def focus_logs(self) -> None:
        self.activity_log.setFocus()
        self.activity_log.moveCursor(QTextCursor.MoveOperation.End)

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
            self.refresh_labs_button,
            self.new_lab_button,
            self.rename_lab_button,
            self.delete_lab_button,
            self.duplicate_lab_button,
            self.export_lab_button,
            self.import_lab_button,
            self.new_vm_in_lab_button,
            self.new_vm_template_button,
            self.delete_vm_template_button,
            self.edit_vm_template_button,
            self.export_vm_template_button,
            self.import_vm_template_button,
            self.refresh_vm_templates_button,
            self.overview_button,
            self.new_lab_template_button,
            self.delete_lab_template_button,
            self.edit_lab_template_button,
            self.export_lab_template_button,
            self.import_lab_template_button,
            self.refresh_lab_templates_button,
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
        has_lab = self.selected_lab is not None
        self.rename_lab_button.setEnabled(has_lab)
        self.delete_lab_button.setEnabled(has_lab)
        self.duplicate_lab_button.setEnabled(has_lab)
        self.export_lab_button.setEnabled(has_lab)
        self.new_vm_in_lab_button.setEnabled(has_lab)
        has_vm_tmpl = self.selected_vm_template is not None
        self.create_vm_from_template_button.setEnabled(has_vm_tmpl)
        self.delete_vm_template_button.setEnabled(has_vm_tmpl)
        self.edit_vm_template_button.setEnabled(has_vm_tmpl)
        self.export_vm_template_button.setEnabled(has_vm_tmpl)
        has_lab_tmpl = self.selected_lab_template is not None
        self.create_lab_from_template_button.setEnabled(has_lab_tmpl)
        self.delete_lab_template_button.setEnabled(has_lab_tmpl)
        self.edit_lab_template_button.setEnabled(has_lab_tmpl)
        self.export_lab_template_button.setEnabled(has_lab_tmpl)

    def refresh_all(self) -> None:
        self.status.showMessage("Loading host state...")
        self.run_operation(
            "Loading host state",
            self.collect_overview,
            on_success=self.apply_overview,
            refresh_after=False,
            busy=False,
        )

    def collect_overview(self) -> dict[str, Any]:
        overview: dict[str, Any] = {"errors": {}}
        jobs: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("preflight", self.backend.preflight),
            ("vms", self.backend.list_vms),
            ("labs", self.backend.load_labs),
            ("logs", self.backend.recent_logs),
            ("vm_templates", self.template_store.list_vm_templates),
            ("lab_templates", self.template_store.list_lab_templates),
        )
        for key, callback in jobs:
            try:
                overview[key] = callback()
            except Exception as exc:
                overview["errors"][key] = str(exc)
        return overview

    def apply_overview(self, overview: dict[str, Any]) -> None:
        errors = overview.get("errors", {})
        if "preflight" in overview:
            self.render_preflight(overview["preflight"])
        elif "preflight" in errors:
            self.preflight_summary.setText(f"Preflight unavailable: {errors['preflight']}")
        if "vms" in overview:
            self.render_vms(overview["vms"])
        elif "vms" in errors:
            self.render_vms([])
            self.status.showMessage(f"VM list unavailable: {errors['vms']}", 5000)
        if "labs" in overview:
            self.render_labs(overview["labs"])
        elif "labs" in errors:
            self.render_labs_error(errors["labs"])
        if "logs" in overview:
            self.render_logs(overview["logs"])
        elif "logs" in errors:
            self.render_logs(f"Logs unavailable: {errors['logs']}")
        if "vm_templates" in overview:
            self.render_vm_templates(overview["vm_templates"])
        if "lab_templates" in overview:
            self.render_lab_templates(overview["lab_templates"])
        self.render_selected()
        if not errors:
            self.status.showMessage("Ready")
        else:
            self.status.showMessage("Loaded with warnings", 5000)

    def refresh_preflight(self) -> None:
        try:
            items = self.backend.preflight()
        except Exception as exc:
            self.preflight_summary.setText(f"Preflight unavailable: {exc}")
            return
        self.render_preflight(items)

    def render_preflight(self, items: list[Any]) -> None:
        self.preflight_table.setRowCount(0)
        counts = {"OK": 0, "Warning": 0, "Error": 0}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
            row = self.preflight_table.rowCount()
            self.preflight_table.insertRow(row)
            self._set_table_item(self.preflight_table, row, 0, item.status, status=item.status)
            self._set_table_item(self.preflight_table, row, 1, f"{item.name}: {item.detail}")
            self._set_table_item(self.preflight_table, row, 2, item.fix)
        total = len(items)
        passed = counts["OK"]
        if counts["Error"]:
            self.preflight_summary.setText(f"Host blocked · {passed}/{total} checks passed")
            self.preflight_summary.setObjectName("errorLabel")
        elif counts["Warning"]:
            self.preflight_summary.setText(f"Host ready with warnings · {passed}/{total} checks passed")
            self.preflight_summary.setObjectName("mutedLabel")
        else:
            self.preflight_summary.setText(f"Host ready · {passed}/{total} checks passed")
            self.preflight_summary.setObjectName("okLabel")
        self.preflight_summary.style().unpolish(self.preflight_summary)
        self.preflight_summary.style().polish(self.preflight_summary)

    def refresh_vms(self) -> None:
        current = self.selected_vm.name if self.selected_vm else ""
        try:
            vms = self.backend.list_vms()
        except HyperGeryError as exc:
            vms = []
            self.show_error(str(exc))
        self.render_vms(vms, current=current)

    def render_vms(self, vms: list[VmSummary], *, current: str | None = None) -> None:
        if current is None:
            current = self.selected_vm.name if self.selected_vm else ""
        self.all_vms = vms
        selected_lab_id = self.selected_lab_id()
        self.vms = filter_vms_for_lab(vms, selected_lab_id, self.vm_filter.currentText() == "Selected Lab")
        self.vm_table.setRowCount(0)
        selected_row = -1
        for vm in self.vms:
            row = self.vm_table.rowCount()
            self.vm_table.insertRow(row)
            self._set_table_item(self.vm_table, row, 0, vm.name)
            self._set_table_item(self.vm_table, row, 1, STATE_LABELS[state_kind(vm.state)], status=vm.state, chip=True)
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
        total_suffix = "" if len(self.all_vms) == 1 else "s"
        if self.vm_filter.currentText() == "Selected Lab" and selected_lab_id:
            self.vm_count_label.setText(f"{len(self.vms)} shown / {len(self.all_vms)} VM{total_suffix}")
        else:
            self.vm_count_label.setText(f"{len(self.vms)} VM{suffix}, {running} running")
        self.update_vm_empty_state()
        self.vm_stack.setCurrentIndex(0 if self.vms else 1)
        self.render_labs(self.labs, keep_selection=True)
        self.update_actions()

    def refresh_labs(self) -> None:
        try:
            labs = self.backend.load_labs()
        except Exception as exc:
            self.render_labs_error(str(exc))
            return
        self.render_labs(labs, keep_selection=bool(self.selected_lab))

    def lab_store(self) -> LabStore:
        return LabStore(self.backend.data_dir)

    def selected_lab_id(self) -> str:
        return str(self.selected_lab.get("lab_id", "")) if self.selected_lab else ""

    def existing_lab_ids(self) -> set[str]:
        return {str(lab.get("lab_id", "")) for lab in self.labs}

    def existing_lab_subnets(self) -> set[str]:
        return {str(lab.get("subnet", "")) for lab in self.labs if lab.get("subnet")}

    def on_lab_selection_changed(self) -> None:
        indexes = self.lab_table.selectionModel().selectedRows()
        if not indexes:
            self.selected_lab = None
        else:
            row = indexes[0].row()
            self.selected_lab = self.labs[row] if 0 <= row < len(self.labs) else None
        self.render_lab_details()
        if self.vm_filter.currentText() == "Selected Lab":
            self.render_vms(self.all_vms)
        self.update_actions()

    def on_vm_filter_changed(self) -> None:
        self.render_vms(self.all_vms)

    def update_vm_empty_state(self) -> None:
        if self.vm_filter.currentText() == "Selected Lab" and self.selected_lab is not None:
            self.vm_empty_title.setText("No VMs in this lab yet")
            self.vm_empty_subtitle.setText(f"Create a VM in {self.selected_lab_id()} from an ISO.")
            self.vm_empty_button.setText("New VM in Lab")
        else:
            self.vm_empty_title.setText("No virtual machines yet")
            self.vm_empty_subtitle.setText("Create a VM from an ISO to get started")
            self.vm_empty_button.setText("New VM")

    def render_lab_details(self) -> None:
        lab = self.selected_lab
        if lab is None:
            self.lab_details_text.setPlainText("No lab selected.")
            self.lab_topology.set_topology(None)
            return
        templates_used = lab.get("templates_used", [])
        self.lab_details_text.setPlainText(
            details_block(
                ("Name", str(lab.get("name") or lab.get("lab_id", ""))),
                ("Lab ID", str(lab.get("lab_id", ""))),
                ("Description", str(lab.get("description") or "")),
                ("Network ID", str(lab.get("network_id", ""))),
                ("Network mode", str(lab.get("network_mode", ""))),
                ("Subnet", str(lab.get("subnet", ""))),
                ("Bridge", str(lab.get("bridge_name", ""))),
                ("VM count", str(vm_count_for_lab(lab, self.all_vms))),
                ("Templates used", ", ".join(templates_used) if templates_used else "none"),
                ("Created", str(lab.get("created_at", ""))),
                ("Updated", str(lab.get("updated_at", ""))),
                ("Notes", str(lab.get("notes", ""))),
            )
        )
        self.lab_topology.set_topology(build_lab_topology(lab, self.all_vms))

    def _select_vm_by_name(self, vm_name: str) -> None:
        for row in range(self.vm_table.rowCount()):
            item = self.vm_table.item(row, 0)
            if item and item.text() == vm_name:
                self.vm_table.selectRow(row)
                self.lab_detail_tabs.setCurrentIndex(0)
                break

    def log_activity(self, message: str) -> None:
        logging.info(message)
        current = self.activity_log.toPlainText()
        text = f"{now_iso()} INFO {message}"
        self.activity_log.setPlainText(f"{current.rstrip()}\n{text}".strip())
        self.activity_log.moveCursor(QTextCursor.MoveOperation.End)

    def selected_lab_or_error(self) -> dict[str, Any]:
        if self.selected_lab is None:
            raise HyperGeryError("Select a lab first.")
        return self.selected_lab

    def new_lab(self) -> None:
        dialog = NewLabDialog(self.existing_lab_ids(), self.existing_lab_subnets(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            lab = self.lab_store().create_lab(
                values["name"],
                values["description"],
                values["network_mode"],
                lab_id=values["lab_id"],
            )
        except Exception as exc:
            self.log_activity(f"Create lab failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = lab
        self.log_activity(f"Created lab {lab['lab_id']}")
        self.refresh_labs()

    def rename_lab(self) -> None:
        try:
            lab = self.selected_lab_or_error()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        dialog = RenameLabDialog(lab, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            updated = self.lab_store().get_lab(str(lab["lab_id"]))
            updated["name"] = values["name"]
            updated["description"] = values["description"]
            updated["updated_at"] = now_iso()
            self.backend.write_lab(updated)
        except Exception as exc:
            self.log_activity(f"Rename lab failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = updated
        self.log_activity(f"Updated lab name {updated['lab_id']}")
        self.refresh_labs()

    def delete_lab(self) -> None:
        try:
            lab = self.selected_lab_or_error()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        dialog = DeleteLabDialog(lab, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.lab_store().delete_lab(str(lab["lab_id"]), delete_vms=dialog.delete_vms_too())
        except Exception as exc:
            self.log_activity(f"Delete lab failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = None
        self.log_activity(f"Deleted lab {lab['lab_id']}")
        self.refresh_labs()

    def duplicate_lab(self) -> None:
        try:
            lab = self.selected_lab_or_error()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        dialog = DuplicateLabDialog(lab, self.existing_lab_ids(), self.existing_lab_subnets(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        clone_vms = bool(values.get("clone_vms"))
        source_lab_id = str(lab["lab_id"])

        def do_duplicate() -> dict:
            store = LabStore(
                self.backend.data_dir,
                clone_vm_callback=self.backend.clone_vm if clone_vms else None,
                vm_state_callback=(lambda name: self.backend.get_vm(name).state) if clone_vms else None,
            )
            return store.duplicate_lab(source_lab_id, values["new_name"], clone_vms=clone_vms)

        def on_done(duplicate: dict) -> None:
            self.selected_lab = duplicate
            self.log_activity(f"Duplicated lab {source_lab_id} to {duplicate['lab_id']}")
            self.refresh_labs()

        action_label = f"Duplicating lab {source_lab_id}" + (" with VM cloning" if clone_vms else "")
        self.log_activity(action_label)
        self.run_operation(action_label, do_duplicate, on_success=on_done)

    def export_lab(self) -> None:
        try:
            lab = self.selected_lab_or_error()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        lab_id = str(lab["lab_id"])
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Lab",
            f"{lab_id}.json",
            "Lab manifest (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.lab_store().export_lab(lab_id, path)
        except Exception as exc:
            self.log_activity(f"Export lab failed: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exported lab {lab_id} to {output}")
        self.status.showMessage(f"Exported {lab_id}", 3500)
        self.refresh_labs()

    def import_lab(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Lab",
            "",
            "Lab manifest (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            lab = self.lab_store().import_lab(path)
        except Exception as exc:
            if "already exists" in str(exc):
                new_lab_id, ok = QInputDialog.getText(
                    self,
                    "Import Lab",
                    f"{exc}\n\nImport with a new lab ID:",
                )
                if not ok or not new_lab_id.strip():
                    self.log_activity(f"Import lab cancelled: {exc}")
                    return
                try:
                    lab = self.lab_store().import_lab(path, new_lab_id=new_lab_id.strip())
                except Exception as retry_exc:
                    self.log_activity(f"Import lab failed: {retry_exc}")
                    self.show_error(str(retry_exc))
                    return
            else:
                self.log_activity(f"Import lab failed: {exc}")
                self.show_error(str(exc))
                return
        self.selected_lab = lab
        self.log_activity(f"Imported lab {lab['lab_id']} from {path}")
        self.refresh_labs()

    def render_labs_error(self, message: str) -> None:
        self.labs = []
        self.selected_lab = None
        self.lab_table.setRowCount(0)
        row = self.lab_table.rowCount()
        self.lab_table.insertRow(row)
        self._set_table_item(self.lab_table, row, 0, "unavailable")
        self._set_table_item(self.lab_table, row, 1, "-")
        self._set_table_item(self.lab_table, row, 2, "-")
        self._set_table_item(self.lab_table, row, 3, "-")
        self._set_table_item(self.lab_table, row, 4, message)
        self._set_table_item(self.lab_table, row, 5, "-")
        self.render_lab_details()
        self.log_activity(f"Lab refresh failed: {message}")

    def render_labs(self, labs: list[dict[str, Any]], *, keep_selection: bool = False) -> None:
        if not labs and not keep_selection:
            self.selected_lab = None
        current_lab_id = self.selected_lab_id() if keep_selection else ""
        self.labs = labs
        was_blocked = self.lab_table.blockSignals(True)
        self.lab_table.setRowCount(0)
        selected_row = -1
        for manifest in labs:
            row = self.lab_table.rowCount()
            self.lab_table.insertRow(row)
            lab_id = str(manifest.get("lab_id", "unknown"))
            name = str(manifest.get("name") or lab_id)
            if lab_id == current_lab_id:
                selected_row = row
                name = f"* {name}"
            self._set_table_item(self.lab_table, row, 0, name)
            self._set_table_item(self.lab_table, row, 1, lab_id)
            self._set_table_item(self.lab_table, row, 2, str(manifest.get("network_mode", "")))
            self._set_table_item(self.lab_table, row, 3, str(manifest.get("subnet", "")))
            self._set_table_item(self.lab_table, row, 4, str(manifest.get("bridge_name", "")))
            self._set_table_item(self.lab_table, row, 5, str(vm_count_for_lab(manifest, self.all_vms)))
        if selected_row < 0 and labs and not keep_selection:
            selected_row = 0
        if selected_row >= 0:
            self.lab_table.selectRow(selected_row)
            self.selected_lab = labs[selected_row]
        elif not keep_selection or current_lab_id:
            self.selected_lab = None
        self.lab_table.blockSignals(was_blocked)
        self.render_lab_details()
        self.update_vm_empty_state()
        self.update_actions()

    def refresh_logs(self) -> None:
        try:
            logs = self.backend.recent_logs()
        except Exception as exc:
            logs = f"Logs unavailable: {exc}"
        self.render_logs(logs)

    def render_logs(self, logs: str) -> None:
        self.activity_log.setPlainText(logs)
        self.activity_log.moveCursor(QTextCursor.MoveOperation.End)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, text: str, *, status: str = "", chip: bool = False) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if status:
            kind = state_kind(status)
            item.setForeground(QColor(STATE_COLORS.get(kind, "#c7d0dd")))
            if chip:
                item.setBackground(QColor(STATE_BACKGROUNDS.get(kind, "#202938")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                font = QFont(item.font())
                font.setBold(True)
                font.setPointSize(max(font.pointSize() - 1, 8))
                item.setFont(font)
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
            self.selection_label.setText("Dashboard")
            self.detail_stack.setCurrentIndex(0)
            empty = "No VM selected."
            for view in self.detail_views.values():
                view.setPlainText(empty)
            return
        self.detail_stack.setCurrentIndex(1)
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

    def show_cleanup_preview(self) -> None:
        dialog = CleanupPreviewDialog(
            self.all_vms,
            self.labs,
            self.vm_templates,
            self.lab_templates,
            self,
        )
        dialog.exec()

    def run_operation(
        self,
        label: str,
        fn: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        refresh_after: bool = True,
        busy: bool = True,
    ) -> None:
        if busy:
            self.set_busy(True, label)
        else:
            self.status.showMessage(label)
        job = BackendJob(label, fn)
        self.jobs.append(job)

        def succeeded() -> None:
            result = job.result
            if on_success:
                on_success(result)
            if refresh_after:
                self.refresh_all()
            if busy or refresh_after:
                self.status.showMessage("Ready")

        def failed() -> None:
            self.show_error(job.error_message)
            self.status.showMessage("Ready")

        def finished() -> None:
            if job in self.jobs:
                self.jobs.remove(job)
            self.completed_jobs.append(job)
            self.completed_jobs = self.completed_jobs[-20:]
            if busy:
                self.set_busy(False)
            else:
                self.update_actions()

        job.succeeded.connect(succeeded)
        job.failed.connect(failed)
        job.finished.connect(finished)
        job.start()

    def new_vm_from_empty(self) -> None:
        if self.vm_filter.currentText() == "Selected Lab" and self.selected_lab is not None:
            self.new_vm_in_selected_lab()
        else:
            self.new_vm()

    def new_vm_in_selected_lab(self) -> None:
        try:
            lab = self.selected_lab_or_error()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.new_vm(default_lab_id=str(lab["lab_id"]))

    def new_vm(self, default_lab_id: str = "default-lab") -> None:
        wizard = VMWizard(self, default_lab_id=default_lab_id)
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

    # ------------------------------------------------------------------ #
    # Templates                                                            #
    # ------------------------------------------------------------------ #

    def on_vm_template_selection_changed(self) -> None:
        indexes = self.vm_template_table.selectionModel().selectedRows()
        if not indexes:
            self.selected_vm_template = None
        else:
            row = indexes[0].row()
            self.selected_vm_template = self.vm_templates[row] if 0 <= row < len(self.vm_templates) else None
        self.render_vm_template_detail()
        self.update_actions()

    def on_lab_template_selection_changed(self) -> None:
        indexes = self.lab_template_table.selectionModel().selectedRows()
        if not indexes:
            self.selected_lab_template = None
        else:
            row = indexes[0].row()
            self.selected_lab_template = self.lab_templates[row] if 0 <= row < len(self.lab_templates) else None
        self.render_lab_template_detail()
        self.update_actions()

    def render_vm_template_detail(self) -> None:
        tmpl = self.selected_vm_template
        if tmpl is None:
            self.vm_template_detail.clear()
            return
        self.vm_template_detail.setPlainText(
            details_block(
                ("Name", str(tmpl.get("name", ""))),
                ("Template ID", str(tmpl.get("template_id", ""))),
                ("OS Type", str(tmpl.get("os_type", ""))),
                ("RAM", format_mib(tmpl.get("ram_mib"))),
                ("vCPUs", str(tmpl.get("vcpus", ""))),
                ("Disk", f"{tmpl.get('disk_gb', '')} GiB"),
                ("Network", str(tmpl.get("network_mode", ""))),
                ("Display", str(tmpl.get("display", ""))),
                ("Notes", str(tmpl.get("notes", ""))),
            )
        )

    def render_lab_template_detail(self) -> None:
        tmpl = self.selected_lab_template
        if tmpl is None:
            self.lab_template_detail.clear()
            return
        self.lab_template_detail.setPlainText(
            details_block(
                ("Name", str(tmpl.get("name", ""))),
                ("Template ID", str(tmpl.get("template_id", ""))),
                ("Network", str(tmpl.get("network_mode", ""))),
                ("VMs", str(len(tmpl.get("vms", [])))),
                ("Description", str(tmpl.get("description", ""))),
                ("Notes", str(tmpl.get("notes", ""))),
            )
        )

    def refresh_templates(self) -> None:
        try:
            vm_templates = self.template_store.list_vm_templates()
            lab_templates = self.template_store.list_lab_templates()
        except Exception as exc:
            self.log_activity(f"Template refresh failed: {exc}")
            self.show_error(str(exc))
            return
        self.render_vm_templates(vm_templates)
        self.render_lab_templates(lab_templates)

    def render_vm_templates(self, templates: list[dict]) -> None:
        self.vm_templates = templates
        was_blocked = self.vm_template_table.blockSignals(True)
        self.vm_template_table.setRowCount(0)
        for tmpl in templates:
            row = self.vm_template_table.rowCount()
            self.vm_template_table.insertRow(row)
            self._set_table_item(self.vm_template_table, row, 0, str(tmpl.get("name", "")))
            self._set_table_item(self.vm_template_table, row, 1, str(tmpl.get("template_id", "")))
            self._set_table_item(self.vm_template_table, row, 2, str(tmpl.get("os_type", "")))
            self._set_table_item(self.vm_template_table, row, 3, format_mib(tmpl.get("ram_mib")))
            self._set_table_item(self.vm_template_table, row, 4, str(tmpl.get("vcpus", "")))
            self._set_table_item(self.vm_template_table, row, 5, f"{tmpl.get('disk_gb', '')} GiB")
            self._set_table_item(self.vm_template_table, row, 6, str(tmpl.get("network_mode", "")))
            self._set_table_item(self.vm_template_table, row, 7, str(tmpl.get("display", "")))
        self.vm_template_table.blockSignals(was_blocked)

    def render_lab_templates(self, templates: list[dict]) -> None:
        self.lab_templates = templates
        was_blocked = self.lab_template_table.blockSignals(True)
        self.lab_template_table.setRowCount(0)
        for tmpl in templates:
            row = self.lab_template_table.rowCount()
            self.lab_template_table.insertRow(row)
            self._set_table_item(self.lab_template_table, row, 0, str(tmpl.get("name", "")))
            self._set_table_item(self.lab_template_table, row, 1, str(tmpl.get("template_id", "")))
            self._set_table_item(self.lab_template_table, row, 2, str(tmpl.get("network_mode", "")))
            self._set_table_item(self.lab_template_table, row, 3, str(len(tmpl.get("vms", []))))
            notes = str(tmpl.get("description") or tmpl.get("notes", ""))
            self._set_table_item(self.lab_template_table, row, 4, notes[:60] + ("..." if len(notes) > 60 else ""))
        self.lab_template_table.blockSignals(was_blocked)

    def new_vm_template(self) -> None:
        dialog = NewVmTemplateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            template = self.template_store.create_vm_template(**values)
        except Exception as exc:
            self.log_activity(f"Create VM template failed: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Created VM template {template['template_id']}")
        self.refresh_templates()

    def delete_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Select a VM template first.")
            return
        tmpl = self.selected_vm_template
        dialog = DeleteVmTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.template_store.delete_vm_template(str(tmpl["template_id"]))
        except Exception as exc:
            self.log_activity(f"Delete VM template failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_vm_template = None
        self.log_activity(f"Deleted VM template {tmpl['template_id']}")
        self.refresh_templates()

    def export_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Select a VM template first.")
            return
        tmpl = self.selected_vm_template
        template_id = str(tmpl["template_id"])
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export VM Template",
            f"{template_id}.json",
            "Template (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.template_store.export_vm_template(template_id, path)
        except Exception as exc:
            self.log_activity(f"Export VM template failed: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exported VM template {template_id} to {output}")
        self.status.showMessage(f"Exported {template_id}", 3500)

    def import_vm_template(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import VM Template",
            "",
            "Template (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            template = self.template_store.import_vm_template(path)
        except Exception as exc:
            if "already exists" in str(exc):
                self.show_error(f"{exc}\n\nDelete the existing template first, then re-import.")
            else:
                self.show_error(str(exc))
            self.log_activity(f"Import VM template failed: {exc}")
            return
        self.log_activity(f"Imported VM template {template['template_id']} from {path}")
        self.refresh_templates()

    def new_lab_template(self) -> None:
        dialog = NewLabTemplateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            template = self.template_store.create_lab_template(**values)
        except Exception as exc:
            self.log_activity(f"Create lab template failed: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Created lab template {template['template_id']}")
        self.refresh_templates()

    def delete_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Select a lab template first.")
            return
        tmpl = self.selected_lab_template
        dialog = DeleteLabTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.template_store.delete_lab_template(str(tmpl["template_id"]))
        except Exception as exc:
            self.log_activity(f"Delete lab template failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab_template = None
        self.log_activity(f"Deleted lab template {tmpl['template_id']}")
        self.refresh_templates()

    def export_action_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Select a lab template first.")
            return
        tmpl = self.selected_lab_template
        template_id = str(tmpl["template_id"])
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Lab Template",
            f"{template_id}.json",
            "Template (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.template_store.export_lab_template(template_id, path)
        except Exception as exc:
            self.log_activity(f"Export lab template failed: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exported lab template {template_id} to {output}")
        self.status.showMessage(f"Exported {template_id}", 3500)

    def import_action_lab_template(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Lab Template",
            "",
            "Template (*.json);;All files (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            template = self.template_store.import_lab_template(path)
        except Exception as exc:
            if "already exists" in str(exc):
                self.show_error(f"{exc}\n\nDelete the existing template first, then re-import.")
            else:
                self.show_error(str(exc))
            self.log_activity(f"Import lab template failed: {exc}")
            return
        self.log_activity(f"Imported lab template {template['template_id']} from {path}")
        self.refresh_templates()

    def create_vm_from_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Select a VM template first.")
            return
        tmpl = self.selected_vm_template
        template_id = str(tmpl["template_id"])
        wizard = VMWizard(self, defaults=tmpl)
        wizard.setWindowTitle(f"Create VM from Template: {template_id}")
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        if (
            QMessageBox.question(
                self,
                "Create VM from Template",
                (
                    f"Create {values['name']} from template {template_id}?\n\n"
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

        lab_id = values["lab_id"]

        def record_template_used(_result: Any) -> None:
            try:
                lab = self.lab_store().get_lab(lab_id)
                used: list[str] = list(lab.get("templates_used", []))
                if template_id not in used:
                    used.append(template_id)
                lab["templates_used"] = used
                self.backend.write_lab(lab)
            except Exception:
                pass

        self.log_activity(f"Creating VM {values['name']} from template {template_id}")
        self.run_operation(
            f"Creating {values['name']} from template",
            lambda: self.backend.create_vm(**values),
            on_success=record_template_used,
        )

    def create_lab_from_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Select a lab template first.")
            return
        tmpl = self.selected_lab_template
        template_id = str(tmpl["template_id"])
        wizard = InstantiateLabTemplateWizard(
            tmpl,
            self.existing_lab_ids(),
            self.existing_lab_subnets(),
            self,
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        lab_name = values["lab_name"]
        lab_description = values["lab_description"]
        vm_iso_map = values["vm_iso_map"]
        planned_vm_count = len(tmpl.get("vms", []))

        def do_instantiate() -> dict:
            return self.template_store.instantiate_lab_template(
                template_id,
                lab_name,
                vm_iso_map,
                new_lab_description=lab_description,
            )

        def on_instantiate_done(result: dict) -> None:
            if result.get("errors"):
                errs = "\n".join(result["errors"])
                self.log_activity(f"Create lab from template failed:\n{errs}")
                self.show_error(f"Lab creation failed:\n{errs}")
                return
            lab = result.get("lab")
            if lab:
                self.selected_lab = lab
                created = len(result.get("vms_created", []))
                warnings = result.get("warnings", [])
                msg = f"Created lab {lab['lab_id']} from template {template_id} ({created}/{planned_vm_count} VMs)"
                if warnings:
                    msg += f"\nWarnings: {'; '.join(warnings)}"
                self.log_activity(msg)
            self.refresh_labs()
            self.refresh_templates()

        self.log_activity(f"Instantiating lab template {template_id} as '{lab_name}'…")
        self.run_operation(
            f"Creating lab from template {template_id}",
            do_instantiate,
            on_success=on_instantiate_done,
        )

    def edit_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Select a VM template first.")
            return
        tmpl = self.selected_vm_template
        dialog = EditVmTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            updated = self.template_store.update_vm_template(str(tmpl["template_id"]), **values)
        except Exception as exc:
            self.log_activity(f"Edit VM template failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_vm_template = updated
        self.log_activity(f"Updated VM template {updated['template_id']}")
        self.refresh_templates()

    def edit_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Select a lab template first.")
            return
        tmpl = self.selected_lab_template
        dialog = EditLabTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            updated = self.template_store.update_lab_template(str(tmpl["template_id"]), **values)
        except Exception as exc:
            self.log_activity(f"Edit lab template failed: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab_template = updated
        self.log_activity(f"Updated lab template {updated['template_id']}")
        self.refresh_templates()
