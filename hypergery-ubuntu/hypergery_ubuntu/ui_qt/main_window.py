from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPixmap, QTextCursor
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
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
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
    GpuPassthroughDialog,
    InstantiateLabTemplateWizard,
    LiveMigrationDialog,
    NewLabDialog,
    NewLabTemplateDialog,
    NewVmTemplateDialog,
    RenameLabDialog,
    SettingsDialog,
    SnapshotDialog,
    VBoxStyleVMCreator,
    VMWizard,
    confirm,
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
from .humanize import (
    V1_TAB_TITLES,
    humanize_activity_log,
    humanize_command_status,
    humanize_command_type,
    humanize_command_value,
    humanize_error,
    humanize_error_message,
    humanize_lab_action,
    humanize_network_label,
    humanize_v1,
    humanize_vm_status,
)
from .topology import LabTopologyWidget
from .vm_tree import VmTree
from .detail_panel import VmDetailPanel
from . import v1_render
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
from .jobs import JobManager
from .workers import BackendJob


class MainWindow(QMainWindow):
    # Mínimo intervalo entre dos capturas reales de preview de una misma VM
    # (HG-BUG-0015): virsh screenshot es caro (subprocess, hasta 8 s).
    PREVIEW_MIN_INTERVAL_S = 2.0
    # Espera acotada a los jobs en curso al cerrar la ventana (HG-BUG-0008).
    CLOSE_WAIT_MS = 5000

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
        self._remote_console_windows: list[VmConsoleWindow] = []
        self.job_manager = JobManager(self)
        self._preview_target: str | None = None
        self._preview_inflight: set[str] = set()
        self._preview_last_capture: dict[str, float] = {}
        self._preview_retry_pending: set[str] = set()
        self._preview_clock = time.monotonic
        self.setWindowTitle(f"HyperGery v{APP_DISPLAY_VERSION}")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        QTimer.singleShot(0, self.refresh_all)
        # Evacuación por batería: vigila el nivel cada minuto y, al entrar en
        # «offload» descargando, ofrece pasar las VMs encendidas a otro equipo.
        from .evacuation import EvacuationMonitor

        self._evac_monitor = EvacuationMonitor()
        self._evac_dialog_open = False
        self._battery_mode = "recommend_only"
        self._battery_timer = QTimer(self)
        self._battery_timer.timeout.connect(self._battery_tick)
        self._battery_timer.start(60_000)

    def _build_ui(self) -> None:
        # Botones "fantasma": set_busy/update_actions los referencian, pero las
        # acciones ahora viven en el menú y la barra de herramientas.
        self.new_button = self._button("Nueva máquina", self.new_vm, primary=True)
        self.refresh_button = self._button("Actualizar", self.refresh_all)
        self.app_settings_button = self._button("Ajustes", self.app_settings)
        for ghost in (self.new_button, self.refresh_button, self.app_settings_button):
            ghost.hide()

        self._build_tool_bar()
        self._build_menu_bar()

        # La ventana es ahora el «manager» de VMs estilo VirtualBox: el área
        # central es directamente el conjunto de páginas (main_tabs). La página
        # «Máquinas virtuales» se construye como 3 paneles (lista | detalle |
        # previsualización) dentro de _build_left_panel.
        self.setCentralWidget(self._build_left_panel())

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._build_status_chips()
        self.status.showMessage("Listo")
        self._show_section("Máquinas virtuales")

    SIDEBAR_SECTIONS = (
        "Inicio",
        "Máquinas virtuales",
        "Laboratorios",
        "Plantillas",
        "Otros equipos",
        "Migraciones",
        "Tareas remotas",
        "Centro de control",
        "Diagnóstico",
        "Ajustes",
    )

    def _std_icon(self, name: str) -> QIcon:
        """Icono estándar de Qt por nombre de StandardPixmap (sin assets)."""
        pixmap = getattr(QStyle.StandardPixmap, name, None)
        if pixmap is None:
            return QIcon()
        return self.style().standardIcon(pixmap)

    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()
        menubar.clear()

        archivo = menubar.addMenu("&Archivo")
        act_new = archivo.addAction("Nueva máquina…", self.new_vm)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        archivo.addAction("Importar laboratorio…", self.import_lab)
        archivo.addSeparator()
        act_prefs = archivo.addAction("Ajustes…", self.app_settings)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        archivo.addSeparator()
        act_quit = archivo.addAction("Salir", self.close)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)

        maquina = menubar.addMenu("&Máquina")
        maquina.addAction(self.act_settings_vm)
        maquina.addSeparator()
        maquina.addAction(self.act_start)
        maquina.addAction(self.act_shutdown)
        maquina.addAction(self.act_force)
        maquina.addSeparator()
        maquina.addAction(self.act_console)
        maquina.addAction(self.act_ext_console)
        maquina.addAction(self.act_snapshots)
        maquina.addAction(self.act_clone)
        maquina.addAction(self.act_migrate)
        maquina.addAction(self.act_gpu)
        maquina.addSeparator()
        maquina.addAction(self.act_delete)

        ver = menubar.addMenu("&Ver")
        self._view_actions = {}
        for section in self.SIDEBAR_SECTIONS:
            if section == "Ajustes":
                continue
            action = ver.addAction(section)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, s=section: self._show_section(s))
            self._view_actions[section] = action
        ver.addSeparator()
        act_refresh = ver.addAction("Actualizar todo", self.refresh_all)
        act_refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        act_find = ver.addAction("Buscar máquina", self._focus_vm_filter)
        act_find.setShortcut(QKeySequence.StandardKey.Find)

        ayuda = menubar.addMenu("A&yuda")
        ayuda.addAction("Acerca de HyperGery", self.show_about)

    def _build_tool_bar(self) -> None:
        # Acciones de máquina (su estado lo sincroniza update_actions).
        self.act_settings_vm = QAction(self._std_icon("SP_FileDialogDetailedView"), "Configuración", self)
        self.act_settings_vm.triggered.connect(self.settings_vm)
        self.act_start = QAction(self._std_icon("SP_MediaPlay"), "Iniciar", self)
        self.act_start.triggered.connect(self.start_vm)
        self.act_shutdown = QAction(self._std_icon("SP_MediaStop"), "Apagar", self)
        self.act_shutdown.triggered.connect(self.shutdown_vm)
        self.act_force = QAction(self._std_icon("SP_BrowserStop"), "Apagar a la fuerza", self)
        self.act_force.triggered.connect(self.force_off_vm)
        self.act_console = QAction(self._std_icon("SP_ComputerIcon"), "Consola", self)
        self.act_console.triggered.connect(self.open_console)
        self.act_ext_console = QAction(self._std_icon("SP_DesktopIcon"), "Consola externa", self)
        self.act_ext_console.triggered.connect(self.open_external_console)
        self.act_snapshots = QAction(self._std_icon("SP_DialogSaveButton"), "Instantáneas", self)
        self.act_snapshots.triggered.connect(self.snapshots_vm)
        self.act_clone = QAction(self._std_icon("SP_FileDialogContentsView"), "Clonar", self)
        self.act_clone.triggered.connect(self.clone_vm)
        self.act_migrate = QAction(self._std_icon("SP_ArrowForward"), "Mover a otro equipo", self)
        self.act_migrate.triggered.connect(self.live_migration_vm)
        self.act_gpu = QAction(self._std_icon("SP_DesktopIcon"), "GPU física…", self)
        self.act_gpu.triggered.connect(self.gpu_vm)
        self.act_delete = QAction(self._std_icon("SP_TrashIcon"), "Eliminar", self)
        self.act_delete.triggered.connect(self.delete_vm)

        toolbar = QToolBar("Acciones")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(32, 32))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toolbar = toolbar
        self.addToolBar(toolbar)

        act_new = QAction(self._std_icon("SP_FileIcon"), "Nueva", self)
        act_new.triggered.connect(self.new_vm)
        toolbar.addAction(act_new)
        toolbar.addAction(self.act_settings_vm)
        toolbar.addSeparator()
        toolbar.addAction(self.act_start)
        toolbar.addAction(self.act_shutdown)
        toolbar.addAction(self.act_force)
        toolbar.addSeparator()
        toolbar.addAction(self.act_console)
        toolbar.addAction(self.act_snapshots)
        toolbar.addAction(self.act_clone)
        toolbar.addAction(self.act_migrate)
        toolbar.addSeparator()
        toolbar.addAction(self.act_delete)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        act_refresh = QAction(self._std_icon("SP_BrowserReload"), "Actualizar", self)
        act_refresh.triggered.connect(self.refresh_all)
        toolbar.addAction(act_refresh)

    def _build_status_chips(self) -> None:
        config = effective_config()
        self.host_chip = QLabel(f"Equipo: {config['host_id'].value}")
        self.hub_chip = QLabel("Hub: sin comprobar")
        self.nas_chip = QLabel("NAS: sin comprobar")
        self.battery_chip = QLabel("🔋 —")
        for chip in (self.host_chip, self.hub_chip, self.nas_chip, self.battery_chip):
            chip.setObjectName("statusChip")
            self.status.addPermanentWidget(chip)

    def _show_section(self, section: str) -> None:
        page_map = {
            "Inicio": self.dashboard_page_index,
            "Máquinas virtuales": 0,
            "Laboratorios": self.labs_page_index,
            "Plantillas": 1,
            "Otros equipos": 2,
            "Migraciones": self.migrations_page_index,
            "Tareas remotas": self.commands_page_index,
            "Centro de control": self.control_center_page_index,
            "Diagnóstico": self.diagnostics_page_index,
        }
        if section not in page_map:
            return
        self.main_tabs.setCurrentIndex(page_map[section])
        for name, action in getattr(self, "_view_actions", {}).items():
            action.setChecked(name == section)
        if section == "Migraciones" and not getattr(self, "_migrations_loaded", False):
            self.refresh_migrations()
            self.refresh_hub_staging()
        if section == "Tareas remotas" and not getattr(self, "_commands_loaded", False):
            self.refresh_commands()
        if section == "Centro de control" and not getattr(self, "_v1_loaded", False):
            self._v1_loaded = True
            self.refresh_v1_all()
        if section == "Laboratorios":
            self.render_labs_workspace()

    def _focus_vm_filter(self) -> None:
        self._show_section("Máquinas virtuales")
        if hasattr(self, "vm_filter_edit"):
            self.vm_filter_edit.setFocus()
            self.vm_filter_edit.selectAll()

    def show_about(self) -> None:
        from .. import APP_HOMEPAGE

        QMessageBox.about(
            self,
            "Acerca de HyperGery",
            f"<b>HyperGery</b> v{APP_DISPLAY_VERSION}<br>"
            "Gestor de máquinas virtuales KVM / QEMU / libvirt.<br><br>"
            "Interfaz estilo VirtualBox.<br>"
            f'<a href="{APP_HOMEPAGE}">{APP_HOMEPAGE}</a><br>'
            "Licencia: ver fichero LICENSE.",
        )

    def _update_battery_chip(self) -> dict:
        try:
            from ..v1.battery import BatteryService
            from ..v1.settings import V1Settings

            try:
                settings = V1Settings.load()
            except Exception:
                settings = V1Settings()
            self._battery_mode = getattr(settings, "battery_mode", "recommend_only")
            state = BatteryService(settings=settings).read()
            data = state.to_dict() if hasattr(state, "to_dict") else {}
            percent = data.get("percent")
            tier = data.get("tier")
            present = data.get("present", percent is not None)
            if not present or percent is None:
                self.battery_chip.setText("🔋 sin batería")
            else:
                tier_txt = f" · {tier}" if tier else ""
                self.battery_chip.setText(f"🔋 {int(round(float(percent)))}%{tier_txt}")
            return data
        except Exception:
            self.battery_chip.setText("🔋 —")
            return {}

    def _battery_tick(self) -> None:
        state = self._update_battery_chip()
        if not state or self._battery_mode == "disabled" or self._evac_dialog_open:
            return
        if self._evac_monitor.should_offer(state):
            self.offer_battery_evacuation(state)

    def offer_battery_evacuation(self, state: dict) -> None:
        """🔋 nivel «offload» descargando: pregunta si pasar las VMs encendidas
        a otro equipo (migración en vivo) y seguir usándolas en remoto."""
        from .dialogs import hub_target_candidates, live_uri_for_host
        from .evacuation import EvacuationDialog, vm_evacuation_blockers

        try:
            running = [vm for vm in self.backend.list_vms() if "running" in (vm.state or "").lower()]
        except HyperGeryError:
            return
        if not running:
            return
        vm_rows = []
        for vm in running:
            xml = vm.xml or ""
            if not xml:
                try:
                    xml = self.backend.get_vm(vm.name).xml
                except HyperGeryError:
                    xml = ""
            vm_rows.append({"name": vm.name, "blockers": vm_evacuation_blockers(xml)})
        try:
            from ..registry import RegistryClient

            hosts = RegistryClient(self.registry_url()).list_hosts()
        except Exception as exc:
            self.log_activity(f"Evacuación por batería no ofrecida: Hub no accesible ({exc})")
            return
        config = effective_config()
        candidates = hub_target_candidates(hosts, config["host_id"].value, socket.gethostname())
        self._evac_dialog_open = True
        try:
            dialog = EvacuationDialog(state.get("percent"), candidates, vm_rows, self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            target = dialog.selected_target()
            names = dialog.evacuable_names()
        finally:
            self._evac_dialog_open = False
        if not accepted or target is None or not names:
            return
        uri = live_uri_for_host(target.get("host") or {})
        if not uri:
            self.show_error("El Hub no tiene usuario/IP SSH de ese equipo; abre «Mover a otro equipo» una vez.")
            return
        self._run_battery_evacuation(names, uri)

    def _run_battery_evacuation(self, names: list[str], uri: str) -> None:
        from .evacuation import evacuate_running_vms
        from .workers import BackendJob

        self.log_activity(f"Evacuación por batería: {len(names)} VM(s) → {uri}")
        holder: dict = {}

        def work() -> dict:
            # progress emite por señal: llega al hilo de la UI encolado.
            return evacuate_running_vms(self.backend, names, uri, progress=holder["job"].progress.emit)

        job = BackendJob("battery evacuation", work)
        holder["job"] = job
        job.progress.connect(self.log_activity)
        jobs = [j for j in getattr(self, "_evac_jobs", []) if not j.isFinished()]
        jobs.append(job)
        self._evac_jobs = jobs

        def done() -> None:
            self._show_evacuation_result(job.result or {})

        def failed() -> None:
            self.show_error(f"La evacuación no pudo ejecutarse: {job.error_message}")

        job.succeeded.connect(done)
        job.failed.connect(failed)
        job.start()

    def _show_evacuation_result(self, result: dict) -> None:
        results = result.get("results") or []
        migrated = result.get("migrated") or []
        uri = result.get("target_uri", "")
        lines = []
        for entry in results:
            if entry.get("ok"):
                downtime = entry.get("downtime_ms")
                lines.append(f"✅ {entry['vm_name']} — migrada (downtime {downtime if downtime is not None else '—'} ms)")
            else:
                lines.append(f"❌ {entry['vm_name']} — sigue AQUÍ intacta: {str(entry.get('error', ''))[:160]}")
        summary = "\n".join(lines) or "No había máquinas que evacuar."
        self.refresh_all()
        if not migrated:
            QMessageBox.warning(self, "Evacuación por batería", summary)
            return
        answer = QMessageBox.question(
            self,
            "Evacuación completada",
            summary + "\n\n¿Abrir las consolas remotas de las máquinas migradas para seguir trabajando?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for name in migrated:
            try:
                self.backend.open_remote_console(name, uri)
            except HyperGeryError as exc:
                self.show_error(f"Consola remota de {name}: {exc}")
                break

    def _build_vm_actions_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.settings_button = self._button("Ajustes", self.settings_vm)
        self.start_button = self._button("Encender", self.start_vm)
        self.shutdown_button = self._button("Apagar (suave)", self.shutdown_vm)
        self.console_button = self._button("Consola", self.open_console)
        self.external_console_button = self._button("Consola externa", self.open_external_console)
        self.snapshots_button = self._button("Instantáneas", self.snapshots_vm)
        self.clone_button = self._button("Clonar", self.clone_vm)
        self.migrate_button = self._button("Mover a otro equipo", self.live_migration_vm)
        self.force_button = self._button("Apagar a la fuerza", self.force_off_vm, danger=True)
        self.delete_button = self._button("Eliminar", self.delete_vm, danger=True)
        self.overview_button = self._button("Recursos…", self.show_cleanup_preview)
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

        # Página «Máquinas virtuales» estilo VirtualBox Manager: tres paneles
        # (lista de VMs | detalles | previsualización) y una tira inferior
        # colapsable con el registro de actividad y la comprobación inicial.
        instances_tab = QWidget()
        outer = QVBoxLayout(instances_tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.vm_manager_split = QSplitter(Qt.Orientation.Horizontal)
        self.vm_manager_split.setObjectName("vmManagerSplit")
        self.vm_manager_split.addWidget(self._build_vm_list_pane())
        self.vm_manager_split.addWidget(self._build_detail_area())
        self.vm_manager_split.addWidget(self._build_preview_panel())
        self.vm_manager_split.setStretchFactor(0, 0)
        self.vm_manager_split.setStretchFactor(1, 1)
        self.vm_manager_split.setStretchFactor(2, 0)
        self.vm_manager_split.setCollapsible(0, False)
        self.vm_manager_split.setCollapsible(1, False)
        self.vm_manager_split.setSizes([290, 760, 260])
        outer.addWidget(self.vm_manager_split, 1)

        outer.addWidget(self._build_vm_bottom_strip())
        # Widgets heredados (tabla de laboratorios, acciones de lab, etiqueta de
        # selección…) que ciertos render_* y tests siguen referenciando: se
        # construyen pero quedan ocultos fuera de la vista principal VM-first.
        outer.addWidget(self._build_hidden_compat_holder())

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
        self.vm_template_table.setHorizontalHeaderLabels(["Nombre", "ID", "SO", "RAM", "vCPUs", "Disco", "Red", "Pantalla"])
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
        self.new_vm_template_button = self._button("Nueva plantilla de máquina", self.new_vm_template, primary=True)
        self.delete_vm_template_button = self._button("Eliminar", self.delete_vm_template, danger=True)
        self.edit_vm_template_button = self._button("Editar", self.edit_vm_template)
        self.edit_vm_template_button.setEnabled(False)
        self.export_vm_template_button = self._button("Exportar", self.export_vm_template)
        self.import_vm_template_button = self._button("Importar", self.import_vm_template)
        self.refresh_vm_templates_button = self._button("Actualizar", self.refresh_templates)
        self.create_vm_from_template_button = self._button("Crear máquina desde plantilla", self.create_vm_from_template, primary=True)
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
        self.vm_template_detail.setPlaceholderText("Selecciona una plantilla para ver sus detalles.")
        self.vm_template_detail.setMaximumHeight(120)
        vm_templates_layout.addWidget(self.vm_template_detail)

        self.templates_tabs.addTab(vm_templates_tab, "Plantillas de máquina")

        # --- Lab Templates Tab ---
        lab_templates_tab = QWidget()
        lab_templates_layout = QVBoxLayout(lab_templates_tab)
        lab_templates_layout.setContentsMargins(8, 8, 8, 8)
        lab_templates_layout.setSpacing(8)

        self.lab_template_table = QTableWidget(0, 5)
        self.lab_template_table.setHorizontalHeaderLabels(["Nombre", "ID", "Red", "VMs", "Notas"])
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
        self.new_lab_template_button = self._button("Nueva plantilla de laboratorio", self.new_lab_template, primary=True)
        self.delete_lab_template_button = self._button("Eliminar", self.delete_lab_template, danger=True)
        self.edit_lab_template_button = self._button("Editar", self.edit_lab_template)
        self.edit_lab_template_button.setEnabled(False)
        self.export_lab_template_button = self._button("Exportar", self.export_action_lab_template)
        self.import_lab_template_button = self._button("Importar", self.import_action_lab_template)
        self.refresh_lab_templates_button = self._button("Actualizar", self.refresh_templates)
        self.create_lab_from_template_button = self._button("Crear laboratorio desde plantilla", self.create_lab_from_template, primary=True)
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
        self.lab_template_detail.setPlaceholderText("Selecciona una plantilla de laboratorio para ver sus detalles.")
        self.lab_template_detail.setMaximumHeight(120)
        lab_templates_layout.addWidget(self.lab_template_detail)

        self.templates_tabs.addTab(lab_templates_tab, "Plantillas de laboratorio")

        self.main_tabs.addTab(templates_tab, "Plantillas")

        self.main_tabs.addTab(self._build_remote_hosts_page(), "Otros equipos")

        self.dashboard_page_index = self.main_tabs.addTab(self._build_dashboard_page(), "Inicio")
        self.labs_page_index = self.main_tabs.addTab(self._build_labs_page(), "Laboratorios")
        self.migrations_page_index = self.main_tabs.addTab(self._build_migrations_page(), "Migraciones")
        self.commands_page_index = self.main_tabs.addTab(self._build_commands_page(), "Tareas remotas")
        self.control_center_page_index = self.main_tabs.addTab(self._build_control_center_page(), "Centro de control")
        self.diagnostics_page_index = self.main_tabs.addTab(self._build_diagnostics_page(), "Diagnóstico")
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
        title = QLabel("Otros equipos")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Equipos conectados al Hub y sus máquinas")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.remote_status_label = QLabel("Hub sin cargar")
        self.remote_status_label.setObjectName("mutedLabel")
        self.refresh_remote_button = self._button("Actualizar", self.refresh_remote_hosts)
        self.test_remote_button = self._button("Probar equipo seleccionado", self.test_selected_remote_host)
        remote_settings_button = self._button("Ajustes", self.app_settings)
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
        self.hub_status_label = QLabel("sin comprobar")
        self.hub_status_label.setObjectName("statusChip")
        self.hub_url_label = QLabel(self.registry_url())
        self.hub_url_label.setObjectName("mutedLabel")
        hub_config_button = self._button("Configurar Hub", self.app_settings)
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
        self.hub_nas_label = QLabel("sin comprobar")
        self.hub_last_check_label = QLabel("—")
        for caption, value_label in (
            ("LATENCIA", self.hub_latency_label),
            ("EQUIPOS EN LÍNEA", self.hub_hosts_online_label),
            ("MÁQUINAS", self.hub_vm_count_label),
            ("ZONA NAS", self.hub_nas_label),
            ("ÚLTIMA COMPROBACIÓN", self.hub_last_check_label),
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
        self.remote_detail.setPlaceholderText("Pulsa «Actualizar» para cargar los equipos desde el Hub.")
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
        status_chip = QLabel("SIN CONEXIÓN" if offline else "EN LÍNEA")
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
            callout = QLabel(f"Sin señal desde {host.get('last_seen') or 'fecha desconocida'}. No se pueden mover máquinas a este equipo.")
            callout.setObjectName("calloutDanger")
            callout.setWordWrap(True)
            layout.addWidget(callout)
        else:
            badges = QHBoxLayout()
            badges.setSpacing(8)
            for ok, text in ((host.get("kvm_ok"), "KVM"), (host.get("libvirt_ok"), "libvirt")):
                badge = QLabel(f"{text} {'OK' if ok else 'FALLO'}")
                badge.setObjectName("statusChipOk" if ok else "statusChipBad")
                badges.addWidget(badge)
            badges.addStretch()
            active_vms = host.get("active_vms") or []
            vm_count = QLabel(f"{len(active_vms)} máquina(s) activa(s)")
            vm_count.setObjectName("mutedLabel")
            badges.addWidget(vm_count)
            layout.addLayout(badges)

            ram = QLabel(f"RAM libre: {host.get('ram_free_mib', 0)} de {host.get('ram_total_mib', 0)} MiB · Disco libre: {host.get('disk_free_mib', 0)} MiB")
            ram.setObjectName("mutedLabel")
            layout.addWidget(ram)

            preview = ", ".join(str(vm) for vm in active_vms[:3])
            if len(active_vms) > 3:
                preview += f" +{len(active_vms) - 3} más"
            inventory = QLabel(preview if preview else "Sin lista de máquinas todavía")
            inventory.setObjectName("mutedLabel")
            inventory.setWordWrap(True)
            layout.addWidget(inventory)

        heartbeat = QLabel(f"última señal: {host.get('last_seen') or 'desconocida'}")
        heartbeat.setObjectName("mutedLabel")
        layout.addWidget(heartbeat)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        test_button = self._button("Probar", lambda checked=False, hid=host_id: self._queue_host_test(hid))
        test_button.setEnabled(not offline)
        view_button = self._button("Ver máquinas", lambda checked=False, hid=host_id: self._view_host_vms(hid))
        target_button = self._button("Usar como destino", lambda checked=False, hid=host_id: self._hint_migration_target(hid))
        target_button.setEnabled(not offline)
        actions.addWidget(test_button)
        actions.addWidget(view_button)
        actions.addWidget(target_button)
        actions.addStretch()
        layout.addLayout(actions)
        return card

    def _hint_migration_target(self, host_id: str) -> None:
        self._dashboard_go_vms()
        self.status.showMessage(f"Selecciona una máquina y pulsa «Mover a otro equipo» con destino {host_id}", 8000)

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
            f"Cargando máquinas de {host_id}",
            fetch,
            on_success=lambda result: self._show_remote_vms_dialog(host_id, result),
            refresh_after=False,
            busy=False,
        )

    def _show_remote_vms_dialog(self, host_id: str, result: dict[str, Any]) -> None:
        error = str((result or {}).get("error") or "")
        if error:
            self.show_error(f"No se han podido cargar las máquinas de {host_id}: {error}")
            return
        vms = list((result or {}).get("vms") or [])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Máquinas en {host_id}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        title = QLabel(f"Máquinas · {host_id}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel(
            "Lista enviada por el agente de ese equipo. Las órdenes de encendido/apagado las ejecuta el "
            "equipo de destino (App → Hub → Agente → libvirt). Borrar máquinas en remoto no está "
            "permitido a propósito, y reiniciar aún no está disponible."
        )
        note.setObjectName("calloutInfo")
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(len(vms), 6)
        table.setObjectName("remoteVmsTable")
        table.setHorizontalHeaderLabels(["Nombre", "Estado", "Laboratorio", "RAM (MiB)", "vCPUs", "Equipo"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        empty = QLabel("Este equipo todavía no ha enviado su lista de máquinas (la envía automáticamente cada pocos segundos).")
        empty.setObjectName("mutedLabel")
        empty.setWordWrap(True)
        layout.addWidget(empty)

        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setMaximumHeight(190)
        detail.setPlaceholderText("Selecciona una máquina para ver sus detalles.")
        layout.addWidget(detail)

        power_status = QLabel("Selecciona una máquina para poder encenderla o apagarla desde aquí.")
        power_status.setObjectName("mutedLabel")
        power_status.setWordWrap(True)
        layout.addWidget(power_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        start_button = QPushButton("Encender")
        shutdown_button = QPushButton("Apagar (suave)")
        force_off_button = QPushButton("Apagar a la fuerza")
        force_off_button.setObjectName("dangerButton")
        refresh_button = QPushButton("Actualizar")
        console_button = QPushButton("Consola")
        console_button.setEnabled(False)
        console_button.setToolTip("Abre la consola gráfica de la máquina remota por SSH (virt-viewer tuneliza el display).")
        for button in (start_button, shutdown_button, force_off_button):
            button.setEnabled(False)
        actions.addWidget(start_button)
        actions.addWidget(shutdown_button)
        actions.addWidget(force_off_button)
        actions.addWidget(refresh_button)
        actions.addWidget(console_button)
        actions.addStretch()
        close_button = QPushButton("Cerrar")
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
        self.remote_vm_console_button = console_button
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
        console_button.clicked.connect(self._open_remote_console)
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
                humanize_vm_status(state, "table"),
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
            if label.text().startswith("Este equipo todavía no ha enviado su lista"):
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
            age_text = f"de hace {int(age_seconds // 60)} min" if age_seconds is not None else "de antigüedad desconocida"
            lines.append(
                f"⚠ Estos datos pueden estar desactualizados ({age_text}). "
                "El agente los renueva cada pocos segundos — comprueba que esté en marcha."
            )
        disk_paths = [str(item) for item in (vm.get("disk_paths") or []) if item]
        iso_paths = [str(item) for item in (vm.get("iso_paths") or []) if item]
        networks = [str(item) for item in (vm.get("networks") or []) if item]
        macs = [str(item) for item in (vm.get("macs") or []) if item]
        lines.append(
            details_block(
                ("Nombre", str(vm.get("vm_name") or vm.get("name") or "")),
                ("ID del equipo", host_id),
                ("Nombre del equipo", self._remote_host_name(host_id) or "desconocido"),
                ("Estado", humanize_vm_status(vm.get("state"))),
                ("Laboratorio", str(vm.get("lab_id") or "desconocido")),
                ("RAM", format_mib(vm.get("ram_mib"))),
                ("vCPUs", str(vm.get("vcpus") or "desconocido")),
                ("Discos", ", ".join(disk_paths) if disk_paths else "ninguno"),
                ("ISOs", ", ".join(iso_paths) if iso_paths else "ninguna"),
                ("Pantalla", str(vm.get("display") or "desconocida").upper()),
                ("MACs", ", ".join(macs) if macs else "sin datos"),
                ("Redes", ", ".join(networks) if networks else "sin datos"),
                ("Última actualización", updated_at or "desconocida"),
                ("Origen del dato", "Hub (lo envía el agente del equipo cada pocos segundos)"),
            )
        )
        detail.setPlainText("\n".join(lines))

    def _update_remote_power_buttons(self) -> None:
        vm = self._selected_remote_vm()
        self._render_remote_vm_details()
        console_button = getattr(self, "remote_vm_console_button", None)
        if vm is None:
            for button in (self.remote_vm_start_button, self.remote_vm_shutdown_button, self.remote_vm_force_off_button):
                button.setEnabled(False)
            if console_button is not None:
                console_button.setEnabled(False)
            return
        state = str(vm.get("state") or "unknown").lower()
        running_like = state in {"running", "paused"}
        shut_off = state in {"shut off", "shutoff"}
        self.remote_vm_start_button.setEnabled(shut_off)
        self.remote_vm_shutdown_button.setEnabled(running_like)
        # Force Off also covers stuck/unknown states; it always asks first.
        self.remote_vm_force_off_button.setEnabled(running_like or state == "unknown")
        # Remote console only makes sense for a running VM (a shut-off VM has no display).
        if console_button is not None:
            console_button.setEnabled(running_like)

    def _remote_host_record(self, host_id: str) -> dict[str, Any]:
        for host in self.remote_hosts:
            if str(host.get("host_id") or "") == host_id:
                return host
        return {"host_id": host_id}

    def _open_remote_console(self) -> None:
        dialog = getattr(self, "_remote_vms_dialog", None)
        vm = self._selected_remote_vm()
        if dialog is None or vm is None:
            return
        host_id = str(getattr(dialog, "host_id", ""))
        vm_name = str(vm.get("vm_name") or vm.get("name") or "")
        from .dialogs import live_uri_for_host

        uri = live_uri_for_host(self._remote_host_record(host_id))
        if not uri:
            self.show_error(
                f"No puedo abrir la consola de {vm_name}: el Hub no reporta una dirección SSH para «{host_id}»."
            )
            return

        # Consola INTEGRADA de HyperGery contra la VM remota: el backend abre un
        # túnel SSH al VNC del otro equipo y la consola conecta a 127.0.0.1:local.
        def setup() -> dict[str, Any]:
            try:
                return self.backend.open_remote_vnc_tunnel(vm_name, uri)
            except Exception as exc:
                return {"error": str(exc)}

        def on_ready(result: dict[str, Any]) -> None:
            error = str((result or {}).get("error") or "")
            if error:
                self.show_error(f"No se pudo abrir la consola de {vm_name}: {error}")
                return
            remote_display = {k: result[k] for k in ("type", "host", "port", "uri") if k in result}
            vm_summary = VmSummary(name=vm_name, state="running", lab_id=str(vm.get("lab_id") or ""), graphics="vnc")
            window = VmConsoleWindow(
                self.backend, vm_summary, self,
                remote_display=remote_display, remote_process=result.get("process"),
            )
            self._remote_console_windows.append(window)
            window.destroyed.connect(
                lambda _=None, w=window: w in self._remote_console_windows and self._remote_console_windows.remove(w)
            )
            window.show()
            window.raise_()
            window.activateWindow()
            window.console.connect_console()

        self.run_operation(
            f"Abriendo consola de {vm_name} en {host_id}",
            setup,
            on_success=on_ready,
            refresh_after=False,
            busy=True,
        )

    def _queue_remote_power_action(self, action: str) -> None:
        dialog = getattr(self, "_remote_vms_dialog", None)
        vm = self._selected_remote_vm()
        if dialog is None or vm is None:
            return
        host_id = str(getattr(dialog, "host_id", ""))
        vm_name = str(vm.get("vm_name") or vm.get("name") or "")
        if action == "force_off":
            if not confirm(
                dialog,
                "Apagar a la fuerza",
                f"Apagar a la fuerza puede dañar datos dentro de {vm_name}. ¿Continuar?",
                danger=True,
            ):
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
                self.remote_power_status.setText(f"No se ha podido encolar la orden {action} para {vm_name}: {error}")
                return
            command_id = str((result or {}).get("command_id") or "")
            self._remote_power_command_id = command_id
            self.remote_power_status.setText(
                f"Orden encolada: {command_id} ({action} {vm_name}). Esperando al equipo de destino…"
            )
            self.log_activity(f"Encolada orden remota {action} de {vm_name} en {host_id}: {command_id}")
            self._remote_power_poll_timer.start()

        self.run_operation(
            f"Encolando orden remota {action} de {vm_name} en {host_id}",
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
                self.remote_power_status.setText(f"No se puede leer la orden {command_id}: {error}")
                return
            status = str((result or {}).get("status") or "")
            if status not in {"done", "failed"}:
                self.remote_power_status.setText(f"Orden {command_id}: {humanize_command_status(status or 'pending', 'detail').lower()}…")
                return
            self._remote_power_poll_timer.stop()
            self._remote_power_command_id = ""
            payload = (result or {}).get("result") or {}
            message = str(payload.get("message") or payload.get("error") or "")
            if status == "done":
                self.remote_power_status.setText(f"Orden {command_id} completada. {message}".strip())
                self.log_activity(f"Orden remota completada: {command_id}. {message}".strip())
            else:
                self.remote_power_status.setText(f"Orden {command_id} FALLÓ. {humanize_error_message(message)}".strip())
                self.log_activity(f"Orden remota FALLÓ: {command_id}. {message}".strip())
            self._refresh_remote_vms()

        self.run_operation(
            f"Comprobando orden remota {command_id}",
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
                self.remote_power_status.setText(f"No se ha podido actualizar la lista de {host_id}: {error}")
                return
            self._populate_remote_vms_table(list((result or {}).get("vms") or []))

        self.run_operation(
            f"Actualizando máquinas de {host_id}",
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
                    "Todavía no hay equipos registrados",
                    "Arranca el agente de HyperGery en otro ordenador para que aparezca aquí.",
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
                "No se puede contactar con el Hub",
                "Comprueba que el Hub del NAS esté encendido (docker compose) o revisa HYPERGERY_HUB_URL.\n\n" + error,
                action=("Abrir ajustes", self.app_settings),
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
                    ("Equipo", host_id),
                    ("Orden encolada", str(result.get("command_id", ""))),
                    ("Estado", humanize_command_status(result.get("status"), "detail")),
                )
            )
            self.log_activity(f"Encolada prueba del equipo {host_id}: {result.get('command_id', '')}")

        self.run_operation(f"Probando equipo remoto {host_id}", do_test, on_success=on_done, refresh_after=False)

    # ------------------------------------------------------------------ #
    # Control Center (v0.9/v1 services)                                   #
    # ------------------------------------------------------------------ #

    V1_TAB_KEYS = ("Dashboard", "Telemetry", "Orchestrator", "Battery", "NAS", "Network", "Guests", "External Nodes", "Progress", "Logs")

    def _build_control_center_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Centro de control")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Tu sistema de un vistazo: equipo, batería, copias en el NAS, redes, usuarios y actividad")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.v1_refresh_all_button = self._button("Actualizar todo", self.refresh_v1_all, primary=True)
        self.v1_export_button = self._button("Exportar informe", self.export_v1_report)
        header.addWidget(self.v1_refresh_all_button)
        header.addWidget(self.v1_export_button)
        layout.addLayout(header)

        note = QLabel(
            "Esta página solo muestra información: desde aquí no se cambia ni se ejecuta nada. "
            "Si necesitas los datos en bruto, cada pestaña tiene un botón «Ver detalles técnicos»."
        )
        note.setObjectName("calloutInfo")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.v1_tabs = QTabWidget()
        self.v1_views: dict[str, QTextEdit] = {}
        self.v1_containers: dict[str, QVBoxLayout] = {}
        for key in self.V1_TAB_KEYS:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            tab_layout.setSpacing(8)
            bar = QHBoxLayout()
            refresh = self._button("Actualizar", lambda checked=False, k=key: self.refresh_v1_tab(k))
            bar.addWidget(refresh)
            bar.addStretch()
            details_toggle = QPushButton("Ver detalles técnicos")
            details_toggle.setCheckable(True)
            bar.addWidget(details_toggle)
            tab_layout.addLayout(bar)

            summary_scroll = QScrollArea()
            summary_scroll.setWidgetResizable(True)
            summary_holder = QWidget()
            summary_layout = QVBoxLayout(summary_holder)
            summary_layout.setContentsMargins(0, 0, 0, 0)
            summary_layout.setSpacing(8)
            placeholder = QLabel("Pulsa «Actualizar» para cargar esta sección.")
            placeholder.setObjectName("mutedLabel")
            summary_layout.addWidget(placeholder)
            summary_layout.addStretch()
            summary_scroll.setWidget(summary_holder)
            tab_layout.addWidget(summary_scroll, 2)

            view = QTextEdit()
            view.setReadOnly(True)
            view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            view.setPlaceholderText("Datos técnicos en bruto (JSON) de esta sección.")
            view.setVisible(False)
            tab_layout.addWidget(view, 3)

            def toggle_details(checked: bool, v=view, b=details_toggle) -> None:
                v.setVisible(checked)
                b.setText("Ocultar detalles técnicos" if checked else "Ver detalles técnicos")

            details_toggle.toggled.connect(toggle_details)

            self.v1_containers[key] = summary_layout
            self.v1_views[key] = view
            self.v1_tabs.addTab(tab, V1_TAB_TITLES.get(key, key))
        layout.addWidget(self.v1_tabs, 1)
        self._v1_loaded = False
        return page

    def _v1_collect(self, key: str) -> dict[str, Any]:
        """Collect one Control Center tab's data (runs in a worker thread)."""
        from ..v1.settings import V1Settings

        try:
            settings = V1Settings.load()
        except Exception:
            settings = V1Settings()
        url = self.registry_url()

        def hub_client():
            from ..registry import RegistryClient

            return RegistryClient(url)

        if key == "Dashboard":
            # HG-BUG-0022: misma fuente estructurada que el endpoint /dashboard
            # de v1.4, renderizada como tarjetas por v1_render.
            from ..v1.api import ApiContext
            from ..v1.nas import NasService
            from ..v1.providers import LocalProvider

            def local_vms():
                try:
                    return LocalProvider(self.backend).list_vms()
                except Exception:
                    return []

            context = ApiContext(
                settings=settings,
                nas=NasService(settings=settings, lab_store=self.lab_store()),
                lab_store=self.lab_store(),
                local_vms=local_vms,
                hub_client=hub_client(),
                backend=self.backend,
            )
            return context.dashboard()
        if key == "Progress":
            from ..v1.progress import get_progress_channel

            return {"operations": get_progress_channel().list()}
        if key == "Telemetry":
            from ..v1.telemetry import TelemetryService, evaluate_alerts

            service = TelemetryService(settings=settings)
            sample = service.sample_local()
            service.record(sample)
            return {"local": sample.to_dict(), "alerts": evaluate_alerts(local_sample=sample, settings=settings)}
        if key == "Orchestrator":
            from ..v1.battery import BatteryService
            from ..v1.hosts import HostRegistry
            from ..v1.orchestrator import OrchestratorService
            from ..v1.providers import LocalProvider
            from ..v1.telemetry import TelemetryService

            registry = HostRegistry(settings=settings, telemetry=TelemetryService(settings=settings), hub_client=hub_client())
            hosts = registry.list_hosts()
            try:
                vms = LocalProvider(self.backend).list_vms()
            except Exception:
                vms = []
            plans = OrchestratorService(settings=settings).plan(
                hosts=hosts,
                vms=vms,
                battery=BatteryService(settings=settings).read(),
                local_host_id=hosts[0].id if hosts else None,
            )
            return {"plans": [plan.to_dict() for plan in plans], "dry_run": True}
        if key == "Battery":
            from ..v1.battery import BatteryService

            service = BatteryService(settings=settings)
            state = service.read()
            return {"battery": state.to_dict(), "actions": service.recommended_actions(state)}
        if key == "NAS":
            from ..v1.nas import NasService

            service = NasService(settings=settings, lab_store=self.lab_store())
            return {"health": service.health(), "commits": service.list_commits()[-10:]}
        if key == "Network":
            from ..v1.networks import networks_from_labs, validate_networks

            labs = self.lab_store().list_labs()
            networks = networks_from_labs(labs)
            result = validate_networks(networks)
            return {"networks": [network.to_dict() for network in networks], "validation": result}
        if key == "Guests":
            from ..v1.rbac import UserStore

            users = UserStore().list_users()
            return {"users": [{**user.to_dict(), "effective_permissions": sorted(user.permissions())} for user in users]}
        if key == "External Nodes":
            from ..v1.external_nodes import ExternalNodeStore, health_check

            nodes = ExternalNodeStore().list_nodes()
            return {"nodes": [{**node.to_dict(), "health": health_check(node)} for node in nodes]}
        if key == "Logs":
            from ..v1.hglog import get_logger

            events = get_logger().query(limit=100, from_file=True)
            return {"events": events[-100:]}
        return {}

    def _set_v1_view(self, key: str, payload: Any) -> None:
        """Show a section: human summary in Spanish + raw JSON details.

        Accepts the payload dict from `_v1_collect`, a JSON string (legacy
        callers/tests), or a plain error message string.
        """
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                details_text, payload = payload, parsed
            else:
                details_text, payload = payload, None
        else:
            details_text = json.dumps(payload, indent=2, sort_keys=True, default=str)

        container = self.v1_containers.get(key)
        if container is not None:
            self._clear_layout(container)
            if isinstance(payload, dict):
                widget = v1_render.build_v1_widget(key, payload)
            else:
                widget = QLabel(details_text or "Sin datos.")
                widget.setObjectName("calloutDanger")
                widget.setWordWrap(True)
            container.addWidget(widget)
            container.addStretch()
        view = self.v1_views.get(key)
        if view is not None:
            view.setPlainText(details_text)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh_v1_tab(self, key: str) -> None:
        title = V1_TAB_TITLES.get(key, key)

        def fetch() -> Any:
            try:
                return self._v1_collect(key)
            except Exception as exc:
                return f"No se ha podido cargar «{title}»: {exc}"

        self.run_operation(
            f"Cargando {title}",
            fetch,
            on_success=lambda payload, k=key: self._set_v1_view(k, payload),
            refresh_after=False,
            busy=False,
        )

    def refresh_v1_all(self) -> None:
        for key in self.V1_TAB_KEYS:
            self.refresh_v1_tab(key)

    def export_v1_report(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar informe del Centro de control",
            "hypergery-v1-report.json",
            "Informe (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        report = {
            "generated_at": now_iso(),
            "sections": {key: self.v1_views[key].toPlainText() for key in self.V1_TAB_KEYS},
        }
        try:
            Path(path).expanduser().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self.show_error(f"No se ha podido exportar el informe: {exc}")
            return
        self.log_activity(f"Informe del Centro de control exportado a {path}")
        self.status.showMessage(f"Informe exportado a {path}", 5000)

    DOCTOR_GROUPS = (
        ("Virtualización local", ("/dev/kvm", "user groups", "libvirt")),
        ("Herramientas", ("python", "qemu-img", "virsh", "virt-viewer")),
        ("Hub y agente", ("hub url", "host id", "hub reachable")),
        ("NAS", ("nas staging path",)),
        ("Docker", ("docker folder", "docker compose")),
        ("Inventario de máquinas", ("hub vm inventory",)),
    )

    def _build_diagnostics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Diagnóstico")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Comprobaciones de KVM, libvirt, Hub, NAS y herramientas — solo lectura, no cambia nada.")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.copy_report_button = self._button("Copiar informe", self.copy_doctor_report)
        self.copy_report_button.setEnabled(False)
        troubleshooting_button = self._button("Guía de problemas", self.open_troubleshooting)
        self.run_doctor_button = self._button("Comprobar sistema", self.run_doctor, primary=True)
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
        self.diag_overall_label = QLabel("Todavía no se ha comprobado el sistema.")
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
            "Pulsa «Comprobar sistema» para revisar tu equipo",
            "Se revisan /dev/kvm, los grupos de usuario, libvirt, las herramientas de QEMU, el Hub, el NAS y Docker Compose, sin cambiar nada.",
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
        self._diag_show_message("Comprobando…", "Revisando KVM, libvirt, herramientas, Hub, NAS y Docker. Puede tardar unos segundos si el Hub no responde.")

        def collect() -> dict[str, Any]:
            from ..doctor import collect_doctor_items, doctor_exit_code

            try:
                items = collect_doctor_items()
                return {"items": items, "exit_code": doctor_exit_code(items)}
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Ejecutando diagnóstico",
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
            self.diag_overall_label.setText("El diagnóstico no se ha podido ejecutar.")
            self._clear_diag_results()
            error_label = QLabel(f"El diagnóstico no se ha podido ejecutar: {result['error']}")
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
            f"Sin fallos críticos · {now_iso()}" if exit_code == 0
            else f"Hay fallos críticos · {now_iso()}"
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
            self.diag_results_layout.addWidget(self._doctor_group_card("Otros", remaining))
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
            name = QLabel(item.name + ("  · CRÍTICO" if item.critical and item.status == "FAIL" else ""))
            name.setMinimumWidth(170)
            # Presentación: el doctor (CLI) emite detalles técnicos; aquí se
            # muestran en español sin tocar el dato original.
            detail_text = (
                str(item.detail)
                .replace("writable=True", "escribible: sí")
                .replace("writable=False", "escribible: NO")
                .replace("{'ok': True}", "responde correctamente")
                .replace(" VM record(s)", " máquina(s) registradas")
            )
            detail = QLabel(detail_text)
            detail.setObjectName("mutedLabel")
            detail.setWordWrap(True)
            row.addWidget(chip)
            row.addWidget(name)
            row.addWidget(detail, 1)
            layout.addLayout(row)
        return card

    def copy_doctor_report(self) -> None:
        if not self._doctor_items:
            self.status.showMessage("Aún no hay diagnóstico que copiar. Pulsa «Comprobar sistema» primero.", 5000)
            return
        from ..doctor import doctor_exit_code, format_doctor_items

        report = format_doctor_items(self._doctor_items)
        report += f"\n\nexit code: {doctor_exit_code(self._doctor_items)} · generated {now_iso()}"
        QApplication.clipboard().setText(report)
        self.status.showMessage("Informe copiado al portapapeles", 5000)
        self.log_activity("Informe de diagnóstico copiado")

    def open_troubleshooting(self) -> None:
        path = Path(__file__).resolve().parents[3] / "docs" / "TROUBLESHOOTING.md"
        if path.is_file():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            self.status.showMessage(f"Abriendo {path}", 5000)
        else:
            self.status.showMessage(f"No se encuentra la guía de problemas en {path}", 8000)

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

        title = QLabel("Inicio")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Tu equipo, el Hub del NAS y los demás equipos del laboratorio, de un vistazo.")
        subtitle.setObjectName("mutedLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(14)
        vm_card, self.dash_vm_big, self.dash_vm_sub = self._stat_card("MÁQUINAS VIRTUALES")
        hub_card, self.dash_hub_big, self.dash_hub_sub = self._stat_card("HYPERGERY HUB")
        nas_card, self.dash_nas_big, self.dash_nas_sub = self._stat_card("ZONA NAS")
        hosts_card, self.dash_hosts_big, self.dash_hosts_sub = self._stat_card("EQUIPOS EN LÍNEA")
        self.dash_hub_big.setText("Sin comprobar")
        self.dash_nas_big.setText("Sin comprobar")
        for card in (vm_card, hub_card, nas_card, hosts_card):
            stats_row.addWidget(card, 1)
        layout.addLayout(stats_row)

        quick_title = QLabel("Acciones rápidas")
        quick_title.setObjectName("sectionTitle")
        layout.addWidget(quick_title)
        quick_grid = QGridLayout()
        quick_grid.setHorizontalSpacing(14)
        quick_grid.setVerticalSpacing(14)
        actions = (
            ("Nueva máquina", "Crear desde una ISO local", self.new_vm, True),
            ("Nuevo laboratorio", "Red aislada para experimentar", self.new_lab, False),
            ("Abrir consola", "Consola VNC integrada", self._dashboard_go_vms, False),
            ("Mover a otro equipo", "A través del Hub o del NAS", self._dashboard_go_vms, False),
            ("Comprobar sistema", "Diagnóstico del equipo y el Hub", self._dashboard_go_diagnostics, False),
            ("Ajustes", "Hub · NAS · valores por defecto", self.app_settings, False),
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
        warnings_title = QLabel("Avisos")
        warnings_title.setObjectName("sectionTitle")
        warnings_layout.addWidget(warnings_title)
        self.dash_warnings_layout = QVBoxLayout()
        self.dash_warnings_layout.setSpacing(8)
        warnings_layout.addLayout(self.dash_warnings_layout)
        warnings_layout.addStretch()
        initial = QLabel("Aún no se ha comprobado el Hub ni el NAS. Pulsa «Actualizar».")
        initial.setObjectName("calloutInfo")
        initial.setWordWrap(True)
        self.dash_warnings_layout.addWidget(initial)

        migration_card = QFrame()
        migration_card.setObjectName("panel")
        migration_layout = QVBoxLayout(migration_card)
        migration_layout.setContentsMargins(16, 14, 16, 14)
        migration_layout.setSpacing(8)
        migration_title = QLabel("Último traslado")
        migration_title.setObjectName("sectionTitle")
        self.dash_migration_label = QLabel("Todavía no se ha movido ninguna máquina.")
        self.dash_migration_label.setObjectName("mutedLabel")
        self.dash_migration_label.setWordWrap(True)
        migration_note = QLabel("Mover una máquina nunca toca la original: se copia, y en el destino se regeneran su UUID y su MAC.")
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
        self._show_section("Máquinas virtuales")

    def _dashboard_go_diagnostics(self) -> None:
        self._show_section("Diagnóstico")

    def update_dashboard_vms(self) -> None:
        counts = {"running": 0, "shutoff": 0, "paused": 0, "unknown": 0}
        for vm in self.all_vms:
            counts[state_kind(vm.state)] += 1
        self.dash_vm_big.setText(str(counts["running"]))
        self._set_stat_tone(self.dash_vm_big, "ok" if counts["running"] else "")
        self.dash_vm_sub.setText(
            f"encendidas · {counts['shutoff']} apagadas · {counts['paused']} en pausa · {len(self.all_vms)} en total"
        )

    def update_dashboard_hub(self, hosts: list[dict[str, Any]], *, reachable: bool, vm_count: int | None, nas_writable: bool, nas_path: str) -> None:
        self.dash_hub_big.setText("En línea" if reachable else "Sin conexión")
        self._set_stat_tone(self.dash_hub_big, "ok" if reachable else "bad")
        records = "desconocido" if vm_count is None else f"{vm_count} máquina(s) registrada(s)"
        self.dash_hub_sub.setText(f"{self.registry_url()} · {records}" if reachable else self.registry_url())
        self.dash_nas_big.setText("Funciona" if nas_writable else "No escribible")
        self._set_stat_tone(self.dash_nas_big, "ok" if nas_writable else "bad")
        self.dash_nas_sub.setText(nas_path)
        online = sum(1 for host in hosts if host.get("status") == "online")
        self.dash_hosts_big.setText(f"{online} / {len(hosts)}" if hosts else "0")
        self._set_stat_tone(self.dash_hosts_big, "ok" if hosts and online == len(hosts) else "")
        offline_ids = [str(host.get("host_id") or "?") for host in hosts if host.get("status") != "online"]
        self.dash_hosts_sub.setText(
            "todos los equipos funcionan" if hosts and not offline_ids
            else (", ".join(offline_ids) + " sin conexión" if offline_ids else "ningún equipo registrado")
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
            callout("El Hub de HyperGery no responde. Revisa HYPERGERY_HUB_URL y que el contenedor Docker esté sano.", "calloutWarn")
        if not nas_writable:
            callout("No se puede escribir en el NAS. Monta la carpeta compartida antes de mover máquinas.", "calloutWarn")
        for host_id in offline_ids:
            callout(f"{host_id} está sin conexión: no se pueden mover máquinas allí.", "calloutWarn")
        if reachable and nas_writable and not offline_ids:
            callout("Sin avisos: el Hub y el NAS funcionan correctamente.", "calloutOk")

    def update_dashboard_migration(self, migrations: list[dict[str, Any]]) -> None:
        if not migrations:
            self.dash_migration_label.setText("Todavía no se ha movido ninguna máquina.")
            return
        last = migrations[-1]
        migration_id = str(last.get("migration_id") or "?")
        status = str(last.get("status") or "unknown")
        vm_name = str(last.get("vm_name") or last.get("source_vm_name") or "?")
        self.dash_migration_label.setText(
            f"{migration_id}\n{vm_name} · estado: {humanize_command_status(status, 'detail').lower()}"
        )

    # ------------------------------------------------------------------ #
    # Labs workspace (v0.8)                                               #
    # ------------------------------------------------------------------ #

    LAB_WS_TABLE_COLUMNS = ("Nombre", "Rol", "Estado", "Equipo", "RAM", "vCPUs", "Ubicación")

    def _build_labs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        title = QLabel("Laboratorios")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Tus laboratorios: máquinas agrupadas entre este equipo y los demás")
        subtitle.setObjectName("mutedLabel")
        head_col.addWidget(title)
        head_col.addWidget(subtitle)
        header.addLayout(head_col)
        header.addStretch()
        self.lab_ws_new_button = self._button("Nuevo laboratorio", self.new_lab, primary=True)
        self.lab_ws_refresh_button = self._button("Actualizar", self.refresh_all)
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
        self.lab_ws_title = QLabel("Ningún laboratorio seleccionado")
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
        self.lab_ws_open_vm_button = self._button("Abrir máquina", self.lab_ws_open_vm)
        self.lab_ws_view_remote_button = self._button("Ver máquina remota", self.lab_ws_view_remote_vm)
        self.lab_ws_migrate_button = self._button("Mover máquina", self.lab_ws_migrate_vm)
        self.lab_ws_role_button = self._button("Asignar rol…", self.lab_ws_set_role)
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
        self.lab_ws_start_button = self._button("Encender laboratorio", self.start_lab, primary=True)
        self.lab_ws_shutdown_button = self._button("Apagar laboratorio", self.shutdown_lab)
        self.lab_ws_snapshot_button = QPushButton("Instantánea del laboratorio")
        self.lab_ws_snapshot_button.setEnabled(False)
        self.lab_ws_snapshot_button.setToolTip(
            "Previsto — aún no hay instantáneas de laboratorio completo. Usa las instantáneas por máquina."
        )
        lab_actions.addWidget(self.lab_ws_start_button)
        lab_actions.addWidget(self.lab_ws_shutdown_button)
        lab_actions.addWidget(self.lab_ws_snapshot_button)
        lab_actions.addStretch()
        detail_layout.addLayout(lab_actions)

        self.lab_ws_feedback = QLabel(
            "«Encender laboratorio» inicia todas las máquinas apagadas del laboratorio, "
            "tanto locales como remotas. «Apagar laboratorio» envía un apagado suave ACPI "
            "a las máquinas encendidas. No existe apagado a la fuerza de todo el laboratorio "
            "para evitar pérdidas de datos."
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
        meta = QLabel(f"{lab_id} · red {humanize_network_label(lab.get('network_mode', 'nat'))} · subred {lab.get('subnet', '') or '—'}")
        meta.setObjectName("mutedLabel")
        summary = lab_status_summary(self._workspace_unified_vms(lab))
        counts = summary["counts"]
        chips = QLabel(
            f"{counts['total']} máquina(s) · {counts['running']} encendidas · {counts['shut_off']} apagadas"
            + (f" · {counts['paused']} en pausa" if counts["paused"] else "")
            + (f" · {counts['not_created']} sin crear" if counts["not_created"] else "")
            + (f" · {counts['unknown']} desconocidas" if counts["unknown"] else "")
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
                    "Todavía no hay laboratorios",
                    "Crea máquinas en default-lab o crea un laboratorio nuevo.",
                    action=("Nuevo laboratorio", self.new_lab),
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
            self.lab_ws_title.setText("Ningún laboratorio seleccionado")
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
            f"{lab_id} · red {humanize_network_label(lab.get('network_mode', 'nat'))} · subred {lab.get('subnet', '') or '—'} · "
            f"puente {lab.get('bridge_name', '') or '—'}"
            + (f"\n{description}" if description else "")
        )
        unified = self._workspace_unified_vms(lab)
        self._lab_ws_vms = unified
        summary = lab_status_summary(unified)
        counts = summary["counts"]
        self.lab_ws_status_label.setText(
            f"Estado: {counts['total']} máquina(s) · {counts['running']} encendidas · "
            f"{counts['shut_off']} apagadas · {counts['paused']} en pausa · "
            f"{counts['unknown']} desconocidas · {counts['not_created']} sin crear"
        )
        hosts = summary["hosts"]
        if hosts:
            parts = [f"{host_id}: {len(names)} máquina(s)" for host_id, names in sorted(hosts.items())]
            self.lab_ws_hosts_label.setText("Reparto por equipos — " + " · ".join(parts))
        else:
            self.lab_ws_hosts_label.setText("Reparto por equipos — aún no hay máquinas creadas")
        self.lab_ws_vm_table.setRowCount(len(unified))
        local_host_id = self._local_host_id()
        for row, vm in enumerate(unified):
            location = "Local" if (not vm["remote"] and vm["host_id"] == local_host_id) else ("Remoto" if vm["remote"] else "—")
            cells = (
                vm["name"],
                vm["role"] or "—",
                humanize_vm_status(vm["state"], "table"),
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
            self.status.showMessage(f"Selecciona {vm['name']} en «Máquinas virtuales» y pulsa «Mover a otro equipo»", 8000)

    def lab_ws_set_role(self) -> None:
        lab = self._selected_workspace_lab()
        vm = self._selected_lab_ws_vm()
        if lab is None or vm is None:
            return
        options = ["(sin rol)"] + list(LAB_VM_ROLES)
        current = vm["role"] if vm["role"] in LAB_VM_ROLES else "(sin rol)"
        choice, ok = QInputDialog.getItem(
            self,
            "Asignar rol",
            f"Rol de {vm['name']} en {lab.get('lab_id', '')}:",
            options,
            options.index(current),
            False,
        )
        if not ok:
            return
        role = "" if choice == "(sin rol)" else choice
        try:
            self.lab_store().set_vm_role(str(lab["lab_id"]), vm["name"], role)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.log_activity(f"Rol '{role or 'ninguno'}' asignado a {vm['name']} en el laboratorio {lab.get('lab_id', '')}")
        self.refresh_labs()
        self.render_labs_workspace()

    def start_lab(self) -> None:
        self._confirm_and_run_lab_power("start")

    def shutdown_lab(self) -> None:
        self._confirm_and_run_lab_power("shutdown")

    def _confirm_and_run_lab_power(self, action: str) -> None:
        lab = self._selected_workspace_lab()
        if lab is None:
            self.show_error("Selecciona un laboratorio primero.")
            return
        plan = plan_lab_power_action(self._workspace_unified_vms(lab), action)
        targets = plan["targets"]
        if not targets:
            self.lab_ws_feedback.setText(
                "No hay nada que encender: ninguna máquina del laboratorio está apagada."
                if action == "start"
                else "No hay nada que apagar: ninguna máquina del laboratorio está encendida."
            )
            return
        if action == "start":
            question = f"Se encenderán {len(targets)} máquina(s) en {plan['host_count']} equipo(s)."
        else:
            question = f"Se pedirá el apagado suave de {len(targets)} máquina(s) encendida(s)."
        names = ", ".join(vm["name"] for vm in targets[:8]) + ("…" if len(targets) > 8 else "")
        if not confirm(
            self,
            "Encender laboratorio" if action == "start" else "Apagar laboratorio",
            f"{question}\n\nMáquinas: {names}\n\n¿Continuar?",
        ):
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
            lines = [f"Laboratorio {lab_id} ({humanize_lab_action(action)}):"]
            if local:
                lines.append(f"  {len(local)} máquina(s) locales: {', '.join(local)}")
            if queued:
                lines.append(f"  {len(queued)} orden(es) remotas encoladas: {', '.join(queued)}")
            if errors:
                lines.append(f"  {len(errors)} FALLARON:")
                for error in errors:
                    name, _, detail = error.partition(": ")
                    lines.append(f"    - {name}: {humanize_error_message(detail).splitlines()[0]}")
                lines.append(f"  Detalle técnico: {'; '.join(errors)}")
            summary = "\n".join(lines)
            self.lab_ws_feedback.setText(summary)
            self.lab_ws_feedback.setObjectName("calloutDanger" if errors else "calloutOk")
            self.lab_ws_feedback.style().unpolish(self.lab_ws_feedback)
            self.lab_ws_feedback.style().polish(self.lab_ws_feedback)
            self.log_activity(summary.replace("\n", " · "))
            self.refresh_all()

        self.log_activity(f"Pedido {humanize_lab_action(action)} del laboratorio {lab_id}: {len(targets)} máquina(s)")
        self.run_operation(
            f"{'Encendiendo' if action == 'start' else 'Apagando'} laboratorio {lab_id}",
            run,
            on_success=on_done,
            refresh_after=False,
            busy=False,
        )

    # Cabeceras cortas para que no se trunquen ("áquina orige…"). Origen y
    # Destino son nombres de máquina; Ruta es el trayecto entre equipos.
    MIGRATIONS_TABLE_COLUMNS = ("ID", "Origen", "Destino", "Ruta", "Método", "Estado", "Actualizado")

    def _build_migrations_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("Migraciones")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Historial de traslados de máquinas entre equipos")
        subtitle.setObjectName("mutedLabel")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.migrations_refresh_button = QPushButton("Actualizar")
        self.migrations_refresh_button.clicked.connect(self.refresh_migrations)
        open_migration = QPushButton("Mover una máquina…")
        open_migration.setObjectName("primaryButton")
        open_migration.clicked.connect(self._open_live_migration_from_page)
        header.addWidget(self.migrations_refresh_button)
        header.addWidget(open_migration)
        layout.addLayout(header)

        self.migrations_status_label = QLabel("Historial sin cargar — pulsa «Actualizar».")
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
        self.copy_migration_id_button = QPushButton("Copiar ID")
        self.copy_migration_id_button.setEnabled(False)
        self.copy_migration_id_button.clicked.connect(self.copy_selected_migration_id)
        self.copy_migration_summary_button = QPushButton("Copiar resumen")
        self.copy_migration_summary_button.setEnabled(False)
        self.copy_migration_summary_button.clicked.connect(self.copy_selected_migration_summary)
        actions.addWidget(self.copy_migration_id_button)
        actions.addWidget(self.copy_migration_summary_button)
        actions.addStretch()
        layout.addLayout(actions)

        safety = QLabel(
            "El historial es de solo consulta: desde aquí no se borra nada. "
            "Mover una máquina nunca toca la original."
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
        title = QLabel("Limpieza de archivos temporales del Hub")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        hours_label = QLabel("Más antiguos de (horas):")
        hours_label.setObjectName("mutedLabel")
        self.staging_hours_spin = QSpinBox()
        self.staging_hours_spin.setRange(1, 720)
        self.staging_hours_spin.setValue(24)
        self.staging_refresh_button = self._button("Actualizar", self.refresh_hub_staging)
        self.staging_dry_run_button = self._button("Simular limpieza", self.dry_run_hub_cleanup)
        self.staging_cleanup_button = self._button("Limpiar de verdad", self.confirm_hub_cleanup, danger=True)
        header.addWidget(hours_label)
        header.addWidget(self.staging_hours_spin)
        header.addWidget(self.staging_refresh_button)
        header.addWidget(self.staging_dry_run_button)
        header.addWidget(self.staging_cleanup_button)
        layout.addLayout(header)

        self.staging_stats_label = QLabel("Sin cargar — pulsa «Actualizar».")
        self.staging_stats_label.setObjectName("mutedLabel")
        self.staging_stats_label.setWordWrap(True)
        layout.addWidget(self.staging_stats_label)

        self.staging_detail = QTextEdit()
        self.staging_detail.setReadOnly(True)
        self.staging_detail.setMaximumHeight(150)
        self.staging_detail.setPlaceholderText(
            "Aquí aparecen los paquetes temporales y las simulaciones de limpieza."
        )
        layout.addWidget(self.staging_detail)

        staging_safety = QLabel(
            "Solo se borran archivos temporales del Hub. Las máquinas y los discos importados no se tocan nunca."
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

    HUB_OFFLINE_STAGING_MESSAGE = "No se puede contactar con el Hub. Revisa el Hub del NAS y HYPERGERY_HUB_URL."

    def refresh_hub_staging(self) -> None:
        url = self.registry_url()

        def fetch() -> dict[str, Any]:
            from ..registry import RegistryClient

            try:
                return RegistryClient(url).list_staged_packages()
            except Exception as exc:
                return {"error": str(exc)}

        self.run_operation(
            "Cargando archivos temporales del Hub",
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
            f"Carpeta temporal: {result.get('staging_dir', '')} · "
            f"{len(packages)} paquete(s) · {total} · {orphans} huérfano(s) · "
            f"el más antiguo {oldest:.1f}h"
        )
        if not packages:
            self.staging_detail.setPlainText("No hay paquetes temporales.")
            return
        lines = []
        for package in packages:
            status = package.get("migration_status") or "sin registro de traslado (huérfano)"
            lines.append(
                f"{package.get('migration_id', '')} · {self._format_size(package.get('size_bytes') or 0)} · "
                f"{package.get('file_count', 0)} archivo(s) · {package.get('age_hours', 0)}h · {status}"
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

        label = "Simulando limpieza de archivos temporales" if dry_run else "Limpiando archivos temporales del Hub"
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
        if not confirm(
            self,
            "Limpiar archivos temporales del Hub",
            (
                f"¿Borrar los paquetes temporales del Hub con más de {hours}h?\n\n"
                "Solo se borran archivos temporales del Hub. "
                "Las máquinas y los discos importados no se tocan nunca.\n\n"
                "Los paquetes de traslados en curso siempre se conservan."
            ),
            yes_text="Sí, borrar",
            no_text="Cancelar",
            danger=True,
        ):
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
        lines = ["SIMULACIÓN — no se ha borrado nada." if dry_run else "LIMPIEZA EJECUTADA."]
        lines.append(
            f"{len(candidates)} candidato(s) a borrar · {self._format_size(result.get('total_size_bytes') or 0)} "
            f"(más antiguos de {result.get('older_than_hours', '?')}h)"
        )
        for candidate in candidates:
            lines.append(
                f"  - {candidate.get('migration_id', '')} "
                f"({self._format_size(candidate.get('size_bytes') or 0)}): {candidate.get('reason', '')}"
            )
        if not candidates:
            lines.append("  No hay nada que limpiar.")
        if skipped:
            lines.append(f"{len(skipped)} omitido(s):")
            for item in skipped:
                lines.append(f"  - {item.get('migration_id', '')}: {item.get('reason', '')}")
        if not dry_run:
            lines.append(
                f"Borrados {result.get('deleted_count', 0)} paquete(s), "
                f"liberados {self._format_size(result.get('deleted_size_bytes') or 0)}."
            )
        for item in errors:
            lines.append(f"ERROR {item.get('migration_id', '')}: {item.get('error', '')}")
        self.staging_detail.setPlainText("\n".join(lines))
        if not dry_run:
            self.log_activity(
                f"Limpieza del Hub completada: {result.get('deleted_count', 0)} borrados, "
                f"{len(errors)} error(es)"
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
            "Cargando historial de traslados",
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
            self.migrations_status_label.setText(f"No se puede contactar con el Hub: {error}")
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
                humanize_command_status(status),
                str(record.get("updated_at") or ""),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 5:
                    status_colors = {"done": "#22C55E", "failed": "#EF4444"}
                    item.setForeground(QColor(status_colors.get(status, "#F59E0B")))
                self.migrations_table.setItem(row, column, item)
        # Ajusta el ancho al contenido para que estados como COMPLETADA se
        # vean enteros (la última columna sigue estirándose), sin dejar que
        # los ID acaparen todo el ancho.
        self.migrations_table.resizeColumnsToContents()
        self.migrations_table.setColumnWidth(0, min(self.migrations_table.columnWidth(0), 230))
        if migrations:
            done = sum(1 for record in migrations if record.get("status") == "done")
            failed = sum(1 for record in migrations if record.get("status") == "failed")
            self.migrations_status_label.setText(
                f"{len(migrations)} traslado(s) en el Hub · {done} completados · {failed} fallidos"
            )
        else:
            self.migrations_status_label.setText("El Hub aún no tiene traslados registrados.")
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
        self.status.showMessage("ID copiado", 4000)

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
        self.status.showMessage("Resumen copiado", 4000)

    COMMANDS_TABLE_COLUMNS = ("ID", "Equipo", "Tipo", "Estado", "Creada", "Antigüedad", "Datos", "Resultado")
    COMMAND_FILTERS = ("Todas", "Pendientes", "En curso", "Completadas", "Fallidas", "De encendido/apagado", "De traslado")
    MIGRATION_COMMAND_TYPES = {"receive_vm_package", "import_vm_package", "migration_status"}

    def _build_commands_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("Tareas remotas")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Órdenes que viajan por el Hub: encendidos remotos, traslados y diagnósticos (solo consulta)")
        subtitle.setObjectName("mutedLabel")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.commands_filter = QComboBox()
        self.commands_filter.addItems(list(self.COMMAND_FILTERS))
        self.commands_filter.currentIndexChanged.connect(self._apply_commands_filter)
        self.commands_refresh_button = self._button("Actualizar", self.refresh_commands)
        header.addWidget(self.commands_filter)
        header.addWidget(self.commands_refresh_button)
        layout.addLayout(header)

        self.commands_status_label = QLabel("Sin cargar — pulsa «Actualizar».")
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
        self.copy_command_id_button = QPushButton("Copiar ID")
        self.copy_command_id_button.setEnabled(False)
        self.copy_command_id_button.clicked.connect(self.copy_selected_command_id)
        self.copy_command_result_button = QPushButton("Copiar resultado")
        self.copy_command_result_button.setEnabled(False)
        self.copy_command_result_button.clicked.connect(self.copy_selected_command_result)
        actions.addWidget(self.copy_command_id_button)
        actions.addWidget(self.copy_command_result_button)
        actions.addStretch()
        layout.addLayout(actions)

        safety = QLabel(
            "Vista de solo consulta: desde aquí no se reenvían ni se borran órdenes. "
            "Para encender o apagar máquinas remotas ve a «Otros equipos» → «Ver máquinas»."
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
            "Cargando órdenes del Hub",
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
            self.commands_status_label.setText(f"No se puede contactar con el Hub: {error}")
            return
        self.commands_history = list((result or {}).get("commands") or [])
        self._apply_commands_filter()

    # Etiquetas del desplegable (en español) → estado interno del Hub.
    COMMAND_STATUS_FILTERS = {
        "Pendientes": "pending",
        "En curso": "running",
        "Completadas": "done",
        "Fallidas": "failed",
    }

    def _filtered_commands(self) -> list[dict[str, Any]]:
        selected = self.commands_filter.currentText()
        commands = self.commands_history
        status = self.COMMAND_STATUS_FILTERS.get(selected)
        if status is not None:
            return [item for item in commands if str(item.get("status") or "") == status]
        if selected == "De encendido/apagado":
            return [item for item in commands if str(item.get("command_type") or "").startswith("vm_")]
        if selected == "De traslado":
            return [item for item in commands if str(item.get("command_type") or "") in self.MIGRATION_COMMAND_TYPES]
        return list(commands)

    @staticmethod
    def _summarize_command_value(value: Any, limit: int = 80) -> str:
        if not value:
            return "—"
        # Resumen en español, sin JSON crudo; el JSON completo sigue
        # disponible con «Copiar resultado».
        text = humanize_command_value(value)
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
                humanize_command_type(command.get("command_type")),
                humanize_command_status(status),
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
        # Evita estados truncados (COMPLETADA…) ajustando al contenido,
        # sin dejar que los ID (UUID) acaparen todo el ancho.
        self.commands_table.resizeColumnsToContents()
        self.commands_table.setColumnWidth(0, min(self.commands_table.columnWidth(0), 230))
        if self.commands_history:
            counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for command in self.commands_history:
                key = str(command.get("status") or "")
                if key in counts:
                    counts[key] += 1
            self.commands_status_label.setText(
                f"{len(commands)} mostradas / {len(self.commands_history)} orden(es) en el Hub · "
                f"{counts['pending']} pendientes · {counts['running']} en curso · "
                f"{counts['done']} completadas · {counts['failed']} fallidas"
            )
        else:
            self.commands_status_label.setText("El Hub aún no tiene órdenes registradas.")
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
        self.status.showMessage("ID copiado", 4000)

    def copy_selected_command_result(self) -> None:
        command = self._selected_command()
        if not command:
            return
        QApplication.clipboard().setText(json.dumps(command.get("result") or {}, indent=2, sort_keys=True))
        self.status.showMessage("Resultado copiado", 4000)

    def _open_live_migration_from_page(self) -> None:
        if self.selected_vm is not None:
            self.live_migration_vm()
            return
        self._dashboard_go_vms()
        self.status.showMessage("Selecciona una máquina y pulsa «Mover a otro equipo»", 6000)

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
        self.vm_empty_title = QLabel("Todavía no hay máquinas virtuales")
        self.vm_empty_title.setObjectName("heroTitle")
        self.vm_empty_subtitle = QLabel("Crea tu primera máquina desde una ISO.")
        self.vm_empty_subtitle.setObjectName("heroSubtitle")
        self.vm_empty_subtitle.setWordWrap(True)
        self.vm_empty_button = self._button("Nueva máquina", self.new_vm_from_empty, primary=True)
        layout.addStretch()
        layout.addWidget(self.vm_empty_title)
        layout.addWidget(self.vm_empty_subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.vm_empty_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return panel

    def _build_vm_list_pane(self) -> QWidget:
        """Columna izquierda estrecha: buscador + árbol de VMs (estilo VirtualBox)."""
        pane = QWidget()
        pane.setObjectName("vmListPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(10, 12, 8, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.vm_page_title = QLabel("Máquinas virtuales")
        self.vm_page_title.setObjectName("sectionTitle")
        self.vm_count_label = QLabel("Sin máquinas")
        self.vm_count_label.setObjectName("mutedLabel")
        header.addWidget(self.vm_page_title)
        header.addStretch()
        header.addWidget(self.vm_count_label)
        layout.addLayout(header)

        # Subtítulo conservado por compatibilidad (no se muestra en la columna
        # estrecha estilo VirtualBox; algunos tests verifican su texto).
        self.vm_page_subtitle = QLabel("Las máquinas de este equipo y sus laboratorios")
        self.vm_page_subtitle.setObjectName("mutedLabel")
        self.vm_page_subtitle.hide()
        layout.addWidget(self.vm_page_subtitle)

        self.vm_filter_edit = QLineEdit()
        self.vm_filter_edit.setPlaceholderText("Buscar…  (Ctrl+F)")
        self.vm_filter_edit.setClearButtonEnabled(True)
        self.vm_filter_edit.textChanged.connect(self._on_vm_search_text)
        layout.addWidget(self.vm_filter_edit)

        self.vm_filter = QComboBox()
        self.vm_filter.addItems(["Todas las máquinas", "Laboratorio seleccionado"])
        self.vm_filter.currentIndexChanged.connect(self.on_vm_filter_changed)
        layout.addWidget(self.vm_filter)

        self.vm_tree = VmTree()
        self.vm_tree.currentVmChanged.connect(self._on_tree_vm_changed)
        self.vm_tree.vmActivated.connect(self._on_tree_vm_activated)
        self.vm_stack = QStackedWidget()
        self.vm_stack.addWidget(self.vm_tree)
        self.vm_stack.addWidget(self._build_vm_empty_state())
        layout.addWidget(self.vm_stack, 1)
        return pane

    def _build_preview_panel(self) -> QWidget:
        """Columna derecha pequeña: «Previsualización» con mini pantalla."""
        panel = QFrame()
        panel.setObjectName("previewPane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Previsualización")
        title.setObjectName("previewTitle")
        layout.addWidget(title)

        self.preview_screen = QFrame()
        self.preview_screen.setObjectName("previewScreen")
        self.preview_screen.setMinimumHeight(150)
        screen_layout = QVBoxLayout(self.preview_screen)
        screen_layout.setContentsMargins(8, 8, 8, 8)
        screen_layout.setSpacing(4)
        # Imagen real del invitado (oculta hasta que llega una captura).
        self.preview_image = QLabel()
        self.preview_image.setObjectName("previewImage")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.hide()
        screen_layout.addWidget(self.preview_image)
        screen_layout.addStretch()
        self.preview_screen_name = QLabel("Sin selección")
        self.preview_screen_name.setObjectName("previewScreenName")
        self.preview_screen_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_screen_name.setWordWrap(True)
        self.preview_screen_hint = QLabel("Selecciona una máquina")
        self.preview_screen_hint.setObjectName("previewScreenHint")
        self.preview_screen_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        screen_layout.addWidget(self.preview_screen_name)
        screen_layout.addWidget(self.preview_screen_hint)
        screen_layout.addStretch()
        layout.addWidget(self.preview_screen)

        self.preview_status = QLabel("")
        self.preview_status.setObjectName("mutedLabel")
        self.preview_host = QLabel("")
        self.preview_host.setObjectName("mutedLabel")
        self.preview_host.setWordWrap(True)
        layout.addWidget(self.preview_status)
        layout.addWidget(self.preview_host)

        self.preview_console_button = QPushButton("Consola")
        self.preview_console_button.clicked.connect(self.open_console)
        self.preview_console_button.setEnabled(False)
        layout.addWidget(self.preview_console_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return panel

    def _build_vm_bottom_strip(self) -> QWidget:
        """Tira inferior colapsable con la comprobación inicial y el registro."""
        strip = QWidget()
        layout = QVBoxLayout(strip)
        layout.setContentsMargins(10, 0, 10, 6)
        layout.setSpacing(4)

        toggle_row = QHBoxLayout()
        self.logs_toggle_button = QPushButton("▸  Registro de actividad")
        self.logs_toggle_button.setObjectName("ghostButton")
        self.logs_toggle_button.setCheckable(True)
        self.logs_toggle_button.toggled.connect(self._toggle_activity_strip)
        toggle_row.addWidget(self.logs_toggle_button)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        self._activity_container = QWidget()
        container = QVBoxLayout(self._activity_container)
        container.setContentsMargins(0, 0, 0, 0)
        container.setSpacing(8)
        container.addWidget(self._build_preflight_box())
        container.addWidget(self._build_logs_panel())
        self._activity_container.setVisible(False)
        layout.addWidget(self._activity_container)
        return strip

    def _toggle_activity_strip(self, checked: bool) -> None:
        self._activity_container.setVisible(checked)
        self.logs_toggle_button.setText(
            "▾  Registro de actividad" if checked else "▸  Registro de actividad"
        )

    def _build_preflight_box(self) -> QWidget:
        self.preflight_summary = QLabel("Comprobación inicial pendiente")
        self.preflight_summary.setObjectName("preflightSummary")
        self.preflight_details_button = QPushButton("Ver detalles")
        self.preflight_details_button.setObjectName("ghostButton")
        self.preflight_details_button.setCheckable(True)
        self.preflight_details_button.toggled.connect(self.toggle_preflight_details)
        self.preflight_table = QTableWidget(0, 3)
        self.preflight_table.setHorizontalHeaderLabels(["Estado", "Detalle", "Comando sugerido"])
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
        return preflight_box

    def _build_lab_box(self) -> QWidget:
        lab_box = QFrame()
        lab_box.setObjectName("panel")
        lab_layout = QVBoxLayout(lab_box)
        lab_layout.setContentsMargins(16, 14, 16, 14)
        lab_layout.setSpacing(8)
        lab_header = QHBoxLayout()
        lab_title = QLabel("Detalles del laboratorio")
        lab_title.setObjectName("sectionTitle")
        self.new_vm_in_lab_button = self._button("Nueva máquina en el laboratorio", self.new_vm_in_selected_lab, primary=True)
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
        self.lab_detail_tabs.addTab(self.lab_details_text, "Detalles")
        self.lab_detail_tabs.addTab(self.lab_topology, "Topología")
        lab_layout.addLayout(lab_header)
        lab_layout.addWidget(self.lab_detail_tabs)
        return lab_box

    def _build_hidden_compat_holder(self) -> QWidget:
        """Construye los widgets heredados que render_*/tests referencian pero
        que ya no forman parte de la vista principal VM-first (quedan ocultos).
        Los laboratorios se gestionan desde el menú Ver → Laboratorios."""
        holder = QWidget()
        holder.setObjectName("compatHolder")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Barra de acciones clásica: set_busy/update_actions referencian sus
        # botones, que ahora viven en la barra de herramientas.
        self._vm_actions_bar = self._build_vm_actions_bar()
        layout.addWidget(self._vm_actions_bar)

        # Etiqueta de selección heredada (la cabecera del detalle ya muestra
        # nombre + estado).
        self.selection_label = QLabel("Ninguna máquina seleccionada")
        self.selection_label.setObjectName("sectionTitle")
        layout.addWidget(self.selection_label)

        self.refresh_labs_button = self._button("Actualizar laboratorios", self.refresh_labs)
        layout.addWidget(self.refresh_labs_button)

        self.lab_table = QTableWidget(0, 6)
        self.lab_table.setHorizontalHeaderLabels(["Nombre", "ID", "Modo", "Subred", "Puente", "VMs"])
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

        self.new_lab_button = self._button("Nuevo laboratorio", self.new_lab, primary=True)
        self.rename_lab_button = self._button("Renombrar", self.rename_lab)
        self.delete_lab_button = self._button("Eliminar", self.delete_lab, danger=True)
        self.duplicate_lab_button = self._button("Duplicar", self.duplicate_lab)
        self.export_lab_button = self._button("Exportar", self.export_lab)
        self.import_lab_button = self._button("Importar", self.import_lab)
        for button in (
            self.new_lab_button,
            self.rename_lab_button,
            self.delete_lab_button,
            self.duplicate_lab_button,
            self.export_lab_button,
            self.import_lab_button,
        ):
            layout.addWidget(button)

        layout.addWidget(self._build_lab_box())

        holder.hide()
        return holder

    def toggle_preflight_details(self, checked: bool) -> None:
        self.preflight_table.setVisible(checked)
        self.preflight_details_button.setText("Ocultar detalles" if checked else "Ver detalles")

    def _build_detail_area(self) -> QWidget:
        self.detail_panel = VmDetailPanel()
        self.detail_panel.consoleRequested.connect(self.open_console)
        self.detail_panel.snapshotsRequested.connect(self.snapshots_vm)
        self.detail_panel.settingsRequested.connect(self.settings_vm)
        self.detail_panel.newVmRequested.connect(self.new_vm)
        return self.detail_panel

    def _build_main_empty_state(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("emptyPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(34, 34, 34, 34)
        layout.setSpacing(18)
        title = QLabel("Ninguna máquina seleccionada")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Selecciona una máquina de la lista o crea una nueva.")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        cards.addWidget(self._quick_card("Nueva máquina", "Crear desde una ISO local", self.new_vm, primary=True), 0, 0)
        cards.addWidget(self._quick_card("Actualizar", "Recargar máquinas, laboratorios y equipos", self.refresh_all), 0, 1)
        cards.addWidget(self._quick_card("Ver registro", "Ir a la actividad reciente", self.focus_logs), 0, 2)
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
        for name in ("General", "Sistema", "Consola", "Almacenamiento", "Red", "Instantáneas", "Registros"):
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
        title = QLabel("Registro de actividad")
        title.setObjectName("sectionTitle")
        copy = QPushButton("Copiar")
        copy.setObjectName("ghostButton")
        copy.clicked.connect(self.copy_logs)
        refresh = QPushButton("Actualizar")
        refresh.setObjectName("ghostButton")
        refresh.clicked.connect(self.refresh_logs)
        clear = QPushButton("Limpiar vista")
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
        self.status.showMessage("Registro copiado al portapapeles", 2500)

    def clear_log_view(self) -> None:
        self.activity_log.clear()
        self.status.showMessage("Vista del registro limpiada", 2500)

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
            self.v1_refresh_all_button,
            self.v1_export_button,
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
        if hasattr(self, "toolbar"):
            self.toolbar.setEnabled(not busy)
        if busy:
            self.status.showMessage(label)
        else:
            self.status.showMessage("Listo")
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
        # Sincroniza las acciones de la barra de herramientas y el menú Máquina.
        self.act_settings_vm.setEnabled(has_vm and shut_off)
        self.act_start.setEnabled(has_vm and not running)
        self.act_shutdown.setEnabled(has_vm and running)
        self.act_force.setEnabled(has_vm and running)
        self.act_console.setEnabled(has_vm and running)
        self.act_ext_console.setEnabled(has_vm and running)
        self.act_snapshots.setEnabled(has_vm)
        self.act_clone.setEnabled(has_vm and shut_off)
        self.act_migrate.setEnabled(has_vm)
        self.act_gpu.setEnabled(has_vm and shut_off)
        self.act_delete.setEnabled(has_vm and shut_off)
        if hasattr(self, "detail_panel"):
            self.detail_panel.set_console_enabled(has_vm and running)
            self.detail_panel.set_settings_enabled(has_vm and shut_off)
        if hasattr(self, "preview_console_button"):
            self.preview_console_button.setEnabled(has_vm and running)
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
            "Cargando equipos remotos",
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
        self.remote_status_label.setText(f"{len(hosts)} equipo(s)")
        if hosts:
            self.remote_detail.setPlainText(details_block(("Hub", self.registry_url()), ("Estado", "accesible")))
        else:
            self.remote_detail.setPlainText(
                "El Hub responde pero no tiene equipos. Arranca el agente de HyperGery en cada equipo."
            )
        self.render_hub_status(hosts, reachable=True, vm_count=vm_count)
        self.update_actions()

    def render_hub_status(self, hosts: list[dict[str, Any]], *, reachable: bool, vm_count: int | None = None) -> None:
        config = effective_config()
        nas_path = os.path.expanduser(config["nas_staging_path"].value)
        nas_writable = os.path.isdir(nas_path) and os.access(nas_path, os.W_OK)
        nas_label = "Listo para migraciones" if nas_writable else "No escribible — revisa el montaje"
        vm_count_label = "desconocido"
        if reachable:
            vm_count_label = str(vm_count) if vm_count is not None else "no disponible"
        self.hub_url_label.setText(self.registry_url())
        self.hub_status_label.setText("EN LÍNEA" if reachable else "SIN CONEXIÓN")
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
        self.hub_nas_label.setToolTip(nas_path)
        self.hub_chip.setText(f"Hub: {'en línea' if reachable else 'sin conexión'}")
        self.hub_chip.setObjectName("statusChipOk" if reachable else "statusChipBad")
        self.nas_chip.setText(f"NAS: {'funciona' if nas_writable else 'no escribible'}")
        self.nas_chip.setObjectName("statusChipOk" if nas_writable else "statusChipBad")
        self.host_chip.setText(f"Equipo: {config['host_id'].value}")
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
            self.show_error("Selecciona un equipo remoto primero.")
            return
        host = self.remote_hosts[index] if 0 <= index < len(self.remote_hosts) else None
        if not host:
            self.show_error("El equipo seleccionado ya no está disponible.")
            return
        self._queue_host_test(str(host.get("host_id", "")))

    def refresh_all(self) -> None:
        self.status.showMessage("Cargando estado del equipo…")
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
            self.preflight_summary.setText(f"Comprobación inicial no disponible: {errors['preflight']}")
        if "vms" in overview:
            self.render_vms(overview["vms"])
        elif "vms" in errors:
            self.render_vms([])
            self.status.showMessage(f"Lista de máquinas no disponible: {errors['vms']}", 5000)
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
            self.remote_status_label.setText("Hub no disponible")
            self.hub_latency_label.setText("—")
            self.render_hub_status([], reachable=False)
            self.remote_detail.setPlainText(
                "Hub not reachable. Set HYPERGERY_HUB_URL or start docker compose in docker/.\n"
                f"Current Hub URL: {self.registry_url()}\n"
                f"Example: export HYPERGERY_HUB_URL=http://192.168.1.150:8765\n\n{errors['remote_hosts']}"
            )
        self.render_selected()
        self._update_battery_chip()
        if not errors:
            self.status.showMessage("Listo")
        else:
            self.status.showMessage("Cargado con avisos", 5000)

    def refresh_preflight(self) -> None:
        try:
            items = self.backend.preflight()
        except Exception as exc:
            self.preflight_summary.setText(f"Comprobación inicial no disponible: {exc}")
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
            self.preflight_summary.setText(f"Equipo bloqueado · {passed}/{total} comprobaciones superadas")
            self.preflight_summary.setObjectName("errorLabel")
        elif counts["Warning"]:
            self.preflight_summary.setText(f"Equipo listo con avisos · {passed}/{total} comprobaciones superadas")
            self.preflight_summary.setObjectName("mutedLabel")
        else:
            self.preflight_summary.setText(f"Equipo listo · {passed}/{total} comprobaciones superadas")
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
        self.vms = filter_vms_for_lab(vms, selected_lab_id, self.vm_filter.currentText() == "Laboratorio seleccionado")
        self.vm_tree.populate(self.vms, self.labs)
        if current:
            self.vm_tree.select_vm_by_name(current)
        if not self.vms:
            self.selected_vm = None
        running = sum(1 for vm in self.vms if state_kind(vm.state) == "running")
        suffix = "" if len(self.vms) == 1 else "s"
        total_suffix = "" if len(self.all_vms) == 1 else "s"
        if self.vm_filter.currentText() == "Laboratorio seleccionado" and selected_lab_id:
            self.vm_count_label.setText(f"{len(self.vms)} mostradas / {len(self.all_vms)} máquina{total_suffix}")
        else:
            self.vm_count_label.setText(f"{len(self.vms)} máquina{suffix}, {running} encendidas")
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
        if self.vm_filter.currentText() == "Laboratorio seleccionado":
            self.render_vms(self.all_vms)
        self.update_actions()

    def on_vm_filter_changed(self) -> None:
        self.render_vms(self.all_vms)

    def update_vm_empty_state(self) -> None:
        if self.vm_filter.currentText() == "Laboratorio seleccionado" and self.selected_lab is not None:
            self.vm_empty_title.setText("Este laboratorio aún no tiene máquinas")
            self.vm_empty_subtitle.setText(f"Crea una máquina en {self.selected_lab_id()} desde una ISO.")
            self.vm_empty_button.setText("Nueva máquina en el laboratorio")
        else:
            self.vm_empty_title.setText("Todavía no hay máquinas virtuales")
            self.vm_empty_subtitle.setText("Crea tu primera máquina desde una ISO.")
            self.vm_empty_button.setText("Nueva máquina")

    def render_lab_details(self) -> None:
        lab = self.selected_lab
        if lab is None:
            self.lab_details_text.setPlainText("Ningún laboratorio seleccionado.")
            self.lab_topology.set_topology(None)
            return
        templates_used = lab.get("templates_used", [])
        self.lab_details_text.setPlainText(
            details_block(
                ("Nombre", str(lab.get("name") or lab.get("lab_id", ""))),
                ("ID", str(lab.get("lab_id", ""))),
                ("Descripción", str(lab.get("description") or "")),
                ("ID de red", str(lab.get("network_id", ""))),
                ("Modo de red", str(lab.get("network_mode", ""))),
                ("Subred", str(lab.get("subnet", ""))),
                ("Puente", str(lab.get("bridge_name", ""))),
                ("Nº de máquinas", str(vm_count_for_lab(lab, self.all_vms))),
                ("Plantillas usadas", ", ".join(templates_used) if templates_used else "ninguna"),
                ("Creado", str(lab.get("created_at", ""))),
                ("Actualizado", str(lab.get("updated_at", ""))),
                ("Notas", str(lab.get("notes", ""))),
            )
        )
        self.lab_topology.set_topology(build_lab_topology(lab, self.all_vms))

    def _select_vm_by_name(self, vm_name: str) -> None:
        self._show_section("Máquinas virtuales")
        if self.vm_tree.select_vm_by_name(vm_name):
            self.lab_detail_tabs.setCurrentIndex(0)

    def log_activity(self, message: str) -> None:
        logging.info(message)
        current = self.activity_log.toPlainText()
        text = f"{now_iso()} INFO {message}"
        self.activity_log.setPlainText(f"{current.rstrip()}\n{text}".strip())
        self.activity_log.moveCursor(QTextCursor.MoveOperation.End)

    def selected_lab_or_error(self) -> dict[str, Any]:
        if self.selected_lab is None:
            raise HyperGeryError("Selecciona un laboratorio primero.")
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
            self.log_activity(f"No se ha podido crear el laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = lab
        self.log_activity(f"Creado laboratorio {lab['lab_id']}")
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
            self.log_activity(f"No se ha podido renombrar el laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = updated
        self.log_activity(f"Renombrado laboratorio {updated['lab_id']}")
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
            self.log_activity(f"No se ha podido eliminar el laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab = None
        self.log_activity(f"Eliminado laboratorio {lab['lab_id']}")
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
            self.log_activity(f"Duplicado laboratorio {source_lab_id} en {duplicate['lab_id']}")
            self.refresh_labs()

        action_label = f"Duplicando laboratorio {source_lab_id}" + (" with VM cloning" if clone_vms else "")
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
            "Exportar laboratorio",
            f"{lab_id}.json",
            "Manifiesto de laboratorio (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.lab_store().export_lab(lab_id, path)
        except Exception as exc:
            self.log_activity(f"No se ha podido exportar el laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exportado laboratorio {lab_id} a {output}")
        self.status.showMessage(f"Exportado {lab_id}", 3500)
        self.refresh_labs()

    def import_lab(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Importar laboratorio",
            "",
            "Manifiesto de laboratorio (*.json);;Todos los archivos (*)",
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
                    "Importar laboratorio",
                    f"{exc}\n\nImport with a new lab ID:",
                )
                if not ok or not new_lab_id.strip():
                    self.log_activity(f"Importación de laboratorio cancelada: {exc}")
                    return
                try:
                    lab = self.lab_store().import_lab(path, new_lab_id=new_lab_id.strip())
                except Exception as retry_exc:
                    self.log_activity(f"No se ha podido importar el laboratorio: {retry_exc}")
                    self.show_error(str(retry_exc))
                    return
            else:
                self.log_activity(f"No se ha podido importar el laboratorio: {exc}")
                self.show_error(str(exc))
                return
        self.selected_lab = lab
        self.log_activity(f"Importado laboratorio {lab['lab_id']} desde {path}")
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
        self.log_activity(f"No se han podido recargar los laboratorios: {message}")

    def render_labs(self, labs: list[dict[str, Any]], *, keep_selection: bool = False) -> None:
        if not labs and not keep_selection:
            self.selected_lab = None
        current_lab_id = self.selected_lab_id() if keep_selection else ""
        self.labs = labs
        if hasattr(self, "vm_tree"):
            self.vm_tree.populate(self.vms, self.labs)
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
            logs = f"Registro no disponible: {exc}"
        self.render_logs(logs)

    def render_logs(self, logs: str) -> None:
        # Los volcados técnicos (JSON de qemu-img, XML de libvirt) se resumen
        # en español; el detalle completo sigue en el archivo hypergery.log.
        self.activity_log.setPlainText(humanize_activity_log(logs))
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

    def _on_tree_vm_changed(self, vm: VmSummary | None) -> None:
        self.selected_vm = vm
        self.render_selected()
        self.update_actions()

    def _on_tree_vm_activated(self, vm: VmSummary) -> None:
        self.selected_vm = vm
        state = (vm.state or "").lower()
        if "running" in state:
            self.open_console()
        elif "shut" in state or "off" in state:
            self.start_vm()

    def _on_vm_search_text(self, text: str) -> None:
        if hasattr(self, "vm_tree"):
            self.vm_tree.set_filter(text)

    def on_vm_selection_changed(self) -> None:
        # Compatibilidad: la selección ahora la conduce el árbol de VMs.
        self.selected_vm = self.vm_tree.current_vm()
        self.render_selected()
        self.update_actions()

    def render_selected(self) -> None:
        vm = self.selected_vm
        if vm is None:
            self.selection_label.setText("Ninguna máquina seleccionada")
            self.detail_panel.show_welcome()
            self._update_preview(None)
            return
        self.selection_label.setText(
            f"{vm.name}  ·  {humanize_vm_status(vm.state)}  ·  {vm.lab_id or 'sin laboratorio'}"
        )
        try:
            snapshots = self.backend.list_snapshots(vm.name)
        except Exception:
            snapshots = []
        self.detail_panel.show_vm(vm, snapshots, extra=self._hypergery_detail_rows(vm))
        self._update_preview(vm)

    def _hypergery_detail_rows(self, vm: VmSummary) -> list[tuple[str, str]]:
        host_id = effective_config()["host_id"].value
        return [
            ("Equipo (host)", str(host_id)),
            ("Hub", self.registry_url()),
            ("Laboratorio", vm.lab_id or "Sin laboratorio"),
            ("Traslado", "Disponible vía «Mover a otro equipo» (NAS/Hub)"),
        ]

    def _update_preview(self, vm: VmSummary | None) -> None:
        if not hasattr(self, "preview_screen_name"):
            return
        # Cualquier captura en curso queda obsoleta al cambiar de selección.
        self._preview_target = vm.name if vm else None
        self.preview_image.hide()
        self.preview_image.clear()
        self.preview_screen_name.show()
        self.preview_screen_hint.show()
        if vm is None:
            self.preview_screen_name.setText("Sin selección")
            self.preview_screen_hint.setText("Selecciona una máquina")
            self.preview_status.setText("")
            self.preview_host.setText("")
            self.preview_console_button.setEnabled(False)
            return
        self.preview_screen_name.setText(vm.name)
        self.preview_status.setText(humanize_vm_status(vm.state))
        host_id = effective_config()["host_id"].value
        self.preview_host.setText(f"Equipo: {host_id}")
        running = "running" in (vm.state or "").lower() or "paused" in (vm.state or "").lower()
        self.preview_console_button.setEnabled(running)
        if running:
            # Captura real del invitado (off-thread, no bloquea ni modifica la VM).
            self.preview_screen_hint.setText("Capturando vista…")
            self._capture_preview(vm.name)
        else:
            self.preview_screen_hint.setText("Apagada — sin señal de vídeo")

    def _capture_preview(self, name: str) -> None:
        import shutil

        from PySide6.QtGui import QGuiApplication

        # Solo tiene sentido capturar con un display real; en modo «offscreen»
        # (tests/headless) o sin virsh no se lanza ningún proceso ni hilo.
        if QGuiApplication.platformName() == "offscreen" or shutil.which("virsh") is None:
            self._on_preview_captured(name, None)
            return
        self._throttled_capture(name)

    def _throttled_capture(self, name: str) -> None:
        # HG-BUG-0015: una captura en vuelo por VM y un mínimo entre capturas.
        # Si llega una petición durante el periodo de enfriamiento se programa
        # un único reintento al expirar (la vista no se queda obsoleta).
        if name in self._preview_inflight:
            return
        elapsed = self._preview_clock() - self._preview_last_capture.get(name, float("-inf"))
        if elapsed < self.PREVIEW_MIN_INTERVAL_S:
            if name not in self._preview_retry_pending:
                self._preview_retry_pending.add(name)
                delay_ms = max(0, int((self.PREVIEW_MIN_INTERVAL_S - elapsed) * 1000)) + 50
                self._schedule_preview_retry(name, delay_ms)
            return
        self._preview_last_capture[name] = self._preview_clock()
        self._preview_inflight.add(name)
        self._start_preview_capture(name)

    def _schedule_preview_retry(self, name: str, delay_ms: int) -> None:
        QTimer.singleShot(delay_ms, lambda n=name: self._run_preview_retry(n))

    def _run_preview_retry(self, name: str) -> None:
        self._preview_retry_pending.discard(name)
        # Solo si la VM sigue siendo la seleccionada.
        if name == self._preview_target:
            self._capture_preview(name)

    def _start_preview_capture(self, name: str) -> None:
        from .screenshot import capture_vm_screenshot

        self.job_manager.submit(
            f"preview:{name}",
            lambda n=name: capture_vm_screenshot(n),
            on_success=lambda job, n=name: self._on_preview_captured(n, job.result),
            on_finished=lambda job, n=name: self._preview_inflight.discard(n),
            track_history=False,
        )

    def _on_preview_captured(self, name: str, data: bytes | None) -> None:
        # Ignora resultados de una VM que ya no está seleccionada.
        if name != self._preview_target or not hasattr(self, "preview_image"):
            return
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            self.preview_screen_hint.setText("Sin vista disponible")
            return
        width = max(180, self.preview_screen.width() - 16)
        scaled = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self.preview_image.setPixmap(scaled)
        self.preview_image.show()
        self.preview_screen_name.hide()
        self.preview_screen_hint.hide()

    def selected_name(self) -> str:
        if self.selected_vm is None:
            raise HyperGeryError("Selecciona una máquina primero.")
        return self.selected_vm.name

    def show_error(self, message: str) -> None:
        # Jerga técnica (virsh, archivos que faltan…) → resumen humano con el
        # detalle técnico al final; los mensajes ya claros pasan sin cambios.
        human = humanize_error_message(message)
        self.status.showMessage(human.splitlines()[0] if human else human)
        QMessageBox.critical(self, "HyperGery", human)
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

        def succeeded(job: BackendJob) -> None:
            if on_success:
                on_success(job.result)
            if refresh_after:
                self.refresh_all()
            if busy or refresh_after:
                self.status.showMessage("Listo")

        def failed(job: BackendJob) -> None:
            self.show_error(job.error_message)
            self.status.showMessage("Listo")

        def finished(job: BackendJob) -> None:
            if busy:
                self.set_busy(False)
            else:
                self.update_actions()

        self.job_manager.submit(
            label,
            fn,
            on_success=succeeded,
            on_failure=failed,
            on_finished=finished,
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        # HG-BUG-0008: sin esto, los BackendJob seguían vivos al cerrar la
        # ventana y podían emitir señales contra widgets destruidos.
        for window in list(self.console_windows.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        survivors = self.job_manager.shutdown(timeout_ms=self.CLOSE_WAIT_MS)
        if survivors:
            logging.warning(
                "Cerrando con %d job(s) aún en ejecución: %s",
                len(survivors),
                ", ".join(survivors),
            )
        super().closeEvent(event)

    def new_vm_from_empty(self) -> None:
        if self.vm_filter.currentText() == "Laboratorio seleccionado" and self.selected_lab is not None:
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
        # UI estilo VirtualBox: una ventana con secciones plegables y sliders.
        wizard = VBoxStyleVMCreator(self, default_lab_id=default_lab_id)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        if not confirm(
            self,
            "Crear máquina",
            (
                f"¿Crear {values['name']}?\n\n"
                f"ISO: {values['iso_path']}\n"
                f"RAM: {values['ram_mib']} MiB\n"
                f"vCPUs: {values['vcpus']}\n"
                f"Disco: {values['disk_gb']} GiB\n"
                f"Red: {values['network_mode']}\n"
                f"Laboratorio: {values['lab_id']}"
            ),
            yes_text="Crear",
            no_text="Cancelar",
        ):
            return
        self.run_operation(f"Creando {values['name']}", lambda: self.backend.create_vm(**values))

    def app_settings(self) -> None:
        dialog = AppSettingsDialog(self.backend, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            HyperGeryConfig(**dialog.values()).save()
        except (OSError, HyperGeryError, ValueError) as exc:
            self.show_error(f"No se han podido guardar los ajustes: {exc}")
            return
        self.status.showMessage("Ajustes guardados", 5000)

    def settings_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        dialog = SettingsDialog(self.selected_vm, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if QMessageBox.question(self, "Guardar ajustes", f"¿Aplicar los ajustes a {self.selected_vm.name}?") != QMessageBox.StandardButton.Yes:
            return
        self.run_operation(f"Guardando ajustes de {self.selected_vm.name}", lambda: self.backend.update_settings(**values))

    def start_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        # Si la VM tiene una ISO conectada (instalación), abre la consola al
        # encender para que el usuario llegue a tiempo al «Press any key to boot
        # from CD» (la ventana dura ~5 s; si abres la consola tarde, la pierdes).
        vm = self.selected_vm
        has_install_iso = bool(vm and getattr(vm, "iso_path", ""))

        def after_start(_result) -> None:
            if has_install_iso:
                self.open_console(force_connect=True)
                # «Press any key to boot from CD»: pulsa espacio por libvirt
                # (send-key) durante la ventana de arranque — funciona con
                # cualquier display (SPICE o VNC), sin depender de la consola.
                from .workers import BackendJob

                sweep = BackendJob("boot keypress sweep", lambda: self.backend.boot_keypress_sweep(name))
                # NUNCA soltar la última referencia dentro de `finished` (PySide
                # destruiría el QThread aún vivo → crash). Se poda en el
                # siguiente arranque: un QThread terminado en la lista es inocuo.
                jobs = [job for job in getattr(self, "_boot_sweep_jobs", []) if not job.isFinished()]
                jobs.append(sweep)
                self._boot_sweep_jobs = jobs
                sweep.start()

        self.run_operation(
            f"Encendiendo {name}",
            lambda: self.backend.start_vm(name),
            on_success=after_start,
        )

    def shutdown_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Pidiendo apagado suave de {name}", lambda: self.backend.shutdown_vm(name))

    def force_off_vm(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        if not confirm(
            self,
            "Apagar a la fuerza",
            f"¿Apagar {name} a la fuerza?\n\nEquivale a desenchufarla y puede corromper datos del sistema invitado.",
            no_text="Cancelar",
            danger=True,
        ):
            return
        self.run_operation(f"Apagando a la fuerza {name}", lambda: self.backend.force_off_vm(name))

    def open_console(self, *, force_connect: bool = False) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
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
        # force_connect: tras encender (instalación), el estado en caché aún es
        # «apagada»; conectamos igualmente porque la VM ya está arrancando.
        if not window.console.is_connected() and (
            force_connect or should_autoconnect_console(vm.graphics, vm.state)
        ):
            # (El «Press any key» del instalador lo cubre el barrido send-key
            # de start_vm, que funciona con cualquier display.)
            window.console.connect_console()

    def open_external_console(self) -> None:
        try:
            name = self.selected_name()
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        self.run_operation(f"Abriendo consola externa de {name}", lambda: self.backend.open_console(name))

    def snapshots_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        SnapshotDialog(self.backend, self.selected_vm.name, self).exec()

    def clone_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        dialog = CloneDialog(self.selected_vm.name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        clone_name = dialog.clone_name()
        if QMessageBox.question(self, "Clonar máquina", f"¿Crear el clon {clone_name} a partir de {self.selected_vm.name}?") != QMessageBox.StandardButton.Yes:
            return
        source = self.selected_vm.name
        self.run_operation(f"Clonando {source}", lambda: self.backend.clone_vm(source, clone_name))

    def live_migration_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        dialog = LiveMigrationDialog(self.backend, self.selected_vm, self)
        dialog.exec()
        if dialog.last_result:
            self.log_activity(
                "Traslado remoto encolado: "
                f"migration_id={dialog.last_result.get('migration_id', '')} "
                f"command_id={dialog.last_result.get('command_id', '')} "
                f"package={dialog.last_result.get('package_dir', '')}"
            )

    def gpu_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        vm = self.selected_vm
        try:
            dialog = GpuPassthroughDialog(self.backend, vm, self)
        except HyperGeryError as exc:
            self.show_error(str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        from ..v1 import gpu_passthrough as gpu_mod

        if dialog.action == "attach":
            row = dialog.selected_row()
            if row is None:
                return
            address = row["address"]
            self.run_operation(
                f"Conectando GPU {address} a {vm.name}",
                lambda: gpu_mod.attach_gpu_to_vm(self.backend, vm.name, address, confirm=True),
                on_success=lambda result: self._show_gpu_attach_result(vm.name, result),
            )
        elif dialog.action == "detach":
            self.run_operation(
                f"Quitando GPU de {vm.name}",
                lambda: gpu_mod.detach_gpus_from_vm(self.backend, vm.name, confirm=True),
            )

    def _show_gpu_attach_result(self, vm_name: str, result: dict) -> None:
        warnings = [w for w in result.get("warnings", []) if w]
        gpu = result.get("gpu") or {}
        lines = [f"GPU {gpu.get('address', '')} conectada a {vm_name}."]
        if warnings:
            lines.append("")
            lines.extend(f"• {warning}" for warning in warnings)
        QMessageBox.information(self, "GPU conectada", "\n".join(lines))

    def delete_vm(self) -> None:
        if self.selected_vm is None:
            self.show_error("Selecciona una máquina primero.")
            return
        vm = self.selected_vm
        dialog = DeleteConfirmationDialog(vm, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.run_operation(f"Eliminando {vm.name}", lambda: self.backend.delete_vm(vm.name, delete_disks=dialog.delete_disks()))

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
                ("Nombre", str(tmpl.get("name", ""))),
                ("ID de plantilla", str(tmpl.get("template_id", ""))),
                ("OS Type", str(tmpl.get("os_type", ""))),
                ("RAM", format_mib(tmpl.get("ram_mib"))),
                ("vCPUs", str(tmpl.get("vcpus", ""))),
                ("Disco", f"{tmpl.get('disk_gb', '')} GiB"),
                ("Red", str(tmpl.get("network_mode", ""))),
                ("Pantalla", str(tmpl.get("display", ""))),
                ("Notas", str(tmpl.get("notes", ""))),
            )
        )

    def render_lab_template_detail(self) -> None:
        tmpl = self.selected_lab_template
        if tmpl is None:
            self.lab_template_detail.clear()
            return
        self.lab_template_detail.setPlainText(
            details_block(
                ("Nombre", str(tmpl.get("name", ""))),
                ("ID de plantilla", str(tmpl.get("template_id", ""))),
                ("Red", str(tmpl.get("network_mode", ""))),
                ("VMs", str(len(tmpl.get("vms", [])))),
                ("Descripción", str(tmpl.get("description", ""))),
                ("Notas", str(tmpl.get("notes", ""))),
            )
        )

    def refresh_templates(self) -> None:
        try:
            vm_templates = self.template_store.list_vm_templates()
            lab_templates = self.template_store.list_lab_templates()
        except Exception as exc:
            self.log_activity(f"No se han podido recargar las plantillas: {exc}")
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
            self.log_activity(f"No se ha podido crear la plantilla de máquina: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Creada plantilla de máquina {template['template_id']}")
        self.refresh_templates()

    def delete_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Selecciona una plantilla de máquina primero.")
            return
        tmpl = self.selected_vm_template
        dialog = DeleteVmTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.template_store.delete_vm_template(str(tmpl["template_id"]))
        except Exception as exc:
            self.log_activity(f"No se ha podido eliminar la plantilla de máquina: {exc}")
            self.show_error(str(exc))
            return
        self.selected_vm_template = None
        self.log_activity(f"Eliminada plantilla de máquina {tmpl['template_id']}")
        self.refresh_templates()

    def export_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Selecciona una plantilla de máquina primero.")
            return
        tmpl = self.selected_vm_template
        template_id = str(tmpl["template_id"])
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar plantilla de máquina",
            f"{template_id}.json",
            "Plantilla (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.template_store.export_vm_template(template_id, path)
        except Exception as exc:
            self.log_activity(f"No se ha podido exportar la plantilla de máquina: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exportada plantilla de máquina {template_id} a {output}")
        self.status.showMessage(f"Exportada {template_id}", 3500)

    def import_vm_template(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Importar plantilla de máquina",
            "",
            "Plantilla (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            template = self.template_store.import_vm_template(path)
        except Exception as exc:
            if "already exists" in str(exc):
                self.show_error(f"{exc}\n\nBorra antes la plantilla existente y vuelve a importarla.")
            else:
                self.show_error(str(exc))
            self.log_activity(f"No se ha podido importar la plantilla de máquina: {exc}")
            return
        self.log_activity(f"Importada plantilla de máquina {template['template_id']} desde {path}")
        self.refresh_templates()

    def new_lab_template(self) -> None:
        dialog = NewLabTemplateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            template = self.template_store.create_lab_template(**values)
        except Exception as exc:
            self.log_activity(f"No se ha podido crear la plantilla de laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Creada plantilla de laboratorio {template['template_id']}")
        self.refresh_templates()

    def delete_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Selecciona una plantilla de laboratorio primero.")
            return
        tmpl = self.selected_lab_template
        dialog = DeleteLabTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.template_store.delete_lab_template(str(tmpl["template_id"]))
        except Exception as exc:
            self.log_activity(f"No se ha podido eliminar la plantilla de laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab_template = None
        self.log_activity(f"Eliminada plantilla de laboratorio {tmpl['template_id']}")
        self.refresh_templates()

    def export_action_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Selecciona una plantilla de laboratorio primero.")
            return
        tmpl = self.selected_lab_template
        template_id = str(tmpl["template_id"])
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar plantilla de laboratorio",
            f"{template_id}.json",
            "Plantilla (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            output = self.template_store.export_lab_template(template_id, path)
        except Exception as exc:
            self.log_activity(f"No se ha podido exportar la plantilla de laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.log_activity(f"Exportada plantilla de laboratorio {template_id} a {output}")
        self.status.showMessage(f"Exportada {template_id}", 3500)

    def import_action_lab_template(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Importar plantilla de laboratorio",
            "",
            "Plantilla (*.json);;Todos los archivos (*)",
            "",
            FILE_DIALOG_OPTIONS,
        )
        if not path:
            return
        try:
            template = self.template_store.import_lab_template(path)
        except Exception as exc:
            if "already exists" in str(exc):
                self.show_error(f"{exc}\n\nBorra antes la plantilla existente y vuelve a importarla.")
            else:
                self.show_error(str(exc))
            self.log_activity(f"No se ha podido importar la plantilla de laboratorio: {exc}")
            return
        self.log_activity(f"Importada plantilla de laboratorio {template['template_id']} desde {path}")
        self.refresh_templates()

    def create_vm_from_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Selecciona una plantilla de máquina primero.")
            return
        tmpl = self.selected_vm_template
        template_id = str(tmpl["template_id"])
        wizard = VMWizard(self, defaults=tmpl)
        wizard.setWindowTitle(f"Crear máquina desde plantilla: {template_id}")
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        values = wizard.values()
        if not confirm(
            self,
            "Crear máquina desde plantilla",
            (
                f"¿Crear {values['name']} desde la plantilla {template_id}?\n\n"
                f"ISO: {values['iso_path']}\n"
                f"RAM: {values['ram_mib']} MiB\n"
                f"vCPUs: {values['vcpus']}\n"
                f"Disco: {values['disk_gb']} GiB\n"
                f"Red: {values['network_mode']}\n"
                f"Laboratorio: {values['lab_id']}"
            ),
            yes_text="Crear",
            no_text="Cancelar",
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

        self.log_activity(f"Creando {values['name']} desde la plantilla {template_id}")
        self.run_operation(
            f"Creando {values['name']} desde plantilla",
            lambda: self.backend.create_vm(**values),
            on_success=record_template_used,
        )

    def create_lab_from_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Selecciona una plantilla de laboratorio primero.")
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
                self.log_activity(f"No se ha podido crear el laboratorio desde la plantilla:\n{errs}")
                self.show_error(f"No se ha podido crear el laboratorio:\n{errs}")
                return
            lab = result.get("lab")
            if lab:
                self.selected_lab = lab
                created = len(result.get("vms_created", []))
                warnings = result.get("warnings", [])
                msg = f"Creado laboratorio {lab['lab_id']} desde la plantilla {template_id} ({created}/{planned_vm_count} máquinas)"
                if warnings:
                    msg += f"\nWarnings: {'; '.join(warnings)}"
                self.log_activity(msg)
            self.refresh_labs()
            self.refresh_templates()

        self.log_activity(f"Creando laboratorio '{lab_name}' desde la plantilla {template_id}…")
        self.run_operation(
            f"Creando laboratorio desde la plantilla {template_id}",
            do_instantiate,
            on_success=on_instantiate_done,
        )

    def edit_vm_template(self) -> None:
        if self.selected_vm_template is None:
            self.show_error("Selecciona una plantilla de máquina primero.")
            return
        tmpl = self.selected_vm_template
        dialog = EditVmTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            updated = self.template_store.update_vm_template(str(tmpl["template_id"]), **values)
        except Exception as exc:
            self.log_activity(f"No se ha podido editar la plantilla de máquina: {exc}")
            self.show_error(str(exc))
            return
        self.selected_vm_template = updated
        self.log_activity(f"Actualizada plantilla de máquina {updated['template_id']}")
        self.refresh_templates()

    def edit_lab_template(self) -> None:
        if self.selected_lab_template is None:
            self.show_error("Selecciona una plantilla de laboratorio primero.")
            return
        tmpl = self.selected_lab_template
        dialog = EditLabTemplateDialog(tmpl, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            updated = self.template_store.update_lab_template(str(tmpl["template_id"]), **values)
        except Exception as exc:
            self.log_activity(f"No se ha podido editar la plantilla de laboratorio: {exc}")
            self.show_error(str(exc))
            return
        self.selected_lab_template = updated
        self.log_activity(f"Actualizada plantilla de laboratorio {updated['template_id']}")
        self.refresh_templates()
