from __future__ import annotations

"""Árbol de máquinas virtuales agrupadas por laboratorio (estilo VirtualBox).

Sustituye a la tabla plana de VMs. Las raíces son los laboratorios (más un
grupo "Sin laboratorio"); las hojas son las máquinas, cada una con su bola de
estado y un badge del SO. Soporta multiselección para acciones en lote y un
filtro de texto.
"""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from .icons import lab_icon, os_icon, state_ball_icon
from .styles import STATE_LABELS, state_kind

if TYPE_CHECKING:  # evita import pesado/circular en runtime
    from ..backend import VmSummary

_VM_ROLE = Qt.ItemDataRole.UserRole
_LAB_ROLE = Qt.ItemDataRole.UserRole + 1
_NO_LAB_KEY = "__no_lab__"


class VmTree(QTreeWidget):
    """Árbol de VMs por laboratorio con multiselección y filtro."""

    currentVmChanged = Signal(object)  # VmSummary | None
    vmActivated = Signal(object)       # VmSummary (doble clic / Enter)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("vmTree")
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        self.setExpandsOnDoubleClick(False)
        self.setAnimated(True)
        self._vms: list[VmSummary] = []
        self._labs: list[dict[str, Any]] = []
        self._filter = ""
        self.currentItemChanged.connect(self._on_current_changed)
        self.itemActivated.connect(self._on_item_activated)

    # ---- API pública -----------------------------------------------------
    def populate(self, vms: list[VmSummary], labs: list[dict[str, Any]]) -> None:
        """Reconstruye el árbol conservando selección y grupos colapsados."""
        self._vms = list(vms)
        self._labs = list(labs)
        self._rebuild()

    def set_filter(self, text: str) -> None:
        self._filter = (text or "").strip().lower()
        self._rebuild()

    def current_vm(self) -> VmSummary | None:
        item = self.currentItem()
        return self._vm_of(item)

    def selected_vms(self) -> list[VmSummary]:
        result: list[VmSummary] = []
        for item in self.selectedItems():
            vm = self._vm_of(item)
            if vm is not None:
                result.append(vm)
        return result

    def select_vm_by_name(self, name: str | None) -> bool:
        if not name:
            return False
        match = self._find_vm_item(name)
        if match is None:
            return False
        self.blockSignals(True)
        self.setCurrentItem(match)
        self.blockSignals(False)
        self._on_current_changed(match, None)
        return True

    # ---- Internos --------------------------------------------------------
    def _vm_of(self, item: QTreeWidgetItem | None) -> VmSummary | None:
        if item is None:
            return None
        return item.data(0, _VM_ROLE)

    def _find_vm_item(self, name: str) -> QTreeWidgetItem | None:
        for top in range(self.topLevelItemCount()):
            group = self.topLevelItem(top)
            for idx in range(group.childCount()):
                child = group.child(idx)
                vm = self._vm_of(child)
                if vm is not None and vm.name == name:
                    return child
        return None

    def _lab_name(self, lab_id: str) -> str:
        for lab in self._labs:
            manifest_id = lab.get("lab_id", lab.get("id"))
            if str(manifest_id) == lab_id:
                return str(lab.get("name") or lab_id)
        return lab_id

    def _matches_filter(self, vm: VmSummary) -> bool:
        if not self._filter:
            return True
        haystack = f"{vm.name} {vm.lab_id or ''} {vm.state}".lower()
        return self._filter in haystack

    def _rebuild(self) -> None:
        previous = self.current_vm()
        previous_name = previous.name if previous else None
        collapsed = self._collapsed_groups()

        self.blockSignals(True)
        self.clear()

        # Agrupa VMs por lab_id preservando el orden de aparición.
        groups: dict[str, list[VmSummary]] = {}
        order: list[str] = []
        for vm in self._vms:
            if not self._matches_filter(vm):
                continue
            key = vm.lab_id or _NO_LAB_KEY
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(vm)

        for key in order:
            label = "Sin laboratorio" if key == _NO_LAB_KEY else self._lab_name(key)
            header = QTreeWidgetItem(self, [f"{label}  ({len(groups[key])})"])
            header.setIcon(0, lab_icon())
            header.setData(0, _LAB_ROLE, key)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = header.font(0)
            font.setBold(True)
            header.setFont(0, font)
            for vm in groups[key]:
                child = QTreeWidgetItem(header, [vm.name])
                child.setData(0, _VM_ROLE, vm)
                child.setIcon(0, os_icon(vm.name, getattr(vm, "os_type", None)))
                state_label = STATE_LABELS.get(state_kind(vm.state), vm.state)
                child.setToolTip(0, f"{vm.name} — {state_label}")
                # Bola de estado como decoración: usa un segundo "icono" textual.
                child.setData(0, _VM_ROLE + 1, state_ball_icon(vm.state))
            header.setExpanded(key not in collapsed)

        self.blockSignals(False)

        # Restaura selección previa o selecciona la primera VM disponible.
        if not self.select_vm_by_name(previous_name):
            first = self._first_vm_item()
            if first is not None:
                self.setCurrentItem(first)
            else:
                self.currentVmChanged.emit(None)

    def _first_vm_item(self) -> QTreeWidgetItem | None:
        for top in range(self.topLevelItemCount()):
            group = self.topLevelItem(top)
            if group.childCount():
                return group.child(0)
        return None

    def _collapsed_groups(self) -> set[str]:
        collapsed: set[str] = set()
        for top in range(self.topLevelItemCount()):
            group = self.topLevelItem(top)
            key = group.data(0, _LAB_ROLE)
            if key is not None and not group.isExpanded():
                collapsed.add(key)
        return collapsed

    def _on_current_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        self.currentVmChanged.emit(self._vm_of(current))

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        vm = self._vm_of(item)
        if vm is not None:
            self.vmActivated.emit(vm)
        else:
            item.setExpanded(not item.isExpanded())
