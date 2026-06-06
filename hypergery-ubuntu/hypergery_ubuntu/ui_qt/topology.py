from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


_STATE_COLORS: dict[str, str] = {
    "running": "#4CAF50",
    "shut off": "#9E9E9E",
    "shutoff": "#9E9E9E",
    "paused": "#FFC107",
    "not created": "#607D8B",
}
_STATE_LABEL: dict[str, str] = {
    "running": "encendida",
    "shut off": "apagada",
    "shutoff": "apagada",
    "paused": "en pausa",
    "not created": "sin crear",
}
_NETWORK_COLOR = "#1565C0"
_NODE_BG = "#1E293B"
_NODE_TEXT = "#E2E8F0"
_BORDER_RADIUS = 10

_NODE_W = 170
_NODE_H = 62
_NET_W = 120
_NET_H = 62
_H_MARGIN = 60
_V_GAP = 14


def _state_color(state: str) -> QColor:
    return QColor(_STATE_COLORS.get(state, "#FF5722"))


def _state_label(state: str) -> str:
    return _STATE_LABEL.get(state, state)


class LabTopologyWidget(QWidget):
    """Read-only visual topology of a lab: network node + VM nodes."""

    vm_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._topology: dict[str, Any] | None = None
        self._hit_boxes: list[tuple[QRect, str]] = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_topology(self, topology: dict[str, Any] | None) -> None:
        self._topology = topology
        self._hit_boxes = []
        self.update()

    def sizeHint(self) -> QSize:
        if not self._topology or not self._topology.get("vms"):
            return QSize(400, 140)
        n = len(self._topology["vms"])
        h = max(n * (_NODE_H + _V_GAP) + 30, 140)
        return QSize(460, h)

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#0F172A"))

        if not self._topology:
            self._draw_empty(painter, w, h, "Ningún laboratorio seleccionado.")
            return
        vms = self._topology.get("vms", [])
        if not vms:
            self._draw_empty(painter, w, h, "Este laboratorio aún no tiene máquinas.")
            return

        self._hit_boxes = []
        net_x = _H_MARGIN
        total_h = len(vms) * (_NODE_H + _V_GAP) - _V_GAP
        net_y = (h - _NET_H) // 2
        vm_x = net_x + _NET_W + _H_MARGIN + 20
        vm_start_y = (h - total_h) // 2

        self._draw_network_node(painter, net_x, net_y)

        for i, vm in enumerate(vms):
            vm_y = vm_start_y + i * (_NODE_H + _V_GAP)
            conn_start = QPoint(net_x + _NET_W, net_y + _NET_H // 2)
            conn_end = QPoint(vm_x, vm_y + _NODE_H // 2)
            self._draw_connection(painter, conn_start, conn_end)
            self._draw_vm_node(painter, vm_x, vm_y, vm)
            self._hit_boxes.append((QRect(vm_x, vm_y, _NODE_W, _NODE_H), vm["name"]))

        painter.end()

    def _draw_empty(self, painter: QPainter, w: int, h: int, text: str) -> None:
        painter.setPen(QColor("#475569"))
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_network_node(self, painter: QPainter, x: int, y: int) -> None:
        path = QPainterPath()
        path.addRoundedRect(x, y, _NET_W, _NET_H, _BORDER_RADIUS, _BORDER_RADIUS)
        painter.fillPath(path, QColor("#1E3A5F"))
        pen = QPen(QColor(_NETWORK_COLOR), 2)
        painter.setPen(pen)
        painter.drawPath(path)

        top = self._topology or {}
        subnet = str(top.get("subnet", "")).replace("/24", "")
        mode = str(top.get("network_mode", "")).upper()
        net_name = str(top.get("network_id", "Network"))

        font = QFont()
        font.setBold(True)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#90CAF9"))
        painter.drawText(QRect(x, y + 8, _NET_W, 18), Qt.AlignmentFlag.AlignHCenter, net_name[:18])

        font.setBold(False)
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor("#64B5F6"))
        painter.drawText(QRect(x, y + 26, _NET_W, 14), Qt.AlignmentFlag.AlignHCenter, mode)
        if subnet:
            painter.drawText(QRect(x, y + 40, _NET_W, 14), Qt.AlignmentFlag.AlignHCenter, subnet)

    def _draw_vm_node(self, painter: QPainter, x: int, y: int, vm: dict) -> None:
        state = str(vm.get("state", "unknown")).lower()
        border_color = _state_color(state)

        path = QPainterPath()
        path.addRoundedRect(x, y, _NODE_W, _NODE_H, _BORDER_RADIUS, _BORDER_RADIUS)
        painter.fillPath(path, QColor(_NODE_BG))
        pen = QPen(border_color, 2)
        painter.setPen(pen)
        painter.drawPath(path)

        # State dot
        dot_x, dot_y = x + 10, y + _NODE_H // 2 - 5
        painter.setBrush(border_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(dot_x, dot_y, 10, 10)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        name = str(vm.get("name", ""))
        if len(name) > 20:
            name = name[:18] + "…"
        font = QFont()
        font.setBold(True)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(_NODE_TEXT))
        painter.drawText(QRect(x + 26, y + 6, _NODE_W - 30, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        font.setBold(False)
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor("#94A3B8"))
        state_label = _state_label(state)
        painter.drawText(QRect(x + 26, y + 24, _NODE_W - 30, 14), Qt.AlignmentFlag.AlignLeft, state_label)

        ram = vm.get("ram_mib", 0)
        vcpus = vm.get("vcpus", 0)
        res_parts = []
        if ram:
            res_parts.append(f"{ram // 1024 if ram >= 1024 else ram}{'G' if ram >= 1024 else 'M'}")
        if vcpus:
            res_parts.append(f"{vcpus}c")
        if not vm.get("live"):
            res_parts.append("not created")
        res_text = "  ".join(res_parts)
        painter.drawText(QRect(x + 26, y + 38, _NODE_W - 30, 14), Qt.AlignmentFlag.AlignLeft, res_text)

    def _draw_connection(self, painter: QPainter, p1: QPoint, p2: QPoint) -> None:
        pen = QPen(QColor("#334155"), 1, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        mid_x = (p1.x() + p2.x()) // 2
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(QPoint(mid_x, p1.y()), QPoint(mid_x, p2.y()), p2)
        painter.drawPath(path)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        pos = event.pos()
        for rect, name in self._hit_boxes:
            if rect.contains(pos):
                self.vm_selected.emit(name)
                return
        super().mousePressEvent(event)
