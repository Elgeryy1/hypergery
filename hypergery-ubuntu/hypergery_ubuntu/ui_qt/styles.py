from __future__ import annotations


APP_DISPLAY_VERSION = "1.0-rc1"

# v0.7 design tokens (docs/design/v0.7/hypergery-design/app/styles.css)
DESIGN_TOKENS = {
    "bg": "#080D14",
    "bg_alt": "#0B1020",
    "surface": "#111C2E",
    "surface_2": "#0E1726",
    "elevated": "#162033",
    "border": "#263244",
    "border_soft": "#1B2536",
    "accent": "#22D3EE",
    "accent_3": "#60A5FA",
    "running": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "offline": "#64748B",
    "text": "#E5E7EB",
    "text_dim": "#94A3B8",
    "text_faint": "#5C6B82",
}

STATE_COLORS = {
    "running": "#22C55E",
    "shutoff": "#94A3B8",
    "paused": "#F59E0B",
    "unknown": "#94A3B8",
}

STATE_BACKGROUNDS = {
    "running": "#0E2C1F",
    "shutoff": "#1B2536",
    "paused": "#33260D",
    "unknown": "#1B2536",
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


def format_mib(value: int | None) -> str:
    return f"{value} MiB" if value else "unknown"


def details_block(*rows: tuple[str, str]) -> str:
    width = max((len(label) for label, _value in rows), default=0)
    return "\n".join(f"{label:<{width}}  {value}" for label, value in rows)


APP_STYLESHEET = """
QMainWindow, QDialog, QWizard {
    background: #080D14;
    color: #E5E7EB;
    font-family: "Inter", "Segoe UI", "Ubuntu", "Sans";
    font-size: 10.5pt;
}
QWidget {
    color: #E5E7EB;
}
QFrame#topBar {
    background: #0B1020;
    border-bottom: 1px solid #263244;
}
QLabel#brandTitle {
    font-size: 18pt;
    font-weight: 700;
    color: #eaf6ff;
}
QLabel#brandSubtle, QLabel#mutedLabel {
    color: #94A3B8;
}
QLabel#sectionTitle {
    font-size: 12pt;
    font-weight: 700;
    color: #f3f8ff;
}
QLabel#heroTitle {
    font-size: 18pt;
    font-weight: 750;
    color: #f8fbff;
}
QLabel#heroSubtitle {
    font-size: 11pt;
    color: #94A3B8;
}
QLabel#preflightSummary {
    font-size: 12pt;
    font-weight: 700;
    color: #dbeafe;
}
QPushButton {
    background: #162033;
    border: 1px solid #263244;
    border-radius: 7px;
    color: #eef4fb;
    padding: 7px 11px;
}
QPushButton:hover {
    background: #263244;
    border-color: #0891b2;
}
QPushButton:disabled {
    background: #19202a;
    border-color: #252e3a;
    color: #687386;
}
QPushButton#primaryButton {
    background: #0e7490;
    border-color: #22d3ee;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #0891b2;
}
QPushButton#dangerButton {
    background: #3a2025;
    border-color: #7f1d1d;
    color: #ffc9c9;
    font-weight: 700;
}
QPushButton#ghostButton {
    background: #151d27;
    border-color: #263244;
    color: #cbd5e1;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QListWidget, QTableWidget {
    background: #0E1726;
    border: 1px solid #263244;
    border-radius: 8px;
    color: #eef4fb;
    selection-background-color: #2563eb;
    padding: 5px;
}
QTableWidget {
    gridline-color: #1B2536;
    alternate-background-color: #0E1726;
}
QHeaderView::section {
    background: #111C2E;
    color: #cbd5e1;
    border: 0;
    border-bottom: 1px solid #2d3848;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #263244;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    background: #0B1020;
    border: 1px solid #263244;
    color: #aab4c3;
    padding: 8px 13px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #162033;
    color: #ffffff;
}
QSplitter::handle {
    background: #1B2536;
}
QFrame#panel {
    background: #111C2E;
    border: 1px solid #263244;
    border-radius: 10px;
}
QFrame#softPanel {
    background: #111C2E;
    border: 1px solid #263244;
    border-radius: 12px;
}
QFrame#emptyPanel {
    background: #0E1726;
    border: 1px dashed #263244;
    border-radius: 12px;
}
QFrame#quickCard {
    background: #111C2E;
    border: 1px solid #263244;
    border-radius: 12px;
}
QFrame#quickCard:hover {
    border-color: #0891b2;
}
QLabel#errorLabel {
    color: #fca5a5;
}
QLabel#okLabel {
    color: #86efac;
}
QStatusBar {
    background: #080D14;
    color: #aab4c3;
}
QFrame#sidebar {
    background: #0B1020;
    border-right: 1px solid #263244;
}
QListWidget#sidebarNav {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 6px;
    outline: 0;
}
QListWidget#sidebarNav::item {
    color: #aab4c3;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 2px 4px;
}
QListWidget#sidebarNav::item:hover {
    background: #162033;
    color: #E5E7EB;
}
QListWidget#sidebarNav::item:selected {
    background: #14323d;
    color: #7dd3fc;
    font-weight: 700;
}
QLabel#statusChip {
    background: #162033;
    border: 1px solid #263244;
    border-radius: 10px;
    color: #aab4c3;
    padding: 4px 10px;
    font-size: 9.5pt;
}
QLabel#statusChipOk {
    background: #11332b;
    border: 1px solid #1f6f53;
    border-radius: 10px;
    color: #86efac;
    padding: 4px 10px;
    font-size: 9.5pt;
}
QLabel#statusChipBad {
    background: #3a2025;
    border: 1px solid #7f1d1d;
    border-radius: 10px;
    color: #fca5a5;
    padding: 4px 10px;
    font-size: 9.5pt;
}
QLabel#placeholderTitle {
    font-size: 16pt;
    font-weight: 700;
    color: #dbeafe;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QLabel#pageTitle {
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: -0.4px;
    color: #f3f8ff;
}
QLabel#statBig {
    font-size: 21pt;
    font-weight: 700;
    color: #E5E7EB;
}
QLabel#statBigOk {
    font-size: 21pt;
    font-weight: 700;
    color: #86efac;
}
QLabel#statBigBad {
    font-size: 21pt;
    font-weight: 700;
    color: #fca5a5;
}
QLabel#statLabel {
    font-size: 9.5pt;
    font-weight: 600;
    color: #94A3B8;
}
QLabel#calloutWarn {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 7px;
    color: #f3d9a8;
    padding: 10px 12px;
}
QLabel#calloutOk {
    background: rgba(34, 197, 94, 0.08);
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 7px;
    color: #b9f0cb;
    padding: 10px 12px;
}
QLabel#calloutInfo {
    background: rgba(96, 165, 250, 0.08);
    border: 1px solid rgba(96, 165, 250, 0.3);
    border-radius: 7px;
    color: #bfdbfe;
    padding: 10px 12px;
}
QLabel#calloutDanger {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 7px;
    color: #f5b9b9;
    padding: 10px 12px;
}
QFrame#hubCard {
    background: #111C2E;
    border: 1px solid rgba(34, 211, 238, 0.28);
    border-radius: 12px;
}
QFrame#hubCardOffline {
    background: #111C2E;
    border: 1px solid rgba(239, 68, 68, 0.4);
    border-radius: 12px;
}
QFrame#hostCard {
    background: #111C2E;
    border: 1px solid #263244;
    border-radius: 10px;
}
QFrame#hostCardSelected {
    background: #111C2E;
    border: 1px solid #22D3EE;
    border-radius: 10px;
}
QFrame#hostCardOffline {
    background: #0E1726;
    border: 1px solid rgba(239, 68, 68, 0.35);
    border-radius: 10px;
}
QLabel#metricLabel {
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: #5C6B82;
}
QLabel#metricValue {
    font-size: 11.5pt;
    font-weight: 600;
    color: #E5E7EB;
}
QLabel#statusChipWarn {
    background: rgba(245, 158, 11, 0.13);
    border: 1px solid rgba(245, 158, 11, 0.4);
    border-radius: 10px;
    color: #fcd34d;
    padding: 4px 10px;
    font-size: 9.5pt;
}
QLabel#srcChipEnv {
    border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 4px;
    color: #7dd3fc;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
QLabel#srcChipConfig {
    border: 1px solid rgba(167, 139, 250, 0.35);
    border-radius: 4px;
    color: #c4b5fd;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
QLabel#srcChipDefault {
    border: 1px solid #263244;
    border-radius: 4px;
    color: #5C6B82;
    padding: 1px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}
"""
