from __future__ import annotations


APP_DISPLAY_VERSION = "0.2.0-dev"

STATE_COLORS = {
    "running": "#36d399",
    "shutoff": "#9aa4b2",
    "paused": "#f6c177",
    "unknown": "#c7d0dd",
}

STATE_BACKGROUNDS = {
    "running": "#123d36",
    "shutoff": "#273241",
    "paused": "#3c3017",
    "unknown": "#202938",
}

STATE_LABELS = {
    "running": "RUNNING",
    "shutoff": "SHUTOFF",
    "paused": "PAUSED",
    "unknown": "UNKNOWN",
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
    background: #0f141b;
    color: #e8edf3;
    font-family: "Inter", "Segoe UI", "Ubuntu", "Sans";
    font-size: 10.5pt;
}
QWidget {
    color: #e8edf3;
}
QFrame#topBar {
    background: #121a24;
    border-bottom: 1px solid #243244;
}
QLabel#brandTitle {
    font-size: 18pt;
    font-weight: 700;
    color: #eaf6ff;
}
QLabel#brandSubtle, QLabel#mutedLabel {
    color: #9aa4b2;
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
    color: #9aa4b2;
}
QLabel#preflightSummary {
    font-size: 12pt;
    font-weight: 700;
    color: #dbeafe;
}
QPushButton {
    background: #202a38;
    border: 1px solid #334155;
    border-radius: 7px;
    color: #eef4fb;
    padding: 7px 11px;
}
QPushButton:hover {
    background: #263449;
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
    border-color: #2b3a4f;
    color: #cbd5e1;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QListWidget, QTableWidget {
    background: #121922;
    border: 1px solid #263449;
    border-radius: 8px;
    color: #eef4fb;
    selection-background-color: #2563eb;
    padding: 5px;
}
QTableWidget {
    gridline-color: #202b3a;
    alternate-background-color: #101720;
}
QHeaderView::section {
    background: #162030;
    color: #cbd5e1;
    border: 0;
    border-bottom: 1px solid #2d3848;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #263449;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    background: #121a24;
    border: 1px solid #263449;
    color: #aab4c3;
    padding: 8px 13px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #1c2938;
    color: #ffffff;
}
QSplitter::handle {
    background: #202938;
}
QFrame#panel {
    background: #121a24;
    border: 1px solid #243244;
    border-radius: 10px;
}
QFrame#softPanel {
    background: #151d28;
    border: 1px solid #2b3a4f;
    border-radius: 12px;
}
QFrame#emptyPanel {
    background: #101720;
    border: 1px dashed #334155;
    border-radius: 12px;
}
QFrame#quickCard {
    background: #151d28;
    border: 1px solid #2b3a4f;
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
    background: #0f141b;
    color: #aab4c3;
}
"""
