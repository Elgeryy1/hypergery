from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
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
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QScrollArea,
    QSpinBox,
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
from ..config import HyperGeryConfig, effective_config, effective_value
from ..labs import LAB_VM_ROLES, LabStore
from ..templates import TemplateStore
from .dialogs import (
    AppSettingsDialog,
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
    LiveMigrationDialog,
    NewLabDialog,
    NewLabTemplateDialog,
    NewVmTemplateDialog,
    RenameLabDialog,
    SettingsDialog,
    SnapshotDialog,
    VMWizard,
)
from .console import VmConsoleWindow
from .console_helpers import should_autoconnect_console
from .lab_helpers import (
    build_lab_topology,
    filter_vms_for_lab,
    lab_status_summary,
    plan_lab_power_action,
    unify_lab_vms,
    vm_count_for_lab,
)
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
        self.remote_hosts: list[dict[str, Any]] = []
        self.remote_vms_inventory: list[dict[str, Any]] = []
        self.console_windows: dict[str, VmConsoleWindow] = {}
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
        self.right_panel = self._build_right_panel()
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(splitter, 1)
        root_layout.addLayout(body, 1)
        self.setCentralWidget(root)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    SIDEBAR_SECTIONS = (
        "Dashboard",
        "Virtual Machines",
        "Labs",
        "Templates",
        "Remote Hosts",
        "Migrations",
        "Commands",
        "Diagnostics",
        "Settings",
    )

    def _build_sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(196)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(0)
        self.sidebar_nav = QListWidget()
        self.sidebar_nav.setObjectName("sidebarNav")
        self.sidebar_nav.addItems(list(self.SIDEBAR_SECTIONS))
        self.sidebar_nav.setCurrentRow(self.SIDEBAR_SECTIONS.index("Virtual Machines"))
        self.sidebar_nav.currentRowChanged.connect(self._on_sidebar_changed)
        layout.addWidget(self.sidebar_nav, 1)
        return frame

    def _on_sidebar_changed(self, row: int) -> None:
        if row < 0:
            return
        section = self.SIDEBAR_SECTIONS[row]
        if section == "Settings":
            previous = getattr(self, "_sidebar_previous_row", self.SIDEBAR_SECTIONS.index("Virtual Machines"))
            self.sidebar_nav.blockSignals(True)
            self.sidebar_nav.setCurrentRow(previous)
            self.sidebar_nav.blockSignals(False)
            self.app_settings()
            return
        self._sidebar_previous_row = row
        page_map = {
            "Dashboard": self.dashboard_page_index,
            "Virtual Machines": 0,
            "Labs": self.labs_page_index,
            "Templates": 1,
            "Remote Hosts": 2,
            "Migrations": self.migrations_page_index,
            "Commands": self.commands_page_index,
            "Diagnostics": self.diagnostics_page_index,
        }
        self.main_tabs.setCurrentIndex(page_map[section])
        if section == "Migrations" and not getattr(self, "_migrations_loaded", False):
            self.refresh_migrations()
            self.refresh_hub_staging()
        if section == "Commands" and not getattr(self, "_commands_loaded", False):
            self.refresh_commands()
        if section == "Labs":
            self.render_labs_workspace()
        self.right_panel.setVisible(section == "Virtual Machines")

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("HyperGery")
        title.setObjectName("brandTitle")
        subtitle = QLabel(f"v{APP_DISPLAY_VERSION} · develop · KVM / QEMU / libvirt")
        subtitle.setObjectName("brandSubtle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        layout.addLayout(brand)
        layout.addSpacing(14)

        config = effective_config()
        self.hub_chip = QLabel("Hub: not checked")
        self.host_chip = QLabel(f"Host: {config['host_id'].value}")
        self.nas_chip = QLabel("NAS: not checked")
        for chip in (self.hub_chip, self.host_chip, self.nas_chip):
            chip.setObjectName("statusChip")
            layout.addWidget(chip)
        layout.addStretch()

        self.new_button = self._button("New VM", self.new_vm, primary=True)
        self.refresh_button = self._button("Refresh", self.refresh_all)
        self.app_settings_button = self._button("Settings", self.app_settings)
        layout.addWidget(self.new_button)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.app_settings_button)
        return bar

    def _build_vm_actions_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.settings_button = self._button("Settings", self.settings_vm)
        self.start_button = self._button("Start", self.start_vm)
        self.shutdown_button = self._button("ACPI Shutdown", self.shutdown_vm)
        self.console_button = self._button("Console", self.open_console)
        self.external_console_button = self._button("External Console", self.open_external_console)
        self.snapshots_button = self._button("Snapshots", self.snapshots_vm)
        self.clone_button = self._button("Clone", self.clone_vm)
        self.migrate_button = self._button("Live Migration", self.live_migration_vm)
        self.force_button = self._button("Force Off", self.force_off_vm, danger=True)
        self.delete_button = self._button("Delete", self.delete_vm, danger=True)
        self.overview_button = self._button("Resources…", self.show_cleanup_preview)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        for button in (
            self.start_button,
            self.shutdown_button,
            self.force_button,
            self.console_button,
            self.external_console_button,
        ):
            top_row.addWidget(button)
        top_row.addStretch()
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        for button in (
            self.snapshots_button,
            self.clone_button,
            self.migrate_button,
            self.settings_button,
            self.overview_button,
        ):
            bottom_row.addWidget(button)
        bottom_row.addStretch()
        bottom_row.addWidget(self.delete_button)
        layout.addLayout(top_row)
        layout.addLayout(bottom_row)
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
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        self.vm_page_title = QLabel("Virtual Machines")
        self.vm_page_title.setObjectName("pageTitle")
        self.vm_page_subtitle = QLabel("Local KVM/libvirt machines and lab workloads")
        self.vm_page_subtitle.setObjectName("mutedLabel")
        head_col.addWidget(self.vm_page_title)
        head_col.addWidget(self.vm_page_subtitle)
        self.vm_count_label = QLabel("No VMs")
        self.vm_count_label.setObjectName("mutedLabel")
        self.vm_filter = QComboBox()
        self.vm_filter.addItems(["All VMs", "Selected Lab"])
        self.vm_filter.currentIndexChanged.connect(self.on_vm_filter_changed)
        header.addLayout(head_col)
        header.addStretch()
        header.addWidget(self.vm_filter)
        header.addWidget(self.vm_count_label)
        layout.addLayout(header)
        layout.addWidget(self._build_vm_actions_bar())

        self.vm_table = QTableWidget(0, 7)
        self.vm_table.setHorizontalHeaderLabels(["Name", "State", "Lab", "CPU", "RAM", "Disk", "Display"])
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

        self.main_tabs.addTab(self._build_remote_hosts_page(), "Remote Hosts")

        self.dashboard_page_index = self.main_tabs.addTab(self._build_dashboard_page(), "Dashboard")
        self.labs_page_index = self.main_tabs.addTab(self._build_labs_page(), "Labs")
        self.migrations_page_index = self.main_tabs.addTab(self._build_migrations_page(), "Migrations")
        self.commands_page_index = self.main_tabs.addTab(self._build_commands_page(), "Commands")
        self.diagnostics_page_index = self.main_tabs.addTab(self._build_diagnostics_page(), "Diagnostics")
        self.main_tabs.tabBar().hide()

        return panel

    def _build_remote_hosts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Remote Hosts")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Hub-connected KVM hosts and VM inventory")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.remote_status_label = QLabel("Hub not loaded")
        self.remote_status_label.setObjectName("mutedLabel")
        self.refresh_remote_button = self._button("Refresh", self.refresh_remote_hosts)
        self.test_remote_button = self._button("Test Selected Host", self.test_selected_remote_host)
        remote_settings_button = self._button("Settings", self.app_settings)
        header.addWidget(self.remote_status_label)
        header.addWidget(self.refresh_remote_button)
        header.addWidget(self.test_remote_button)
        header.addWidget(remote_settings_button)
        layout.addLayout(header)

        self.hub_card = QFrame()
        self.hub_card.setObjectName("hubCard")
        hub_layout = QVBoxLayout(self.hub_card)
        hub_layout.setContentsMargins(18, 14, 18, 14)
        hub_layout.setSpacing(10)
        hub_head = QHBoxLayout()
        hub_title = QLabel("HyperGery Hub")
        hub_title.setObjectName("sectionTitle")
        self.hub_status_label = QLabel("not checked")
        self.hub_status_label.setObjectName("statusChip")
        self.hub_url_label = QLabel(self.registry_url())
        self.hub_url_label.setObjectName("mutedLabel")
        hub_config_button = self._button("Config Hub", self.app_settings)
        hub_head.addWidget(hub_title)
        hub_head.addWidget(self.hub_status_label)
        hub_head.addSpacing(8)
        hub_head.addWidget(self.hub_url_label)
        hub_head.addStretch()
        hub_head.addWidget(hub_config_button)
        hub_layout.addLayout(hub_head)

        metrics = QHBoxLayout()
        metrics.setSpacing(24)
        self.hub_latency_label = QLabel("—")
        self.hub_hosts_online_label = QLabel("0")
        self.hub_vm_count_label = QLabel("0")
        self.hub_nas_label = QLabel("not checked")
        self.hub_last_check_label = QLabel("—")
        for caption, value_label in (
            ("LATENCY", self.hub_latency_label),
            ("HOSTS ONLINE", self.hub_hosts_online_label),
            ("VM INVENTORY", self.hub_vm_count_label),
            ("NAS STAGING", self.hub_nas_label),
            ("LAST CHECK", self.hub_last_check_label),
        ):
            cell = QVBoxLayout()
            cell.setSpacing(3)
            caption_label = QLabel(caption)
            caption_label.setObjectName("metricLabel")
            value_label.setObjectName("metricValue")
            value_label.setWordWrap(True)
            cell.addWidget(caption_label)
            cell.addWidget(value_label)
            metrics.addLayout(cell, 1)
        hub_layout.addLayout(metrics)
        layout.addWidget(self.hub_card)

        self.remote_cards_scroll = QScrollArea()
        self.remote_cards_scroll.setWidgetResizable(True)
        self.remote_cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_body = QWidget()
        self.remote_cards_layout = QGridLayout(cards_body)
        self.remote_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.remote_cards_layout.setHorizontalSpacing(14)
        self.remote_cards_layout.setVerticalSpacing(14)
        self.remote_cards_scroll.setWidget(cards_body)
        layout.addWidget(self.remote_cards_scroll, 1)
        self._host_card_frames: list[QFrame] = []
        self.selected_remote_host_index: int | None = None

        self.remote_detail = QTextEdit()
        self.remote_detail.setReadOnly(True)
        self.remote_detail.setMaximumHeight(120)
        self.remote_detail.setPlaceholderText("Select Refresh to load hosts from the HyperGery Hub.")
        layout.addWidget(self.remote_detail)
        return page

    def _clear_remote_cards(self) -> None:
        self._host_card_frames = []
        self.selected_remote_host_index = None
        while self.remote_cards_layout.count():
            item = self.remote_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _remote_message_panel(self, title: str, body: str, *, action: tuple[str, Callable[[], None]] | None = None) -> QFrame:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        body_label = QLabel(body)
        body_label.setObjectName("mutedLabel")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        if action is not None:
            layout.addWidget(self._button(action[0], action[1]), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return panel

    def _select_host_card(self, index: int) -> None:
        self.selected_remote_host_index = index
        for frame_index, frame in enumerate(self._host_card_frames):
            host = self.remote_hosts[frame_index] if frame_index < len(self.remote_hosts) else {}
            offline = str(host.get("status") or "offline") != "online"
            name = "hostCardSelected" if frame_index == index else ("hostCardOffline" if offline else "hostCard")
            frame.setObjectName(name)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
        self.update_actions()

    def _host_card(self, host: dict[str, Any], index: int) -> QFrame:
        offline = str(host.get("status") or "offline") != "online"
        card = QFrame()
        card.setObjectName("hostCardOffline" if offline else "hostCard")
        card.mousePressEvent = lambda event, idx=index: self._select_host_card(idx)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        host_id = str(host.get("host_id") or "?")
        id_label = QLabel(host_id)
        id_label.setObjectName("sectionTitle")
        name = str(host.get("name") or host.get("hostname") or "")
        cpu = str(host.get("cpu_model") or "")
        if len(cpu) > 42:
            cpu = cpu[:39] + "…"
        meta = QLabel(" · ".join(part for part in (name, cpu) if part))
        meta.setObjectName("mutedLabel")
        status_chip = QLabel("OFFLINE" if offline else "ONLINE")
        status_chip.setObjectName("statusChipBad" if offline else "statusChipOk")
        head_col = QVBoxLayout()
        head_col.setSpacing(1)
        head_col.addWidget(id_label)
        head_col.addWidget(meta)
        head.addLayout(head_col)
        head.addStretch()
        head.addWidget(status_chip, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)

        if offline:
            callout = QLabel(f"No heartbeat since {host.get('last_seen') or 'unknown'}. Not available as a migration target.")
            callout.setObjectName("calloutDanger")
            callout.setWordWrap(True)
            layout.addWidget(callout)
        else:
            badges = QHBoxLayout()
            badges.setSpacing(8)
            for ok, text in ((host.get("kvm_ok"), "KVM"), (host.get("libvirt_ok"), "libvirt")):
                badge = QLabel(f"{text} {'OK' if ok else 'FAIL'}")
                badge.setObjectName("statusChipOk" if ok else "statusChipBad")
                badges.addWidget(badge)
            badges.addStretch()
            active_vms = host.get("active_vms") or []
            vm_count = QLabel(f"{len(active_vms)} active VM(s)")
            vm_count.setObjectName("mutedLabel")
            badges.addWidget(vm_count)
            layout.addLayout(badges)

            ram = QLabel(f"RAM {host.get('ram_free_mib', 0)} / {host.get('ram_total_mib', 0)} MiB free · Disk {host.get('disk_free_mib', 0)} MiB free")
            ram.setObjectName("mutedLabel")
            layout.addWidget(ram)

            preview = ", ".join(str(vm) for vm in active_vms[:3])
            if len(active_vms) > 3:
                preview += f" +{len(active_vms) - 3} more"
            inventory = QLabel(preview if preview else "No VM inventory reported")
            inventory.setObjectName("mutedLabel")
            inventory.setWordWrap(True)
            layout.addWidget(inventory)

        heartbeat = QLabel(f"last seen {host.get('last_seen') or 'unknown'}")
        heartbeat.setObjectName("mutedLabel")
        layout.addWidget(heartbeat)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        test_button = self._button("Test Host", lambda checked=False, hid=host_id: self._queue_host_test(hid))
        test_button.setEnabled(not offline)
        view_button = self._button("View VMs", lambda checked=False, hid=host_id: self._view_host_vms(hid))
        target_button = self._button("Use as Migration Target", lambda checked=False, hid=host_id: self._hint_migration_target(hid))
        target_button.setEnabled(not offline)
        actions.addWidget(test_button)
        actions.addWidget(view_button)
        actions.addWidget(target_button)
        actions.addStretch()
        layout.addLayout(actions)
        return card

    def _hint_migration_target(self, host_id: str) -> None:
        self._dashboard_go_vms()
        self.status.showMessage(f"Select a VM and use Live Migration with target host {host_id}", 8000)

    def _view_host_vms(self, host_id: str) -> None:
        local_host_id = effective_config()["host_id"].value
        if host_id == local_host_id:
            self._dashboard_go_vms()
            return
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return {"vms": RegistryClient(url).list_vms(host_id)}
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            f"Loading VM inventory for {host_id}",
            fetch,
            on_success=lambda result: self._show_remote_vms_dialog(host_id, result),
            refresh_after=False,
            busy=False,
        )

    def _show_remote_vms_dialog(self, host_id: str, result: dict[str, Any]) -> None:
        error = str((result or {}).get("error") or "")
        if error:
            self.show_error(f"Cannot load VM inventory for {host_id}: {error}")
            return
        vms = list((result or {}).get("vms") or [])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"VMs on {host_id}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        title = QLabel(f"VM inventory · {host_id}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel(
            "Inventory reported by that host's agent. Remote power commands are executed by the target "
            "host agent (App → Hub → Agent → libvirt). Remote console arrives in v0.8.x/v0.9; remote "
            "delete is intentionally not supported. Reboot/Reset is not available yet (no safe backend)."
        )
        note.setObjectName("calloutInfo")
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(len(vms), 6)
        table.setObjectName("remoteVmsTable")
        table.setHorizontalHeaderLabels(["Name", "State", "Lab", "RAM (MiB)", "vCPUs", "Host"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        empty = QLabel("No VM inventory reported for this host yet (the agent reports it on each heartbeat).")
        empty.setObjectName("mutedLabel")
        empty.setWordWrap(True)
        layout.addWidget(empty)

        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setMaximumHeight(190)
        detail.setPlaceholderText("Select a remote VM to see its details.")
        layout.addWidget(detail)

        power_status = QLabel("Select a VM to enable remote power actions.")
        power_status.setObjectName("mutedLabel")
        power_status.setWordWrap(True)
        layout.addWidget(power_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        start_button = QPushButton("Start")
        shutdown_button = QPushButton("ACPI Shutdown")
        force_off_button = QPushButton("Force Off")
        force_off_button.setObjectName("dangerButton")
        refresh_button = QPushButton("Refresh")
        console_button = QPushButton("Console")
        console_button.setEnabled(False)
        console_button.setToolTip("Remote console arrives later — not available in v0.8.")
        for button in (start_button, shutdown_button, force_off_button):
            button.setEnabled(False)
        actions.addWidget(start_button)
        actions.addWidget(shutdown_button)
        actions.addWidget(force_off_button)
        actions.addWidget(refresh_button)
        actions.addWidget(console_button)
        actions.addStretch()
        close_button = QPushButton("Close")
        actions.addWidget(close_button)
        layout.addLayout(actions)

        dialog.host_id = host_id
        self._remote_vms_dialog = dialog
        self.remote_vms_table = table
        self.remote_vm_detail = detail
        self.remote_power_status = power_status
        self.remote_vm_start_button = start_button
        self.remote_vm_shutdown_button = shutdown_button
        self.remote_vm_force_off_button = force_off_button
        self.remote_vm_refresh_button = refresh_button
        self._remote_vms = []
        self._remote_power_poll_timer = QTimer(dialog)
        self._remote_power_poll_timer.setInterval(3000)
        self._remote_power_poll_timer.timeout.connect(self._poll_remote_power_command)
        self._remote_power_command_id = ""
        self._remote_power_poll_running = False

        table.itemSelectionChanged.connect(self._update_remote_power_buttons)
        start_button.clicked.connect(lambda: self._queue_remote_power_action("start"))
        shutdown_button.clicked.connect(lambda: self._queue_remote_power_action("shutdown"))
        force_off_button.clicked.connect(lambda: self._queue_remote_power_action("force_off"))
        refresh_button.clicked.connect(self._refresh_remote_vms)
        close_button.clicked.connect(dialog.accept)
        dialog.finished.connect(self._remote_power_poll_timer.stop)

        self._populate_remote_vms_table(vms)
        dialog.resize(720, 460)
        dialog.show()

    def _populate_remote_vms_table(self, vms: list[dict[str, Any]]) -> None:
        dialog = getattr(self, "_remote_vms_dialog", None)
        if dialog is None:
            return
        table = self.remote_vms_table
        self._remote_vms = list(vms)
        host_id = str(getattr(dialog, "host_id", ""))
        table.setRowCount(len(vms))
        for row, vm in enumerate(vms):
            state = str(vm.get("state") or "unknown")
            cells = (
                str(vm.get("vm_name") or vm.get("name") or ""),
                state.upper(),
                str(vm.get("lab_id") or ""),
                str(vm.get("ram_mib") or ""),
                str(vm.get("vcpus") or ""),
                host_id,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 1:
                    item.setForeground(QColor(STATE_COLORS.get(state.replace(" ", ""), "#94A3B8")))
                table.setItem(row, column, item)
        # The empty-state hint is the widget right below the table.
        for label in dialog.findChildren(QLabel):
            if label.text().startswith("No VM inventory reported"):
                label.setVisible(not vms)
        self._update_remote_power_buttons()

    def _selected_remote_vm(self) -> dict[str, Any] | None:
        table = getattr(self, "remote_vms_table", None)
        if table is None:
            return None
        row = table.currentRow()
        if row < 0 or row >= len(self._remote_vms):
            return None
        return self._remote_vms[row]

    REMOTE_INVENTORY_STALE_SECONDS = 180

    @staticmethod
    def _iso_age_seconds(timestamp: str) -> float | None:
        try:
            parsed = datetime.fromisoformat(str(timestamp))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - parsed).total_seconds())

    def _remote_host_name(self, host_id: str) -> str:
        for host in self.remote_hosts:
            if str(host.get("host_id") or "") == host_id:
                return str(host.get("name") or host.get("hostname") or "")
        return ""

    def _render_remote_vm_details(self) -> None:
        detail = getattr(self, "remote_vm_detail", None)
        if detail is None:
            return
        vm = self._selected_remote_vm()
        if vm is None:
            detail.setPlainText("")
            return
        dialog = getattr(self, "_remote_vms_dialog", None)
        host_id = str(getattr(dialog, "host_id", "")) if dialog is not None else ""
        updated_at = str(vm.get("updated_at") or "")
        age_seconds = self._iso_age_seconds(updated_at)
        lines: list[str] = []
        if age_seconds is None or age_seconds > self.REMOTE_INVENTORY_STALE_SECONDS:
            age_text = f"{int(age_seconds // 60)} min old" if age_seconds is not None else "of unknown age"
            lines.append(
                f"⚠ Inventory data may be stale ({age_text}). "
                "The agent refreshes it on each heartbeat — check that the agent is running."
            )
        disk_paths = [str(item) for item in (vm.get("disk_paths") or []) if item]
        iso_paths = [str(item) for item in (vm.get("iso_paths") or []) if item]
        networks = [str(item) for item in (vm.get("networks") or []) if item]
        macs = [str(item) for item in (vm.get("macs") or []) if item]
        lines.append(
            details_block(
                ("VM name", str(vm.get("vm_name") or vm.get("name") or "")),
                ("Host ID", host_id),
                ("Host name", self._remote_host_name(host_id) or "unknown"),
                ("State", str(vm.get("state") or "unknown")),
                ("Lab", str(vm.get("lab_id") or "unknown")),
                ("RAM", format_mib(vm.get("ram_mib"))),
                ("vCPUs", str(vm.get("vcpus") or "unknown")),
                ("Disks", ", ".join(disk_paths) if disk_paths else "none reported"),
                ("ISOs", ", ".join(iso_paths) if iso_paths else "none"),
                ("Display", str(vm.get("display") or "unknown").upper()),
                ("MACs", ", ".join(macs) if macs else "not reported"),
                ("Networks", ", ".join(networks) if networks else "not reported"),
                ("Last inventory update", updated_at or "unknown"),
                ("Inventory source", "Hub (reported by the host agent on each heartbeat)"),
            )
        )
        detail.setPlainText("\n".join(lines))

    def _update_remote_power_buttons(self) -> None:
        vm = self._selected_remote_vm()
        self._render_remote_vm_details()
        if vm is None:
            for button in (self.remote_vm_start_button, self.remote_vm_shutdown_button, self.remote_vm_force_off_button):
                button.setEnabled(False)
            return
        state = str(vm.get("state") or "unknown").lower()
        running_like = state in {"running", "paused"}
        shut_off = state in {"shut off", "shutoff"}
        self.remote_vm_start_button.setEnabled(shut_off)
        self.remote_vm_shutdown_button.setEnabled(running_like)
        # Force Off also covers stuck/unknown states; it always asks first.
        self.remote_vm_force_off_button.setEnabled(running_like or state == "unknown")

    def _queue_remote_power_action(self, action: str) -> None:
        dialog = getattr(self, "_remote_vms_dialog", None)
        vm = self._selected_remote_vm()
        if dialog is None or vm is None:
            return
        host_id = str(getattr(dialog, "host_id", ""))
        vm_name = str(vm.get("vm_name") or vm.get("name") or "")
        if action == "force_off":
            answer = QMessageBox.question(
                dialog,
                "Force Off VM",
                f"Force Off may corrupt guest data on {vm_name}. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        url = self.registry_url()

        def queue_command() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return RegistryClient(url).queue_vm_power_command(host_id, vm_name, action)
            except Exception as exc:
                return {"error": str(exc)}

        def on_queued(result: dict[str, Any]) -> None:
            error = str((result or {}).get("error") or "")
            if error:
                self.remote_power_status.setText(f"Cannot queue {action} for {vm_name}: {error}")
                return
            command_id = str((result or {}).get("command_id") or "")
            self._remote_power_command_id = command_id
            self.remote_power_status.setText(
                f"Command queued: {command_id} ({action} {vm_name}). Waiting for the target host agent..."
            )
            self.log_activity(f"Queued remote {action} for {vm_name} on {host_id}: {command_id}")
            self._remote_power_poll_timer.start()

        self.run_operation(
            f"Queueing remote {action} for {vm_name} on {host_id}",
            queue_command,
            on_success=on_queued,
            refresh_after=False,
            busy=False,
        )

    def _poll_remote_power_command(self) -> None:
        command_id = self._remote_power_command_id
        if not command_id or self._remote_power_poll_running:
            return
        self._remote_power_poll_running = True
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return RegistryClient(url).command(command_id)
            except Exception as exc:
                return {"error": str(exc)}

        def on_status(result: dict[str, Any]) -> None:
            self._remote_power_poll_running = False
            error = str((result or {}).get("error") or "")
            if error:
                self.remote_power_status.setText(f"Cannot read command {command_id}: {error}")
                return
            status = str((result or {}).get("status") or "")
            if status not in {"done", "failed"}:
                self.remote_power_status.setText(f"Command {command_id}: {status or 'pending'}...")
                return
            self._remote_power_poll_timer.stop()
            self._remote_power_command_id = ""
            payload = (result or {}).get("result") or {}
            message = str(payload.get("message") or payload.get("error") or "")
            if status == "done":
                self.remote_power_status.setText(f"Command {command_id} done. {message}".strip())
                self.log_activity(f"Remote command done: {command_id}. {message}".strip())
            else:
                self.remote_power_status.setText(f"Command {command_id} FAILED. {message}".strip())
                self.log_activity(f"Remote command FAILED: {command_id}. {message}".strip())
            self._refresh_remote_vms()

        self.run_operation(
            f"Checking remote command {command_id}",
            fetch,
            on_success=on_status,
            refresh_after=False,
            busy=False,
        )

    def _refresh_remote_vms(self) -> None:
        dialog = getattr(self, "_remote_vms_dialog", None)
        if dialog is None:
            return
        host_id = str(getattr(dialog, "host_id", ""))
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return {"vms": RegistryClient(url).list_vms(host_id)}
            except Exception as exc:
                return {"error": str(exc)}

        def on_loaded(result: dict[str, Any]) -> None:
            error = str((result or {}).get("error") or "")
            if error:
                self.remote_power_status.setText(f"Cannot refresh inventory for {host_id}: {error}")
                return
            self._populate_remote_vms_table(list((result or {}).get("vms") or []))

        self.run_operation(
            f"Refreshing VM inventory for {host_id}",
            fetch,
            on_success=on_loaded,
            refresh_after=False,
            busy=False,
        )

    def _render_host_cards(self, hosts: list[dict[str, Any]]) -> None:
        self._clear_remote_cards()
        if not hosts:
            self.remote_cards_layout.addWidget(
                self._remote_message_panel(
                    "No hosts registered yet",
                    "Start a HyperGery Agent on another machine to register it with the Hub.",
                ),
                0,
                0,
            )
            return
        for index, host in enumerate(hosts):
            card = self._host_card(host, index)
            self._host_card_frames.append(card)
            self.remote_cards_layout.addWidget(card, index // 2, index % 2)
        self.remote_cards_layout.setRowStretch((len(hosts) - 1) // 2 + 1, 1)

    def render_hub_offline(self, error: str) -> None:
        self._clear_remote_cards()
        self.remote_cards_layout.addWidget(
            self._remote_message_panel(
                "Hub not reachable",
                "Start docker compose in docker/ or check HYPERGERY_HUB_URL.\n\n" + error,
                action=("Open Settings", self.app_settings),
            ),
            0,
            0,
        )

    def _queue_host_test(self, host_id: str) -> None:
        def do_test() -> dict:
            from ..registry import RegistryClient

            return RegistryClient(self.registry_url()).create_command(host_id, "ping", {})

        def on_done(result: dict) -> None:
            self.remote_detail.setPlainText(
                details_block(
                    ("Hub", self.registry_url()),
                    ("Host", host_id),
                    ("Queued command", str(result.get("command_id", ""))),
                    ("Status", str(result.get("status", ""))),
                )
            )
            self.log_activity(f"Queued remote host test for {host_id}: {result.get('command_id', '')}")

        self.run_operation(f"Testing remote host {host_id}", do_test, on_success=on_done, refresh_after=False)

    DOCTOR_GROUPS = (
        ("Local Virtualization", ("/dev/kvm", "user groups", "libvirt")),
        ("Tooling", ("python", "qemu-img", "virsh", "virt-viewer")),
        ("Hub & Agent", ("hub url", "host id", "hub reachable")),
        ("NAS", ("nas staging path",)),
        ("Docker", ("docker folder", "docker compose")),
        ("VM Inventory", ("hub vm inventory",)),
    )

    def _build_diagnostics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Diagnostics")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Doctor checks for KVM, libvirt, Hub, NAS and tooling — read-only, nothing is changed.")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.copy_report_button = self._button("Copy Report", self.copy_doctor_report)
        self.copy_report_button.setEnabled(False)
        troubleshooting_button = self._button("Open Troubleshooting", self.open_troubleshooting)
        self.run_doctor_button = self._button("Run Doctor", self.run_doctor, primary=True)
        header.addWidget(self.copy_report_button)
        header.addWidget(troubleshooting_button)
        header.addWidget(self.run_doctor_button)
        layout.addLayout(header)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.diag_ok_chip = QLabel("— OK")
        self.diag_ok_chip.setObjectName("statusChip")
        self.diag_warn_chip = QLabel("— WARN")
        self.diag_warn_chip.setObjectName("statusChip")
        self.diag_fail_chip = QLabel("— FAIL")
        self.diag_fail_chip.setObjectName("statusChip")
        self.diag_overall_label = QLabel("Doctor has not run yet.")
        self.diag_overall_label.setObjectName("mutedLabel")
        summary.addWidget(self.diag_ok_chip)
        summary.addWidget(self.diag_warn_chip)
        summary.addWidget(self.diag_fail_chip)
        summary.addStretch()
        summary.addWidget(self.diag_overall_label)
        layout.addLayout(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.diag_results_layout = QVBoxLayout(body)
        self.diag_results_layout.setContentsMargins(0, 0, 0, 0)
        self.diag_results_layout.setSpacing(12)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self._doctor_items: list[Any] = []
        self._diag_show_message(
            "Run Doctor to check your environment",
            "Doctor inspects /dev/kvm, user groups, libvirt, QEMU tooling, Hub reachability, NAS staging, and Docker Compose without changing the system.",
        )
        return page

    def _clear_diag_results(self) -> None:
        while self.diag_results_layout.count():
            item = self.diag_results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _diag_show_message(self, title: str, body: str) -> None:
        self._clear_diag_results()
        self.diag_results_layout.addWidget(self._remote_message_panel(title, body))
        self.diag_results_layout.addStretch()

    def run_doctor(self) -> None:
        self.run_doctor_button.setEnabled(False)
        self._diag_show_message("Running diagnostics…", "Checking KVM, libvirt, tooling, Hub, NAS, and Docker. This can take a few seconds if the Hub is unreachable.")

        def collect() -> dict[str, Any]:
            from ..doctor import collect_doctor_items, doctor_exit_code

            try:
                items = collect_doctor_items()
                return {"items": items, "exit_code": doctor_exit_code(items)}
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Running doctor diagnostics",
            collect,
            on_success=self.render_doctor_results,
            refresh_after=False,
            busy=False,
        )

    def render_doctor_results(self, result: dict[str, Any]) -> None:
        self.run_doctor_button.setEnabled(True)
        if result.get("error"):
            self._doctor_items = []
            self.copy_report_button.setEnabled(False)
            for chip, text in ((self.diag_ok_chip, "— OK"), (self.diag_warn_chip, "— WARN"), (self.diag_fail_chip, "— FAIL")):
                chip.setText(text)
                chip.setObjectName("statusChip")
                chip.style().unpolish(chip)
                chip.style().polish(chip)
            self.diag_overall_label.setText("Doctor failed to run.")
            self._clear_diag_results()
            error_label = QLabel(f"Doctor failed to run: {result['error']}")
            error_label.setObjectName("calloutDanger")
            error_label.setWordWrap(True)
            self.diag_results_layout.addWidget(error_label)
            self.diag_results_layout.addStretch()
            return
        items = result.get("items") or []
        self._doctor_items = items
        self.copy_report_button.setEnabled(bool(items))
        counts = {"OK": 0, "WARN": 0, "FAIL": 0}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        for chip, key, tone in (
            (self.diag_ok_chip, "OK", "statusChipOk"),
            (self.diag_warn_chip, "WARN", "statusChipWarn"),
            (self.diag_fail_chip, "FAIL", "statusChipBad"),
        ):
            chip.setText(f"{counts[key]} {key}")
            chip.setObjectName(tone if counts[key] else "statusChip")
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        exit_code = result.get("exit_code", 0)
        self.diag_overall_label.setText(
            f"No critical failures · exit code 0 · {now_iso()}" if exit_code == 0
            else f"Critical failures present · exit code 1 · {now_iso()}"
        )

        self._clear_diag_results()
        remaining = list(items)
        for group_title, names in self.DOCTOR_GROUPS:
            group_items = [item for item in remaining if item.name in names]
            if not group_items:
                continue
            remaining = [item for item in remaining if item not in group_items]
            self.diag_results_layout.addWidget(self._doctor_group_card(group_title, group_items))
        if remaining:
            self.diag_results_layout.addWidget(self._doctor_group_card("Other", remaining))
        self.diag_results_layout.addStretch()

    def _doctor_group_card(self, title: str, items: list[Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        chip_names = {"OK": "statusChipOk", "WARN": "statusChipWarn", "FAIL": "statusChipBad"}
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(10)
            chip = QLabel(item.status)
            chip.setObjectName(chip_names.get(item.status, "statusChip"))
            chip.setFixedWidth(64)
            chip.setMinimumHeight(26)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(item.name + ("  · CRITICAL" if item.critical and item.status == "FAIL" else ""))
            name.setMinimumWidth(170)
            detail = QLabel(str(item.detail))
            detail.setObjectName("mutedLabel")
            detail.setWordWrap(True)
            row.addWidget(chip)
            row.addWidget(name)
            row.addWidget(detail, 1)
            layout.addLayout(row)
        return card

    def copy_doctor_report(self) -> None:
        if not self._doctor_items:
            self.status.showMessage("No diagnostics to copy yet. Run Doctor first.", 5000)
            return
        from ..doctor import doctor_exit_code, format_doctor_items

        report = format_doctor_items(self._doctor_items)
        report += f"\n\nexit code: {doctor_exit_code(self._doctor_items)} · generated {now_iso()}"
        QApplication.clipboard().setText(report)
        self.status.showMessage("Doctor report copied to clipboard", 5000)
        self.log_activity("Copied doctor report to clipboard")

    def open_troubleshooting(self) -> None:
        path = Path(__file__).resolve().parents[3] / "docs" / "TROUBLESHOOTING.md"
        if path.is_file():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            self.status.showMessage(f"Opening {path}", 5000)
        else:
            self.status.showMessage(f"Troubleshooting guide not found at {path}", 8000)

    def _stat_card(self, label: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        label_widget = QLabel(label)
        label_widget.setObjectName("statLabel")
        big = QLabel("—")
        big.setObjectName("statBig")
        sub = QLabel("")
        sub.setObjectName("mutedLabel")
        sub.setWordWrap(True)
        layout.addWidget(label_widget)
        layout.addWidget(big)
        layout.addWidget(sub)
        layout.addStretch()
        return card, big, sub

    def _set_stat_tone(self, label: QLabel, tone: str) -> None:
        label.setObjectName({"ok": "statBigOk", "bad": "statBigBad"}.get(tone, "statBig"))
        label.style().unpolish(label)
        label.style().polish(label)

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(16)

        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Local host, HyperGery Hub on the NAS, and the remote lab hosts at a glance.")
        subtitle.setObjectName("mutedLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(14)
        vm_card, self.dash_vm_big, self.dash_vm_sub = self._stat_card("VIRTUAL MACHINES")
        hub_card, self.dash_hub_big, self.dash_hub_sub = self._stat_card("HYPERGERY HUB")
        nas_card, self.dash_nas_big, self.dash_nas_sub = self._stat_card("NAS STAGING")
        hosts_card, self.dash_hosts_big, self.dash_hosts_sub = self._stat_card("HOSTS ONLINE")
        self.dash_hub_big.setText("Not checked")
        self.dash_nas_big.setText("Not checked")
        for card in (vm_card, hub_card, nas_card, hosts_card):
            stats_row.addWidget(card, 1)
        layout.addLayout(stats_row)

        quick_title = QLabel("Quick actions")
        quick_title.setObjectName("sectionTitle")
        layout.addWidget(quick_title)
        quick_grid = QGridLayout()
        quick_grid.setHorizontalSpacing(14)
        quick_grid.setVerticalSpacing(14)
        actions = (
            ("New VM", "Create from a local ISO", self.new_vm, True),
            ("New Lab", "Isolated lab network", self.new_lab, False),
            ("Open Console", "Integrated VNC console", self._dashboard_go_vms, False),
            ("Live Migration", "Hub Transfer or NAS Clone", self._dashboard_go_vms, False),
            ("Run Doctor", "Host and Hub diagnostics", self._dashboard_go_diagnostics, False),
            ("Settings", "Hub · NAS · VM defaults", self.app_settings, False),
        )
        for index, (name, sub, callback, primary) in enumerate(actions):
            quick_grid.addWidget(self._quick_card(name, sub, callback, primary=primary), index // 3, index % 3)
        layout.addLayout(quick_grid)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)

        warnings_card = QFrame()
        warnings_card.setObjectName("panel")
        warnings_layout = QVBoxLayout(warnings_card)
        warnings_layout.setContentsMargins(16, 14, 16, 14)
        warnings_layout.setSpacing(8)
        warnings_title = QLabel("Warnings")
        warnings_title.setObjectName("sectionTitle")
        warnings_layout.addWidget(warnings_title)
        self.dash_warnings_layout = QVBoxLayout()
        self.dash_warnings_layout.setSpacing(8)
        warnings_layout.addLayout(self.dash_warnings_layout)
        warnings_layout.addStretch()
        initial = QLabel("Hub and NAS state not checked yet. Select Refresh to load it.")
        initial.setObjectName("calloutInfo")
        initial.setWordWrap(True)
        self.dash_warnings_layout.addWidget(initial)

        migration_card = QFrame()
        migration_card.setObjectName("panel")
        migration_layout = QVBoxLayout(migration_card)
        migration_layout.setContentsMargins(16, 14, 16, 14)
        migration_layout.setSpacing(8)
        migration_title = QLabel("Last migration")
        migration_title.setObjectName("sectionTitle")
        self.dash_migration_label = QLabel("No migrations recorded yet.")
        self.dash_migration_label.setObjectName("mutedLabel")
        self.dash_migration_label.setWordWrap(True)
        migration_note = QLabel("Migrations (Hub Transfer or NAS Clone) keep the source VM untouched; UUID and MAC are regenerated on the target.")
        migration_note.setObjectName("mutedLabel")
        migration_note.setWordWrap(True)
        migration_layout.addWidget(migration_title)
        migration_layout.addWidget(self.dash_migration_label)
        migration_layout.addWidget(migration_note)
        migration_layout.addStretch()

        bottom_row.addWidget(warnings_card, 3)
        bottom_row.addWidget(migration_card, 2)
        layout.addLayout(bottom_row)
        layout.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)
        return page

    def _dashboard_go_vms(self) -> None:
        self.sidebar_nav.setCurrentRow(self.SIDEBAR_SECTIONS.index("Virtual Machines"))

    def _dashboard_go_diagnostics(self) -> None:
        self.sidebar_nav.setCurrentRow(self.SIDEBAR_SECTIONS.index("Diagnostics"))

    def update_dashboard_vms(self) -> None:
        counts = {"running": 0, "shutoff": 0, "paused": 0, "unknown": 0}
        for vm in self.all_vms:
            counts[state_kind(vm.state)] += 1
        self.dash_vm_big.setText(str(counts["running"]))
        self._set_stat_tone(self.dash_vm_big, "ok" if counts["running"] else "")
        self.dash_vm_sub.setText(
            f"running · {counts['shutoff']} shutoff · {counts['paused']} paused · {len(self.all_vms)} total"
        )

    def update_dashboard_hub(self, hosts: list[dict[str, Any]], *, reachable: bool, vm_count: int | None, nas_writable: bool, nas_path: str) -> None:
        self.dash_hub_big.setText("Online" if reachable else "Offline")
        self._set_stat_tone(self.dash_hub_big, "ok" if reachable else "bad")
        records = "unknown" if vm_count is None else f"{vm_count} VM record(s)"
        self.dash_hub_sub.setText(f"{self.registry_url()} · {records}" if reachable else self.registry_url())
        self.dash_nas_big.setText("Writable" if nas_writable else "Not writable")
        self._set_stat_tone(self.dash_nas_big, "ok" if nas_writable else "bad")
        self.dash_nas_sub.setText(nas_path)
        online = sum(1 for host in hosts if host.get("status") == "online")
        self.dash_hosts_big.setText(f"{online} / {len(hosts)}" if hosts else "0")
        self._set_stat_tone(self.dash_hosts_big, "ok" if hosts and online == len(hosts) else "")
        offline_ids = [str(host.get("host_id") or "?") for host in hosts if host.get("status") != "online"]
        self.dash_hosts_sub.setText(
            "all hosts operational" if hosts and not offline_ids
            else (", ".join(offline_ids) + " offline" if offline_ids else "no hosts registered")
        )
        self._update_dashboard_warnings(reachable=reachable, nas_writable=nas_writable, offline_ids=offline_ids)

    def _update_dashboard_warnings(self, *, reachable: bool, nas_writable: bool, offline_ids: list[str]) -> None:
        while self.dash_warnings_layout.count():
            item = self.dash_warnings_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        def callout(text: str, tone: str) -> None:
            label = QLabel(text)
            label.setObjectName(tone)
            label.setWordWrap(True)
            self.dash_warnings_layout.addWidget(label)
        if not reachable:
            callout("HyperGery Hub is not responding. Check HYPERGERY_HUB_URL and that the Docker container is healthy.", "calloutWarn")
        if not nas_writable:
            callout("NAS staging is not writable. Mount the NAS share before packaging migrations.", "calloutWarn")
        for host_id in offline_ids:
            callout(f"{host_id} is offline. It is not available as a migration target.", "calloutWarn")
        if reachable and nas_writable and not offline_ids:
            callout("No warnings. Hub and NAS staging are operational.", "calloutOk")

    def update_dashboard_migration(self, migrations: list[dict[str, Any]]) -> None:
        if not migrations:
            self.dash_migration_label.setText("No migrations recorded yet.")
            return
        last = migrations[-1]
        migration_id = str(last.get("migration_id") or "?")
        status = str(last.get("status") or "unknown")
        vm_name = str(last.get("vm_name") or last.get("source_vm_name") or "?")
        self.dash_migration_label.setText(f"{migration_id}\n{vm_name} · status: {status}")

    # ------------------------------------------------------------------ #
    # Labs workspace (v0.8)                                               #
    # ------------------------------------------------------------------ #

    LAB_WS_TABLE_COLUMNS = ("Name", "Role", "State", "Host", "RAM", "vCPUs", "Location")

    def _build_labs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Labs")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Lab workspaces: grouped VMs across local and remote hosts")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.lab_ws_new_button = self._button("New Lab", self.new_lab, primary=True)
        self.lab_ws_refresh_button = self._button("Refresh", self.refresh_all)
        header.addWidget(self.lab_ws_new_button)
        header.addWidget(self.lab_ws_refresh_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_body = QWidget()
        self.lab_ws_cards_layout = QVBoxLayout(cards_body)
        self.lab_ws_cards_layout.setContentsMargins(0, 0, 8, 0)
        self.lab_ws_cards_layout.setSpacing(10)
        cards_scroll.setWidget(cards_body)
        splitter.addWidget(cards_scroll)

        detail = QFrame()
        detail.setObjectName("panel")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 14, 16, 14)
        detail_layout.setSpacing(8)
        self.lab_ws_title = QLabel("No lab selected")
        self.lab_ws_title.setObjectName("sectionTitle")
        self.lab_ws_meta = QLabel("")
        self.lab_ws_meta.setObjectName("mutedLabel")
        self.lab_ws_meta.setWordWrap(True)
        self.lab_ws_status_label = QLabel("")
        self.lab_ws_status_label.setObjectName("mutedLabel")
        self.lab_ws_status_label.setWordWrap(True)
        self.lab_ws_hosts_label = QLabel("")
        self.lab_ws_hosts_label.setObjectName("mutedLabel")
        self.lab_ws_hosts_label.setWordWrap(True)
        detail_layout.addWidget(self.lab_ws_title)
        detail_layout.addWidget(self.lab_ws_meta)
        detail_layout.addWidget(self.lab_ws_status_label)
        detail_layout.addWidget(self.lab_ws_hosts_label)

        self.lab_ws_vm_table = QTableWidget(0, len(self.LAB_WS_TABLE_COLUMNS))
        self.lab_ws_vm_table.setHorizontalHeaderLabels(list(self.LAB_WS_TABLE_COLUMNS))
        self.lab_ws_vm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lab_ws_vm_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lab_ws_vm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_ws_vm_table.setAlternatingRowColors(True)
        self.lab_ws_vm_table.verticalHeader().setVisible(False)
        self.lab_ws_vm_table.horizontalHeader().setStretchLastSection(True)
        self.lab_ws_vm_table.itemSelectionChanged.connect(self._update_lab_ws_buttons)
        detail_layout.addWidget(self.lab_ws_vm_table, 1)

        vm_actions = QHBoxLayout()
        vm_actions.setSpacing(8)
        self.lab_ws_open_vm_button = self._button("Open VM", self.lab_ws_open_vm)
        self.lab_ws_view_remote_button = self._button("View Remote VM", self.lab_ws_view_remote_vm)
        self.lab_ws_migrate_button = self._button("Migrate VM", self.lab_ws_migrate_vm)
        self.lab_ws_role_button = self._button("Set VM Role…", self.lab_ws_set_role)
        for button in (
            self.lab_ws_open_vm_button,
            self.lab_ws_view_remote_button,
            self.lab_ws_migrate_button,
            self.lab_ws_role_button,
        ):
            vm_actions.addWidget(button)
        vm_actions.addStretch()
        detail_layout.addLayout(vm_actions)

        lab_actions = QHBoxLayout()
        lab_actions.setSpacing(8)
        self.lab_ws_start_button = self._button("Start Lab", self.start_lab, primary=True)
        self.lab_ws_shutdown_button = self._button("Shutdown Lab", self.shutdown_lab)
        self.lab_ws_snapshot_button = QPushButton("Snapshot Lab")
        self.lab_ws_snapshot_button.setEnabled(False)
        self.lab_ws_snapshot_button.setToolTip(
            "Planned — lab-wide snapshots are not available yet. Use per-VM Snapshots in Virtual Machines."
        )
        lab_actions.addWidget(self.lab_ws_start_button)
        lab_actions.addWidget(self.lab_ws_shutdown_button)
        lab_actions.addWidget(self.lab_ws_snapshot_button)
        lab_actions.addStretch()
        detail_layout.addLayout(lab_actions)

        self.lab_ws_feedback = QLabel(
            "Start Lab starts every shut off VM in the lab (local backend or Hub → Agent for remote VMs). "
            "Shutdown Lab sends ACPI shutdown to every running VM. There is no lab-wide Force Off."
        )
        self.lab_ws_feedback.setObjectName("calloutInfo")
        self.lab_ws_feedback.setWordWrap(True)
        detail_layout.addWidget(self.lab_ws_feedback)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._lab_ws_card_frames: list[QFrame] = []
        self.selected_workspace_lab_id = ""
        self._lab_ws_vms: list[dict[str, Any]] = []
        return page

    def _local_host_id(self) -> str:
        return str(effective_config()["host_id"].value)

    def _clear_lab_ws_cards(self) -> None:
        self._lab_ws_card_frames = []
        while self.lab_ws_cards_layout.count():
            item = self.lab_ws_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _lab_ws_card(self, lab: dict[str, Any]) -> QFrame:
        lab_id = str(lab.get("lab_id", ""))
        selected = lab_id == self.selected_workspace_lab_id
        card = QFrame()
        card.setObjectName("hostCardSelected" if selected else "hostCard")
        card.mousePressEvent = lambda event, lid=lab_id: self._select_workspace_lab(lid)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        title = QLabel(str(lab.get("name") or lab_id))
        title.setObjectName("sectionTitle")
        meta = QLabel(f"{lab_id} · {lab.get('network_mode', 'nat')} · {lab.get('subnet', '')}")
        meta.setObjectName("mutedLabel")
        summary = lab_status_summary(self._workspace_unified_vms(lab))
        counts = summary["counts"]
        chips = QLabel(
            f"{counts['total']} VM(s) · {counts['running']} running · {counts['shut_off']} shut off"
            + (f" · {counts['paused']} paused" if counts["paused"] else "")
            + (f" · {counts['not_created']} not created" if counts["not_created"] else "")
            + (f" · {counts['unknown']} unknown" if counts["unknown"] else "")
        )
        chips.setObjectName("mutedLabel")
        chips.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(meta)
        layout.addWidget(chips)
        if lab.get("description"):
            description = QLabel(str(lab.get("description")))
            description.setObjectName("mutedLabel")
            description.setWordWrap(True)
            layout.addWidget(description)
        return card

    def _workspace_unified_vms(self, lab: dict[str, Any]) -> list[dict[str, Any]]:
        return unify_lab_vms(lab, self.all_vms, self.remote_vms_inventory, self._local_host_id())

    def _selected_workspace_lab(self) -> dict[str, Any] | None:
        for lab in self.labs:
            if str(lab.get("lab_id", "")) == self.selected_workspace_lab_id:
                return lab
        return None

    def _select_workspace_lab(self, lab_id: str) -> None:
        self.selected_workspace_lab_id = lab_id
        self.render_labs_workspace()

    def render_labs_workspace(self) -> None:
        if not hasattr(self, "lab_ws_cards_layout"):
            return
        labs = self.labs
        if labs and not any(str(lab.get("lab_id", "")) == self.selected_workspace_lab_id for lab in labs):
            self.selected_workspace_lab_id = str(labs[0].get("lab_id", ""))
        self._clear_lab_ws_cards()
        if not labs:
            self.lab_ws_cards_layout.addWidget(
                self._remote_message_panel(
                    "No labs yet",
                    "Create VMs in default-lab or create a new lab.",
                    action=("New Lab", self.new_lab),
                )
            )
            self.lab_ws_cards_layout.addStretch()
            self._render_lab_ws_detail(None)
            return
        for lab in labs:
            card = self._lab_ws_card(lab)
            self._lab_ws_card_frames.append(card)
            self.lab_ws_cards_layout.addWidget(card)
        self.lab_ws_cards_layout.addStretch()
        self._render_lab_ws_detail(self._selected_workspace_lab())

    def _render_lab_ws_detail(self, lab: dict[str, Any] | None) -> None:
        if lab is None:
            self.lab_ws_title.setText("No lab selected")
            self.lab_ws_meta.setText("")
            self.lab_ws_status_label.setText("")
            self.lab_ws_hosts_label.setText("")
            self.lab_ws_vm_table.setRowCount(0)
            self._lab_ws_vms = []
            self._update_lab_ws_buttons()
            return
        lab_id = str(lab.get("lab_id", ""))
        self.lab_ws_title.setText(str(lab.get("name") or lab_id))
        description = str(lab.get("description") or "")
        self.lab_ws_meta.setText(
            f"{lab_id} · {lab.get('network_mode', 'nat')} · subnet {lab.get('subnet', '')} · "
            f"bridge {lab.get('bridge_name', '')}"
            + (f"\n{description}" if description else "")
        )
        unified = self._workspace_unified_vms(lab)
        self._lab_ws_vms = unified
        summary = lab_status_summary(unified)
        counts = summary["counts"]
        self.lab_ws_status_label.setText(
            f"Status: {counts['total']} VM(s) · {counts['running']} running · "
            f"{counts['shut_off']} shut off · {counts['paused']} paused · "
            f"{counts['unknown']} unknown · {counts['not_created']} not created"
        )
        hosts = summary["hosts"]
        if hosts:
            parts = [f"{host_id}: {len(names)} VM(s)" for host_id, names in sorted(hosts.items())]
            self.lab_ws_hosts_label.setText("Host distribution — " + " · ".join(parts))
        else:
            self.lab_ws_hosts_label.setText("Host distribution — no live VMs yet")
        self.lab_ws_vm_table.setRowCount(len(unified))
        local_host_id = self._local_host_id()
        for row, vm in enumerate(unified):
            location = "Local" if (not vm["remote"] and vm["host_id"] == local_host_id) else ("Remote" if vm["remote"] else "—")
            cells = (
                vm["name"],
                vm["role"] or "—",
                vm["state"].upper(),
                vm["host_id"] or "—",
                format_mib(vm["ram_mib"]) if vm["ram_mib"] else "—",
                str(vm["vcpus"] or "—"),
                location,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 2:
                    item.setForeground(QColor(STATE_COLORS.get(state_kind(vm["state"]), "#94A3B8")))
                self.lab_ws_vm_table.setItem(row, column, item)
        self._update_lab_ws_buttons()

    def _selected_lab_ws_vm(self) -> dict[str, Any] | None:
        row = self.lab_ws_vm_table.currentRow()
        if row < 0 or row >= len(self._lab_ws_vms):
            return None
        return self._lab_ws_vms[row]

    def _update_lab_ws_buttons(self) -> None:
        lab = self._selected_workspace_lab()
        vm = self._selected_lab_ws_vm()
        has_lab = lab is not None
        is_local = vm is not None and not vm["remote"] and vm["state"] != "not created"
        is_remote = vm is not None and vm["remote"]
        self.lab_ws_open_vm_button.setEnabled(is_local)
        self.lab_ws_view_remote_button.setEnabled(is_remote)
        self.lab_ws_migrate_button.setEnabled(is_local)
        self.lab_ws_role_button.setEnabled(has_lab and vm is not None)
        self.lab_ws_start_button.setEnabled(has_lab and any(v["state"] == "shut off" for v in self._lab_ws_vms))
        self.lab_ws_shutdown_button.setEnabled(has_lab and any(v["state"] == "running" for v in self._lab_ws_vms))

    def lab_ws_open_vm(self) -> None:
        vm = self._selected_lab_ws_vm()
        if vm is None or vm["remote"]:
            return
        self._dashboard_go_vms()
        self.vm_filter.setCurrentIndex(0)
        self._select_vm_by_name(vm["name"])

    def lab_ws_view_remote_vm(self) -> None:
        vm = self._selected_lab_ws_vm()
        if vm is None or not vm["remote"]:
            return
        self._view_host_vms(vm["host_id"])

    def lab_ws_migrate_vm(self) -> None:
        vm = self._selected_lab_ws_vm()
        if vm is None or vm["remote"]:
            return
        self._dashboard_go_vms()
        self.vm_filter.setCurrentIndex(0)
        self._select_vm_by_name(vm["name"])
        if self.selected_vm is not None and self.selected_vm.name == vm["name"]:
            self.live_migration_vm()
        else:
            self.status.showMessage(f"Select {vm['name']} in Virtual Machines, then use Live Migration", 8000)

    def lab_ws_set_role(self) -> None:
        lab = self._selected_workspace_lab()
        vm = self._selected_lab_ws_vm()
        if lab is None or vm is None:
            return
        options = ["(no role)"] + list(LAB_VM_ROLES)
        current = vm["role"] if vm["role"] in LAB_VM_ROLES else "(no role)"
        choice, ok = QInputDialog.getItem(
            self,
            "Set VM Role",
            f"Role for {vm['name']} in {lab.get('lab_id', '')}:",
            options,
            options.index(current),
            False,
        )
        if not ok:
            return
        role = "" if choice == "(no role)" else choice
        try:
            self.lab_store().set_vm_role(str(lab["lab_id"]), vm["name"], role)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.log_activity(f"Set role '{role or 'none'}' for {vm['name']} in lab {lab.get('lab_id', '')}")
        self.refresh_labs()
        self.render_labs_workspace()

    def start_lab(self) -> None:
        self._confirm_and_run_lab_power("start")

    def shutdown_lab(self) -> None:
        self._confirm_and_run_lab_power("shutdown")

    def _confirm_and_run_lab_power(self, action: str) -> None:
        lab = self._selected_workspace_lab()
        if lab is None:
            self.show_error("Select a lab first.")
            return
        plan = plan_lab_power_action(self._workspace_unified_vms(lab), action)
        targets = plan["targets"]
        if not targets:
            self.lab_ws_feedback.setText(
                f"Nothing to {action}: no VMs in the required state ("
                + ("shut off" if action == "start" else "running")
                + ")."
            )
            return
        if action == "start":
            question = f"This will start {len(targets)} VM(s) across {plan['host_count']} host(s)."
        else:
            question = f"This will request ACPI shutdown for {len(targets)} running VM(s)."
        names = ", ".join(vm["name"] for vm in targets[:8]) + ("…" if len(targets) > 8 else "")
        answer = QMessageBox.question(
            self,
            f"{action.capitalize()} Lab",
            f"{question}\n\nVMs: {names}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._execute_lab_power(str(lab.get("lab_id", "")), action, targets)

    def _execute_lab_power(self, lab_id: str, action: str, targets: list[dict[str, Any]]) -> None:
        url = self.registry_url()
        backend = self.backend
        local_method = "start_vm" if action == "start" else "shutdown_vm"

        def run() -> dict[str, Any]:
            from ..registry import RegistryClient

            results: dict[str, list[str]] = {"local": [], "queued": [], "errors": []}
            client: RegistryClient | None = None
            for vm in targets:
                try:
                    if vm["remote"]:
                        if client is None:
                            client = RegistryClient(url)
                        command = client.queue_vm_power_command(vm["host_id"], vm["name"], action)
                        results["queued"].append(f"{vm['name']}@{vm['host_id']} ({command.get('command_id', '')})")
                    else:
                        getattr(backend, local_method)(vm["name"])
                        results["local"].append(vm["name"])
                except Exception as exc:
                    results["errors"].append(f"{vm['name']}: {exc}")
            return results

        def on_done(results: dict[str, Any]) -> None:
            local = results.get("local") or []
            queued = results.get("queued") or []
            errors = results.get("errors") or []
            lines = [f"Lab {lab_id} {action}:"]
            if local:
                lines.append(f"  {len(local)} local VM(s): {', '.join(local)}")
            if queued:
                lines.append(f"  {len(queued)} remote command(s) queued: {', '.join(queued)}")
            if errors:
                lines.append(f"  {len(errors)} FAILED: {'; '.join(errors)}")
            summary = "\n".join(lines)
            self.lab_ws_feedback.setText(summary)
            self.lab_ws_feedback.setObjectName("calloutDanger" if errors else "calloutOk")
            self.lab_ws_feedback.style().unpolish(self.lab_ws_feedback)
            self.lab_ws_feedback.style().polish(self.lab_ws_feedback)
            self.log_activity(summary.replace("\n", " · "))
            self.refresh_all()

        self.log_activity(f"Lab {action} requested for {lab_id}: {len(targets)} VM(s)")
        self.run_operation(
            f"{'Starting' if action == 'start' else 'Shutting down'} lab {lab_id}",
            run,
            on_success=on_done,
            refresh_after=False,
            busy=False,
        )

    MIGRATIONS_TABLE_COLUMNS = ("Migration ID", "Source VM", "Target VM", "Source → Target", "Strategy", "Status", "Updated")

    def _build_migrations_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("Migrations")
        title.setObjectName("pageTitle")
        subtitle = QLabel("NAS package history and migration status")
        subtitle.setObjectName("mutedLabel")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.migrations_refresh_button = QPushButton("Refresh")
        self.migrations_refresh_button.clicked.connect(self.refresh_migrations)
        open_migration = QPushButton("Open Live Migration")
        open_migration.setObjectName("primaryButton")
        open_migration.clicked.connect(self._open_live_migration_from_page)
        header.addWidget(self.migrations_refresh_button)
        header.addWidget(open_migration)
        layout.addLayout(header)

        self.migrations_status_label = QLabel("History not loaded yet — press Refresh or open this section again.")
        self.migrations_status_label.setObjectName("mutedLabel")
        self.migrations_status_label.setWordWrap(True)
        layout.addWidget(self.migrations_status_label)

        self.migrations_table = QTableWidget(0, len(self.MIGRATIONS_TABLE_COLUMNS))
        self.migrations_table.setHorizontalHeaderLabels(list(self.MIGRATIONS_TABLE_COLUMNS))
        self.migrations_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.migrations_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.migrations_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.migrations_table.verticalHeader().setVisible(False)
        self.migrations_table.horizontalHeader().setStretchLastSection(True)
        self.migrations_table.itemSelectionChanged.connect(self._update_migration_copy_buttons)
        layout.addWidget(self.migrations_table, 1)

        actions = QHBoxLayout()
        self.copy_migration_id_button = QPushButton("Copy Migration ID")
        self.copy_migration_id_button.setEnabled(False)
        self.copy_migration_id_button.clicked.connect(self.copy_selected_migration_id)
        self.copy_migration_summary_button = QPushButton("Copy Summary")
        self.copy_migration_summary_button.setEnabled(False)
        self.copy_migration_summary_button.clicked.connect(self.copy_selected_migration_summary)
        actions.addWidget(self.copy_migration_id_button)
        actions.addWidget(self.copy_migration_summary_button)
        actions.addStretch()
        layout.addLayout(actions)

        safety = QLabel(
            "History is read-only: migration records are never deleted from this page. "
            "Source VMs are never touched by migrations."
        )
        safety.setObjectName("calloutInfo")
        safety.setWordWrap(True)
        layout.addWidget(safety)
        layout.addWidget(self._build_hub_staging_panel())
        self.migrations_history: list[dict[str, Any]] = []
        self._migrations_loaded = False
        return page

    def _build_hub_staging_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Hub Staging Maintenance")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        hours_label = QLabel("Older than (hours):")
        hours_label.setObjectName("mutedLabel")
        self.staging_hours_spin = QSpinBox()
        self.staging_hours_spin.setRange(1, 720)
        self.staging_hours_spin.setValue(24)
        self.staging_refresh_button = self._button("Refresh Staging", self.refresh_hub_staging)
        self.staging_dry_run_button = self._button("Dry Run Cleanup", self.dry_run_hub_cleanup)
        self.staging_cleanup_button = self._button("Cleanup Confirmed", self.confirm_hub_cleanup, danger=True)
        header.addWidget(hours_label)
        header.addWidget(self.staging_hours_spin)
        header.addWidget(self.staging_refresh_button)
        header.addWidget(self.staging_dry_run_button)
        header.addWidget(self.staging_cleanup_button)
        layout.addLayout(header)

        self.staging_stats_label = QLabel("Staging not loaded yet — press Refresh Staging.")
        self.staging_stats_label.setObjectName("mutedLabel")
        self.staging_stats_label.setWordWrap(True)
        layout.addWidget(self.staging_stats_label)

        self.staging_detail = QTextEdit()
        self.staging_detail.setReadOnly(True)
        self.staging_detail.setMaximumHeight(150)
        self.staging_detail.setPlaceholderText(
            "Staged packages and cleanup previews appear here. Run Dry Run Cleanup to see candidates."
        )
        layout.addWidget(self.staging_detail)

        staging_safety = QLabel(
            "Only temporary Hub staging packages are deleted. VMs and imported disks are never touched."
        )
        staging_safety.setObjectName("calloutInfo")
        staging_safety.setWordWrap(True)
        layout.addWidget(staging_safety)
        return panel

    @staticmethod
    def _format_size(size_bytes: int | float) -> str:
        size = float(size_bytes or 0)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024 or unit == "GiB":
                return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{int(size)} B"

    HUB_OFFLINE_STAGING_MESSAGE = "Hub not reachable. Check the NAS Hub and HYPERGERY_HUB_URL."

    def refresh_hub_staging(self) -> None:
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return RegistryClient(url).list_staged_packages()
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Loading Hub staging packages",
            fetch,
            on_success=self.render_hub_staging,
            refresh_after=False,
            busy=False,
        )

    def render_hub_staging(self, result: dict[str, Any]) -> None:
        error = str((result or {}).get("error") or "")
        if error:
            self.staging_stats_label.setText(f"{self.HUB_OFFLINE_STAGING_MESSAGE}\n{error}")
            return
        packages = list((result or {}).get("packages") or [])
        orphans = int((result or {}).get("orphan_count") or 0)
        total = self._format_size((result or {}).get("total_size_bytes") or 0)
        oldest = max((float(p.get("age_hours") or 0) for p in packages), default=0.0)
        self.staging_stats_label.setText(
            f"Staging path: {result.get('staging_dir', '')} · "
            f"{len(packages)} package(s) · {total} · {orphans} orphan(s) · "
            f"oldest {oldest:.1f}h"
        )
        if not packages:
            self.staging_detail.setPlainText("No staged packages found.")
            return
        lines = []
        for package in packages:
            status = package.get("migration_status") or "no migration record (orphan)"
            lines.append(
                f"{package.get('migration_id', '')} · {self._format_size(package.get('size_bytes') or 0)} · "
                f"{package.get('file_count', 0)} file(s) · {package.get('age_hours', 0)}h · {status}"
            )
        self.staging_detail.setPlainText("\n".join(lines))

    def _run_hub_cleanup(self, *, dry_run: bool) -> None:
        url = self.registry_url()
        hours = int(self.staging_hours_spin.value())

        def cleanup() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return RegistryClient(url).cleanup_staging(older_than_hours=hours, dry_run=dry_run)
            except Exception as exc:
                return {"error": str(exc)}

        label = "Previewing Hub staging cleanup" if dry_run else "Cleaning Hub staging packages"
        self.run_operation(
            label,
            cleanup,
            on_success=self.render_hub_cleanup_result,
            refresh_after=False,
            busy=False,
        )

    def dry_run_hub_cleanup(self) -> None:
        self._run_hub_cleanup(dry_run=True)

    def confirm_hub_cleanup(self) -> None:
        hours = int(self.staging_hours_spin.value())
        answer = QMessageBox.warning(
            self,
            "Cleanup Hub Staging",
            (
                f"Delete leftover Hub staging packages older than {hours}h?\n\n"
                "Only temporary Hub staging packages are deleted. "
                "VMs and imported disks are never touched.\n\n"
                "Packages of active migrations are always kept."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_hub_cleanup(dry_run=False)

    def render_hub_cleanup_result(self, result: dict[str, Any]) -> None:
        error = str((result or {}).get("error") or "")
        if error:
            self.staging_detail.setPlainText(f"{self.HUB_OFFLINE_STAGING_MESSAGE}\n{error}")
            return
        dry_run = bool(result.get("dry_run"))
        candidates = list(result.get("candidates") or [])
        skipped = list(result.get("skipped") or [])
        errors = list(result.get("errors") or [])
        lines = ["DRY RUN — nothing was deleted." if dry_run else "CLEANUP EXECUTED."]
        lines.append(
            f"{len(candidates)} candidate(s) · {self._format_size(result.get('total_size_bytes') or 0)} "
            f"(older than {result.get('older_than_hours', '?')}h)"
        )
        for candidate in candidates:
            lines.append(
                f"  - {candidate.get('migration_id', '')} "
                f"({self._format_size(candidate.get('size_bytes') or 0)}): {candidate.get('reason', '')}"
            )
        if not candidates:
            lines.append("  No cleanup candidates found.")
        if skipped:
            lines.append(f"{len(skipped)} skipped:")
            for item in skipped:
                lines.append(f"  - {item.get('migration_id', '')}: {item.get('reason', '')}")
        if not dry_run:
            lines.append(
                f"Deleted {result.get('deleted_count', 0)} package(s), "
                f"freed {self._format_size(result.get('deleted_size_bytes') or 0)}."
            )
        for item in errors:
            lines.append(f"ERROR {item.get('migration_id', '')}: {item.get('error', '')}")
        self.staging_detail.setPlainText("\n".join(lines))
        if not dry_run:
            self.log_activity(
                f"Hub staging cleanup done: {result.get('deleted_count', 0)} deleted, "
                f"{len(errors)} error(s)"
            )
            self.refresh_hub_staging()

    def refresh_migrations(self) -> None:
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return {"migrations": RegistryClient(url).list_migrations()}
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Loading migration history",
            fetch,
            on_success=self.render_migrations,
            refresh_after=False,
            busy=False,
        )

    def render_migrations(self, result: dict[str, Any]) -> None:
        self._migrations_loaded = True
        error = str((result or {}).get("error") or "")
        if error:
            self.migrations_table.setRowCount(0)
            self.migrations_history = []
            self.migrations_status_label.setText(f"Hub not reachable: {error}")
            self._update_migration_copy_buttons()
            return
        migrations = list((result or {}).get("migrations") or [])
        self.migrations_history = migrations
        self.migrations_table.setRowCount(len(migrations))
        for row, record in enumerate(migrations):
            status = str(record.get("status") or "unknown")
            cells = (
                str(record.get("migration_id") or ""),
                str(record.get("source_vm_name") or ""),
                str(record.get("target_vm_name") or ""),
                f"{record.get('source_host_id') or '?'} → {record.get('target_host_id') or '?'}",
                str(record.get("strategy") or ""),
                status.upper(),
                str(record.get("updated_at") or ""),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 5:
                    status_colors = {"done": "#22C55E", "failed": "#EF4444"}
                    item.setForeground(QColor(status_colors.get(status, "#F59E0B")))
                self.migrations_table.setItem(row, column, item)
        if migrations:
            done = sum(1 for record in migrations if record.get("status") == "done")
            failed = sum(1 for record in migrations if record.get("status") == "failed")
            self.migrations_status_label.setText(
                f"{len(migrations)} migration(s) on the Hub · {done} done · {failed} failed"
            )
        else:
            self.migrations_status_label.setText("No migrations recorded on the Hub yet.")
        self._update_migration_copy_buttons()

    def _selected_migration(self) -> dict[str, Any] | None:
        row = self.migrations_table.currentRow()
        if row < 0 or row >= len(self.migrations_history):
            return None
        return self.migrations_history[row]

    def _update_migration_copy_buttons(self) -> None:
        enabled = self._selected_migration() is not None
        self.copy_migration_id_button.setEnabled(enabled)
        self.copy_migration_summary_button.setEnabled(enabled)

    def copy_selected_migration_id(self) -> None:
        record = self._selected_migration()
        if not record:
            return
        QApplication.clipboard().setText(str(record.get("migration_id") or ""))
        self.status.showMessage("Migration ID copied", 4000)

    def copy_selected_migration_summary(self) -> None:
        record = self._selected_migration()
        if not record:
            return
        errors = record.get("errors") or []
        lines = [
            f"migration_id: {record.get('migration_id', '')}",
            f"status: {record.get('status', '')}",
            f"strategy: {record.get('strategy', '')}",
            f"source: {record.get('source_host_id', '')} / {record.get('source_vm_name', '')}",
            f"target: {record.get('target_host_id', '')} / {record.get('target_vm_name', '')}",
            f"package: {record.get('package_path', '')}",
            f"updated: {record.get('updated_at', '')}",
            f"errors: {'; '.join(str(item) for item in errors) if errors else 'none'}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.status.showMessage("Migration summary copied", 4000)

    COMMANDS_TABLE_COLUMNS = ("Command ID", "Host", "Type", "Status", "Created", "Age", "Payload", "Result")
    COMMAND_FILTERS = ("All", "Pending", "Running", "Done", "Failed", "Power commands", "Migration commands")
    MIGRATION_COMMAND_TYPES = {"receive_vm_package", "import_vm_package", "migration_status"}

    def _build_commands_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("Commands")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Hub command queue — remote power, migration, and diagnostic commands (read-only)")
        subtitle.setObjectName("mutedLabel")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.commands_filter = QComboBox()
        self.commands_filter.addItems(list(self.COMMAND_FILTERS))
        self.commands_filter.currentIndexChanged.connect(self._apply_commands_filter)
        self.commands_refresh_button = self._button("Refresh", self.refresh_commands)
        header.addWidget(self.commands_filter)
        header.addWidget(self.commands_refresh_button)
        layout.addLayout(header)

        self.commands_status_label = QLabel("Commands not loaded yet — press Refresh or open this section again.")
        self.commands_status_label.setObjectName("mutedLabel")
        self.commands_status_label.setWordWrap(True)
        layout.addWidget(self.commands_status_label)

        self.commands_table = QTableWidget(0, len(self.COMMANDS_TABLE_COLUMNS))
        self.commands_table.setHorizontalHeaderLabels(list(self.COMMANDS_TABLE_COLUMNS))
        self.commands_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.commands_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.commands_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.commands_table.setAlternatingRowColors(True)
        self.commands_table.verticalHeader().setVisible(False)
        self.commands_table.horizontalHeader().setStretchLastSection(True)
        self.commands_table.setColumnWidth(0, 230)
        self.commands_table.itemSelectionChanged.connect(self._update_command_copy_buttons)
        layout.addWidget(self.commands_table, 1)

        actions = QHBoxLayout()
        self.copy_command_id_button = QPushButton("Copy Command ID")
        self.copy_command_id_button.setEnabled(False)
        self.copy_command_id_button.clicked.connect(self.copy_selected_command_id)
        self.copy_command_result_button = QPushButton("Copy Result")
        self.copy_command_result_button.setEnabled(False)
        self.copy_command_result_button.clicked.connect(self.copy_selected_command_result)
        actions.addWidget(self.copy_command_id_button)
        actions.addWidget(self.copy_command_result_button)
        actions.addStretch()
        layout.addLayout(actions)

        safety = QLabel(
            "Read-only view: commands cannot be requeued, deleted, or executed from this page. "
            "Remote power actions live in Remote Hosts → View VMs."
        )
        safety.setObjectName("calloutInfo")
        safety.setWordWrap(True)
        layout.addWidget(safety)

        self.commands_history: list[dict[str, Any]] = []
        self.commands_visible: list[dict[str, Any]] = []
        self._commands_loaded = False
        return page

    def refresh_commands(self) -> None:
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return {"commands": RegistryClient(url).list_commands(limit=200)}
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Loading Hub command queue",
            fetch,
            on_success=self.render_commands,
            refresh_after=False,
            busy=False,
        )

    def render_commands(self, result: dict[str, Any]) -> None:
        self._commands_loaded = True
        error = str((result or {}).get("error") or "")
        if error:
            self.commands_history = []
            self._apply_commands_filter()
            self.commands_status_label.setText(f"Hub not reachable: {error}")
            return
        self.commands_history = list((result or {}).get("commands") or [])
        self._apply_commands_filter()

    def _filtered_commands(self) -> list[dict[str, Any]]:
        selected = self.commands_filter.currentText()
        commands = self.commands_history
        if selected in {"Pending", "Running", "Done", "Failed"}:
            return [item for item in commands if str(item.get("status") or "") == selected.lower()]
        if selected == "Power commands":
            return [item for item in commands if str(item.get("command_type") or "").startswith("vm_")]
        if selected == "Migration commands":
            return [item for item in commands if str(item.get("command_type") or "") in self.MIGRATION_COMMAND_TYPES]
        return list(commands)

    @staticmethod
    def _summarize_command_value(value: Any, limit: int = 80) -> str:
        if not value:
            return "—"
        if isinstance(value, dict):
            text = str(value.get("message") or value.get("error") or json.dumps(value, sort_keys=True))
        else:
            text = str(value)
        return text[: limit - 1] + "…" if len(text) > limit else text

    def _command_age_text(self, command: dict[str, Any]) -> str:
        age_seconds = self._iso_age_seconds(str(command.get("created_at") or ""))
        if age_seconds is None:
            return "—"
        if age_seconds < 90:
            return f"{int(age_seconds)}s"
        if age_seconds < 5400:
            return f"{int(age_seconds // 60)}m"
        return f"{age_seconds / 3600:.1f}h"

    COMMAND_STATUS_COLORS = {"done": "#22C55E", "failed": "#EF4444", "running": "#3B82F6"}

    def _apply_commands_filter(self) -> None:
        commands = self._filtered_commands()
        self.commands_visible = commands
        self.commands_table.setRowCount(len(commands))
        for row, command in enumerate(commands):
            status = str(command.get("status") or "unknown")
            cells = (
                str(command.get("command_id") or ""),
                str(command.get("target_host_id") or ""),
                str(command.get("command_type") or ""),
                status.upper(),
                str(command.get("created_at") or ""),
                self._command_age_text(command),
                self._summarize_command_value(command.get("payload")),
                self._summarize_command_value(command.get("result")),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setForeground(QColor(self.COMMAND_STATUS_COLORS.get(status, "#F59E0B")))
                self.commands_table.setItem(row, column, item)
        if self.commands_history:
            counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for command in self.commands_history:
                key = str(command.get("status") or "")
                if key in counts:
                    counts[key] += 1
            self.commands_status_label.setText(
                f"{len(commands)} shown / {len(self.commands_history)} command(s) on the Hub · "
                f"{counts['pending']} pending · {counts['running']} running · "
                f"{counts['done']} done · {counts['failed']} failed"
            )
        else:
            self.commands_status_label.setText("No commands recorded on the Hub yet.")
        self._update_command_copy_buttons()

    def _selected_command(self) -> dict[str, Any] | None:
        row = self.commands_table.currentRow()
        if row < 0 or row >= len(self.commands_visible):
            return None
        return self.commands_visible[row]

    def _update_command_copy_buttons(self) -> None:
        enabled = self._selected_command() is not None
        self.copy_command_id_button.setEnabled(enabled)
        self.copy_command_result_button.setEnabled(enabled)

    def copy_selected_command_id(self) -> None:
        command = self._selected_command()
        if not command:
            return
        QApplication.clipboard().setText(str(command.get("command_id") or ""))
        self.status.showMessage("Command ID copied", 4000)

    def copy_selected_command_result(self) -> None:
        command = self._selected_command()
        if not command:
            return
        QApplication.clipboard().setText(json.dumps(command.get("result") or {}, indent=2, sort_keys=True))
        self.status.showMessage("Command result copied", 4000)

    def _open_live_migration_from_page(self) -> None:
        if self.selected_vm is not None:
            self.live_migration_vm()
            return
        self._dashboard_go_vms()
        self.status.showMessage("Select a VM, then use Live Migration", 6000)

    def _placeholder_page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("placeholderTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("mutedLabel")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addStretch()
        return page

    def _build_vm_empty_state(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        self.vm_empty_title = QLabel("No virtual machines yet")
        self.vm_empty_title.setObjectName("heroTitle")
        self.vm_empty_subtitle = QLabel("Create your first VM from an ISO.")
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
        for name in ("General", "System", "Console", "Storage", "Network", "Snapshots", "Logs"):
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
            self.app_settings_button,
            self.start_button,
            self.shutdown_button,
            self.console_button,
            self.external_console_button,
            self.snapshots_button,
            self.clone_button,
            self.migrate_button,
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
            self.refresh_remote_button,
            self.test_remote_button,
            self.staging_refresh_button,
            self.staging_dry_run_button,
            self.staging_cleanup_button,
            self.commands_refresh_button,
            self.lab_ws_new_button,
            self.lab_ws_refresh_button,
            self.lab_ws_start_button,
            self.lab_ws_shutdown_button,
            self.lab_ws_open_vm_button,
            self.lab_ws_view_remote_button,
            self.lab_ws_migrate_button,
            self.lab_ws_role_button,
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
        self.external_console_button.setEnabled(has_vm and running)
        self.snapshots_button.setEnabled(has_vm)
        self.clone_button.setEnabled(has_vm and shut_off)
        self.migrate_button.setEnabled(has_vm)
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
        self.test_remote_button.setEnabled(self.selected_remote_host_index is not None)
        if hasattr(self, "lab_ws_vm_table"):
            self._update_lab_ws_buttons()

    def registry_url(self) -> str:
        return effective_value("hub_url")

    def refresh_remote_hosts(self) -> None:
        self.run_operation(
            "Loading remote hosts",
            self._load_remote_hosts,
            on_success=self.render_remote_hosts,
            refresh_after=False,
        )

    def _load_remote_hosts(self) -> dict[str, Any]:
        from ..registry import RegistryClient

        import time

        client = RegistryClient(self.registry_url())
        try:
            started = time.perf_counter()
            client.health()
            latency_ms: int | None = int((time.perf_counter() - started) * 1000)
        except Exception:
            latency_ms = None
        hosts = client.list_hosts()
        try:
            remote_vms: list[dict[str, Any]] | None = client.list_vms()
            vm_count: int | None = len(remote_vms)
        except Exception:
            remote_vms = None
            vm_count = None
        try:
            migrations: list[dict[str, Any]] = client.list_migrations()
        except Exception:
            migrations = []
        return {
            "hosts": hosts,
            "vm_count": vm_count,
            "remote_vms": remote_vms,
            "migrations": migrations,
            "latency_ms": latency_ms,
        }

    def render_remote_hosts(self, result: dict[str, Any] | list[dict[str, Any]]) -> None:
        latency_ms: int | None = None
        if isinstance(result, dict):
            hosts = result.get("hosts", [])
            vm_count = result.get("vm_count")
            latency_ms = result.get("latency_ms")
            if result.get("remote_vms") is not None:
                self.remote_vms_inventory = list(result.get("remote_vms") or [])
            self.update_dashboard_migration(result.get("migrations") or [])
        else:
            hosts = result
            vm_count = None
        self.remote_hosts = hosts
        self.render_labs_workspace()
        self._render_host_cards(hosts)
        self.hub_latency_label.setText(f"{latency_ms} ms" if latency_ms is not None else "—")
        self.remote_status_label.setText(f"{len(hosts)} host(s)")
        if hosts:
            self.remote_detail.setPlainText(details_block(("Hub", self.registry_url()), ("Status", "reachable")))
        else:
            self.remote_detail.setPlainText(
                "Hub is reachable but has no hosts. Start a HyperGery agent on each participating host."
            )
        self.render_hub_status(hosts, reachable=True, vm_count=vm_count)
        self.update_actions()

    def render_hub_status(self, hosts: list[dict[str, Any]], *, reachable: bool, vm_count: int | None = None) -> None:
        config = effective_config()
        nas_path = os.path.expanduser(config["nas_staging_path"].value)
        nas_label = f"{nas_path} writable={os.path.isdir(nas_path) and os.access(nas_path, os.W_OK)}"
        vm_count_label = "unknown"
        if reachable:
            vm_count_label = str(vm_count) if vm_count is not None else "unavailable"
        self.hub_url_label.setText(self.registry_url())
        self.hub_status_label.setText("ONLINE" if reachable else "OFFLINE")
        self.hub_status_label.setObjectName("statusChipOk" if reachable else "statusChipBad")
        self.hub_status_label.style().unpolish(self.hub_status_label)
        self.hub_status_label.style().polish(self.hub_status_label)
        self.hub_card.setObjectName("hubCard" if reachable else "hubCardOffline")
        self.hub_card.style().unpolish(self.hub_card)
        self.hub_card.style().polish(self.hub_card)
        self.hub_last_check_label.setText(now_iso())
        self.hub_hosts_online_label.setText(str(sum(1 for host in hosts if host.get("status") == "online")))
        self.hub_vm_count_label.setText(vm_count_label)
        self.hub_nas_label.setText(nas_label)
        nas_writable = os.path.isdir(nas_path) and os.access(nas_path, os.W_OK)
        self.hub_chip.setText(f"Hub: {'online' if reachable else 'offline'}")
        self.hub_chip.setObjectName("statusChipOk" if reachable else "statusChipBad")
        self.nas_chip.setText(f"NAS: {'writable' if nas_writable else 'not writable'}")
        self.nas_chip.setObjectName("statusChipOk" if nas_writable else "statusChipBad")
        self.host_chip.setText(f"Host: {config['host_id'].value}")
        for chip in (self.hub_chip, self.nas_chip):
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self.update_dashboard_hub(
            hosts,
            reachable=reachable,
            vm_count=vm_count,
            nas_writable=nas_writable,
            nas_path=nas_path,
        )

    def test_selected_remote_host(self) -> None:
        index = self.selected_remote_host_index
        if index is None:
            self.show_error("Select a remote host first.")
            return
        host = self.remote_hosts[index] if 0 <= index < len(self.remote_hosts) else None
        if not host:
            self.show_error("Selected host is no longer available.")
            return
        self._queue_host_test(str(host.get("host_id", "")))

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
            ("remote_hosts", self._load_remote_hosts),
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
        if "remote_hosts" in overview:
            self.render_remote_hosts(overview["remote_hosts"])
        elif "remote_hosts" in errors:
            self.remote_hosts = []
            self.render_hub_offline(str(errors["remote_hosts"]))
            self.remote_status_label.setText("Hub unavailable")
            self.hub_latency_label.setText("—")
            self.render_hub_status([], reachable=False)
            self.remote_detail.setPlainText(
                "Hub not reachable. Set HYPERGERY_HUB_URL or start docker compose in docker/.\n"
                f"Current Hub URL: {self.registry_url()}\n"
                f"Example: export HYPERGERY_HUB_URL=http://192.168.1.150:8765\n\n{errors['remote_hosts']}"
            )
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
        self.update_dashboard_vms()
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
            self._set_table_item(self.vm_table, row, 5, vm.disk_virtual or "—")
            self._set_table_item(self.vm_table, row, 6, (vm.graphics or "—").upper() if vm.graphics else "—")
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
            self.vm_empty_subtitle.setText("Create your first VM from an ISO.")
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
        self.render_labs_workspace()
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
        self.detail_views["Console"].setPlainText(
            details_block(
                ("Display", (vm.graphics or "unknown").upper()),
                ("Integrated console", "available (VNC)" if vm.graphics == "vnc" else "not available — requires VNC"),
                ("External viewer", "virt-viewer or remote-viewer"),
                ("Host Key", "Right Ctrl"),
                ("Close behavior", "closing the console window does not stop the VM"),
            )
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

    def app_settings(self) -> None:
        dialog = AppSettingsDialog(self.backend, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            HyperGeryConfig(**dialog.values()).save()
        except (OSError, HyperGeryError, ValueError) as exc:
            self.show_error(f"Cannot save HyperGery settings: {exc}")
            return
        self.status.showMessage("HyperGery settings saved", 5000)

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
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        vm = self.selected_vm
        window = self.console_windows.get(vm.name)
        if window is None:
            window = VmConsoleWindow(self.backend, vm, self, on_vm_changed=lambda _name: self.refresh_all())
            window.destroyed.connect(lambda _=None, name=vm.name: self.console_windows.pop(name, None))
            self.console_windows[vm.name] = window
        else:
            window.set_vm(vm)
        window.show()
        window.raise_()
        window.activateWindow()
        if should_autoconnect_console(vm.graphics, vm.state) and not window.console.is_connected():
            window.console.connect_console()

    def open_external_console(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Opening external console for {name}", lambda: self.backend.open_console(name))

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

    def live_migration_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Select a VM first.")
            return
        dialog = LiveMigrationDialog(self.backend, self.selected_vm, self)
        dialog.exec()
        if dialog.last_result:
            self.log_activity(
                "Remote migration queued: "
                f"migration_id={dialog.last_result.get('migration_id', '')} "
                f"command_id={dialog.last_result.get('command_id', '')} "
                f"package={dialog.last_result.get('package_dir', '')}"
            )

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
