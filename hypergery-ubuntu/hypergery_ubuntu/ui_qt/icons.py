from __future__ import annotations

"""Iconos dibujados por código (sin ficheros): bolas de estado y badges de SO.

Mantenerlo sin assets evita problemas de empaquetado y de rutas. Todas las
funciones se llaman en tiempo de ejecución (con QApplication ya creada).
"""

from functools import lru_cache

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap

from .formatting import os_icon_key
from .styles import STATE_COLORS, state_kind

# Colores de marca aproximados por familia de SO.
_OS_STYLE = {
    "ubuntu": ("#E95420", "U"),
    "debian": ("#A80030", "D"),
    "fedora": ("#3C6EB4", "F"),
    "centos": ("#932279", "C"),
    "arch": ("#1793D1", "A"),
    "windows": ("#0078D6", "W"),
    "linux": ("#555555", "L"),
    "generic": ("#666666", "·"),
}


@lru_cache(maxsize=64)
def state_ball_icon(state: str, size: int = 14) -> QIcon:
    """Círculo de color según el estado (running/paused/shutoff/unknown)."""
    kind = state_kind(state)
    color = STATE_COLORS.get(kind, STATE_COLORS["unknown"])
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
    margin = 2
    painter.drawEllipse(margin, margin, size - 2 * margin - 1, size - 2 * margin - 1)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=64)
def os_icon(name: str | None, os_hint: str | None = None, size: int = 18) -> QIcon:
    """Badge cuadrado redondeado con el color de marca y la inicial del SO."""
    key = os_icon_key(name, os_hint)
    color, letter = _OS_STYLE.get(key, _OS_STYLE["generic"])
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size - 1, size - 1, 4, 4)
    painter.setPen(QPen(QColor("#ffffff")))
    font = QFont()
    font.setBold(True)
    font.setPointSizeF(max(7.0, size * 0.5))
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=16)
def lab_icon(size: int = 18) -> QIcon:
    """Icono de carpeta/grupo para las cabeceras de laboratorio del árbol."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#c9a227")))
    painter.setPen(Qt.PenStyle.NoPen)
    # Pestaña + cuerpo de la carpeta.
    painter.drawRoundedRect(1, 5, size - 3, size - 8, 2, 2)
    painter.drawRoundedRect(1, 3, (size - 3) // 2, 4, 1, 1)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=8)
def app_icon(size: int = 64) -> QIcon:
    """Icono de la aplicación: cuadrado azul HyperGery con las iniciales HG."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#2a82da")))
    painter.setPen(Qt.PenStyle.NoPen)
    radius = max(4, size // 5)
    painter.drawRoundedRect(0, 0, size - 1, size - 1, radius, radius)
    painter.setPen(QPen(QColor("#ffffff")))
    font = QFont()
    font.setBold(True)
    font.setPointSizeF(max(8.0, size * 0.42))
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "HG")
    painter.end()
    return QIcon(pixmap)
