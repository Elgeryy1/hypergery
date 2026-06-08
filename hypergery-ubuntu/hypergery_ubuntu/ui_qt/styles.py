from __future__ import annotations

from .formatting import format_mib

APP_DISPLAY_VERSION = "1.1-dev"

# Tema VirtualBox 7 (modo oscuro). Sustituye al antiguo tema navy/cyan v0.7.
# El objetivo es parecerse al máximo al gestor de VirtualBox: grises neutros,
# selección azul, acentos sobrios y mucho contraste de texto.
DESIGN_TOKENS = {
    "bg": "#1e1e1e",          # fondo de ventana
    "bg_alt": "#252525",      # fondo de filas alternas
    "surface": "#2d2d2d",     # paneles y tarjetas
    "surface_2": "#333333",   # campos de entrada
    "elevated": "#3c3c3c",    # toolbar, cabeceras
    "border": "#555555",      # bordes estándar
    "border_soft": "#444444", # bordes suaves
    "accent": "#2a82da",      # azul de selección (estilo VirtualBox)
    "accent_3": "#3d8ee0",
    "running": "#3cb449",     # VM encendida
    "warning": "#f0a30a",     # VM en pausa / avisos
    "danger": "#c42b1c",      # error / apagado forzado
    "offline": "#888888",     # VM apagada
    "text": "#dddddd",        # texto principal
    "text_dim": "#aaaaaa",    # texto secundario
    "text_faint": "#777777",  # texto tenue / placeholder
}

STATE_COLORS = {
    "running": "#3cb449",
    "shutoff": "#888888",
    "paused": "#f0a30a",
    "unknown": "#888888",
}

STATE_BACKGROUNDS = {
    "running": "#1f3a24",
    "shutoff": "#333333",
    "paused": "#3a300f",
    "unknown": "#333333",
}

STATE_LABELS = {
    "running": "ENCENDIDA",
    "shutoff": "APAGADA",
    "paused": "EN PAUSA",
    "unknown": "DESCONOCIDA",
}


def state_kind(state: str) -> str:
    value = state.lower()
    if "running" in value:
        return "running"
    if "paused" in value:
        return "paused"
    if "shut" in value or "off" in value:
        return "shutoff"
    return "unknown"


def details_block(*rows: tuple[str, str]) -> str:
    width = max((len(label) for label, _value in rows), default=0)
    return "\n".join(f"{label:<{width}}  {value}" for label, value in rows)


APP_STYLESHEET = """
QMainWindow, QDialog, QWizard {
    background: #1e1e1e;
    color: #dddddd;
    font-family: "Segoe UI", "Inter", "Ubuntu", "Sans";
    font-size: 10pt;
}
QWidget {
    color: #dddddd;
}

/* ---------- Barra de menús estilo VirtualBox ---------- */
QMenuBar {
    background: #2d2d2d;
    color: #dddddd;
    border-bottom: 1px solid #444444;
    padding: 2px 4px;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background: #3c3c3c;
}
QMenuBar::item:pressed {
    background: #2a82da;
    color: #ffffff;
}
QMenu {
    background: #2d2d2d;
    color: #dddddd;
    border: 1px solid #555555;
    padding: 4px;
}
QMenu::item {
    padding: 6px 26px 6px 22px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #2a82da;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #777777;
}
QMenu::separator {
    height: 1px;
    background: #444444;
    margin: 4px 8px;
}

/* ---------- Toolbar de iconos grandes ---------- */
QToolBar {
    background: #3c3c3c;
    border: 0;
    border-bottom: 1px solid #2a2a2a;
    padding: 4px 8px;
    spacing: 2px;
}
QToolBar::separator {
    width: 1px;
    background: #555555;
    margin: 4px 6px;
}
QToolButton {
    background: transparent;
    color: #dddddd;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 8px;
    margin: 1px;
}
QToolButton:hover {
    background: #4a4a4a;
    border-color: #5a5a5a;
}
QToolButton:pressed {
    background: #2a82da;
}
QToolButton:checked {
    background: #2a82da;
    border-color: #2a82da;
}
QToolButton:disabled {
    color: #6d6d6d;
}

QFrame#topBar {
    background: #2d2d2d;
    border-bottom: 1px solid #444444;
}
QLabel#brandTitle {
    font-size: 16pt;
    font-weight: 700;
    color: #f0f0f0;
}
QLabel#brandSubtle, QLabel#mutedLabel {
    color: #aaaaaa;
}
QLabel#sectionTitle {
    font-size: 11.5pt;
    font-weight: 700;
    color: #f0f0f0;
}
QLabel#heroTitle {
    font-size: 17pt;
    font-weight: 700;
    color: #f4f4f4;
}
QLabel#heroSubtitle {
    font-size: 10.5pt;
    color: #aaaaaa;
}
QLabel#preflightSummary {
    font-size: 11.5pt;
    font-weight: 700;
    color: #e6e6e6;
}
QPushButton {
    background: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 5px;
    color: #eeeeee;
    padding: 7px 12px;
}
QPushButton:hover {
    background: #474747;
    border-color: #2a82da;
}
QPushButton:disabled {
    background: #2a2a2a;
    border-color: #3a3a3a;
    color: #6d6d6d;
}
QPushButton#primaryButton {
    background: #2a82da;
    border-color: #3d8ee0;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #3d8ee0;
}
QPushButton#dangerButton {
    background: #4a2420;
    border-color: #c42b1c;
    color: #ffb4ab;
    font-weight: 700;
}
QPushButton#dangerButton:hover {
    background: #5e2c26;
}
QPushButton#ghostButton {
    background: #333333;
    border-color: #4a4a4a;
    color: #cccccc;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QListWidget, QTableWidget, QTreeWidget {
    background: #333333;
    border: 1px solid #555555;
    border-radius: 5px;
    color: #eeeeee;
    selection-background-color: #2a82da;
    selection-color: #ffffff;
    padding: 4px;
}
QComboBox QAbstractItemView {
    background: #2d2d2d;
    border: 1px solid #555555;
    selection-background-color: #2a82da;
}
QTableWidget {
    gridline-color: #404040;
    alternate-background-color: #2a2a2a;
}
QHeaderView::section {
    background: #3c3c3c;
    color: #cccccc;
    border: 0;
    border-bottom: 1px solid #555555;
    padding: 7px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #555555;
    border-radius: 6px;
    top: -1px;
    background: #262626;
}
QTabBar::tab {
    background: #2d2d2d;
    border: 1px solid #444444;
    color: #aaaaaa;
    padding: 7px 14px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
}
QTabBar::tab:selected {
    background: #3c3c3c;
    color: #ffffff;
    border-bottom-color: #2a82da;
}
QTabBar::tab:hover:!selected {
    background: #353535;
}
QSplitter::handle {
    background: #1e1e1e;
}
QSplitter::handle:hover {
    background: #2a82da;
}

/* ---------- Árbol de máquinas (panel izquierdo estilo VirtualBox) ---------- */
QTreeWidget#vmTree {
    background: #262626;
    border: 1px solid #444444;
    border-radius: 6px;
    outline: 0;
    padding: 4px;
}
QTreeWidget#vmTree::item {
    color: #dddddd;
    padding: 6px 4px;
    border-radius: 4px;
    margin: 1px 2px;
}
QTreeWidget#vmTree::item:hover {
    background: #333333;
}
QTreeWidget#vmTree::item:selected {
    background: #2a82da;
    color: #ffffff;
}
QTreeWidget#vmTree::branch {
    background: transparent;
}

QFrame#panel {
    background: #2d2d2d;
    border: 1px solid #555555;
    border-radius: 8px;
}
QFrame#softPanel {
    background: #2d2d2d;
    border: 1px solid #4a4a4a;
    border-radius: 10px;
}
QFrame#emptyPanel {
    background: #262626;
    border: 1px dashed #555555;
    border-radius: 10px;
}
QFrame#quickCard {
    background: #2d2d2d;
    border: 1px solid #555555;
    border-radius: 10px;
}
QFrame#quickCard:hover {
    border-color: #2a82da;
}
QLabel#errorLabel {
    color: #ff9b8f;
}
QLabel#okLabel {
    color: #7fd98a;
}
QStatusBar {
    background: #2d2d2d;
    color: #aaaaaa;
    border-top: 1px solid #444444;
}
QStatusBar QLabel {
    color: #bbbbbb;
}

/* ---------- Detalle de VM estilo VirtualBox (etiqueta/valor) ---------- */
QLabel#detailGroup {
    font-size: 11pt;
    font-weight: 700;
    color: #f0f0f0;
    padding-top: 6px;
}
QLabel#detailKey {
    color: #9b9b9b;
}
QLabel#detailValue {
    color: #e8e8e8;
    font-weight: 600;
}

QFrame#sidebar {
    background: #262626;
    border-right: 1px solid #444444;
}
QListWidget#sidebarNav {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 6px;
    outline: 0;
}
QListWidget#sidebarNav::item {
    color: #bbbbbb;
    border-radius: 6px;
    padding: 9px 12px;
    margin: 2px 4px;
}
QListWidget#sidebarNav::item:hover {
    background: #333333;
    color: #eeeeee;
}
QListWidget#sidebarNav::item:selected {
    background: #2a82da;
    color: #ffffff;
    font-weight: 700;
}
QLabel#statusChip {
    background: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 9px;
    color: #bbbbbb;
    padding: 4px 10px;
    font-size: 9pt;
}
QLabel#statusChipOk {
    background: #1f3a24;
    border: 1px solid #2f6b3a;
    border-radius: 9px;
    color: #8fe39a;
    padding: 4px 10px;
    font-size: 9pt;
}
QLabel#statusChipBad {
    background: #4a2420;
    border: 1px solid #c42b1c;
    border-radius: 9px;
    color: #ff9b8f;
    padding: 4px 10px;
    font-size: 9pt;
}
QLabel#statusChipWarn {
    background: #3a300f;
    border: 1px solid #8a6a16;
    border-radius: 9px;
    color: #f5c451;
    padding: 4px 10px;
    font-size: 9pt;
}
QLabel#placeholderTitle {
    font-size: 15pt;
    font-weight: 700;
    color: #e6e6e6;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QLabel#pageTitle {
    font-size: 15pt;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: #f0f0f0;
}
QLabel#statBig {
    font-size: 20pt;
    font-weight: 700;
    color: #e8e8e8;
}
QLabel#statBigOk {
    font-size: 20pt;
    font-weight: 700;
    color: #7fd98a;
}
QLabel#statBigBad {
    font-size: 20pt;
    font-weight: 700;
    color: #ff9b8f;
}
QLabel#statLabel {
    font-size: 9pt;
    font-weight: 600;
    color: #aaaaaa;
}
QLabel#calloutWarn {
    background: rgba(240, 163, 10, 0.10);
    border: 1px solid rgba(240, 163, 10, 0.35);
    border-radius: 6px;
    color: #f3d9a8;
    padding: 10px 12px;
}
QLabel#calloutOk {
    background: rgba(60, 180, 73, 0.10);
    border: 1px solid rgba(60, 180, 73, 0.35);
    border-radius: 6px;
    color: #b9f0cb;
    padding: 10px 12px;
}
QLabel#calloutInfo {
    background: rgba(42, 130, 218, 0.10);
    border: 1px solid rgba(42, 130, 218, 0.35);
    border-radius: 6px;
    color: #bfdcf5;
    padding: 10px 12px;
}
QLabel#calloutDanger {
    background: rgba(196, 43, 28, 0.12);
    border: 1px solid rgba(196, 43, 28, 0.45);
    border-radius: 6px;
    color: #f5b9b9;
    padding: 10px 12px;
}
QFrame#hubCard {
    background: #2d2d2d;
    border: 1px solid rgba(42, 130, 218, 0.40);
    border-radius: 10px;
}
QFrame#hubCardOffline {
    background: #2d2d2d;
    border: 1px solid rgba(196, 43, 28, 0.45);
    border-radius: 10px;
}
QFrame#hostCard {
    background: #2d2d2d;
    border: 1px solid #555555;
    border-radius: 9px;
}
QFrame#hostCardSelected {
    background: #2d2d2d;
    border: 1px solid #2a82da;
    border-radius: 9px;
}
QFrame#hostCardOffline {
    background: #262626;
    border: 1px solid rgba(196, 43, 28, 0.40);
    border-radius: 9px;
}
QLabel#metricLabel {
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: #888888;
}
QLabel#metricValue {
    font-size: 11pt;
    font-weight: 600;
    color: #e8e8e8;
}
QLabel#srcChipEnv {
    border: 1px solid rgba(61, 142, 224, 0.45);
    border-radius: 4px;
    color: #7db8ec;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
QLabel#srcChipConfig {
    border: 1px solid rgba(167, 139, 250, 0.40);
    border-radius: 4px;
    color: #c4b5fd;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
QLabel#srcChipDefault {
    border: 1px solid #555555;
    border-radius: 4px;
    color: #888888;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
QScrollBar:vertical {
    background: #262626;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4a4a4a;
    border-radius: 6px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #5a5a5a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #262626;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #4a4a4a;
    border-radius: 6px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
"""

__all__ = [
    "APP_DISPLAY_VERSION",
    "APP_STYLESHEET",
    "DESIGN_TOKENS",
    "STATE_BACKGROUNDS",
    "STATE_COLORS",
    "STATE_LABELS",
    "details_block",
    "format_mib",
    "state_kind",
]
