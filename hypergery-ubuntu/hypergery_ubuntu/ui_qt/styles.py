from __future__ import annotations


APP_DISPLAY_VERSION = "0.2.0-dev"

STATE_COLORS = {
    "running": "#36d399",
    "shutoff": "#9aa4b2",
    "paused": "#f6c177",
    "unknown": "#c7d0dd",
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
    background: #11161d;
    color: #e8edf3;
    font-family: "Inter", "Segoe UI", "Ubuntu", "Sans";
    font-size: 10.5pt;
}
QWidget {
    color: #e8edf3;
}
QFrame#topBar {
    background: #171d26;
    border-bottom: 1px solid #2a3441;
}
QLabel#brandTitle {
    font-size: 18pt;
    font-weight: 700;
}
QLabel#brandSubtle, QLabel#mutedLabel {
    color: #9aa4b2;
}
QLabel#sectionTitle {
    font-size: 12pt;
    font-weight: 700;
}
QPushButton {
    background: #242d3a;
    border: 1px solid #344052;
    border-radius: 6px;
    color: #eef4fb;
    padding: 8px 12px;
}
QPushButton:hover {
    background: #2d3848;
    border-color: #4d5f76;
}
QPushButton:disabled {
    background: #19202a;
    border-color: #252e3a;
    color: #687386;
}
QPushButton#primaryButton {
    background: #2563eb;
    border-color: #3774ff;
    font-weight: 700;
}
QPushButton#dangerButton {
    background: #3a2025;
    border-color: #7f1d1d;
    color: #ffc9c9;
    font-weight: 700;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QListWidget, QTableWidget {
    background: #151b24;
    border: 1px solid #2d3848;
    border-radius: 6px;
    color: #eef4fb;
    selection-background-color: #2563eb;
    padding: 5px;
}
QTableWidget {
    gridline-color: #25303d;
    alternate-background-color: #131922;
}
QHeaderView::section {
    background: #1b2330;
    color: #cbd5e1;
    border: 0;
    border-bottom: 1px solid #2d3848;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #2d3848;
    border-radius: 7px;
    top: -1px;
}
QTabBar::tab {
    background: #171d26;
    border: 1px solid #2d3848;
    color: #aab4c3;
    padding: 8px 13px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #222b38;
    color: #ffffff;
}
QSplitter::handle {
    background: #202938;
}
QFrame#panel {
    background: #141a23;
    border: 1px solid #273241;
    border-radius: 8px;
}
QLabel#errorLabel {
    color: #fca5a5;
}
QLabel#okLabel {
    color: #86efac;
}
QStatusBar {
    background: #11161d;
    color: #aab4c3;
}
"""
