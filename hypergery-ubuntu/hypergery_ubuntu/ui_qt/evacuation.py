"""Evacuación por batería (idea de Gerard, 2026-06-11).

Cuando el portátil entra en nivel «offload» (por defecto 30%, configurable en
V1Settings.battery_offload_percent) descargando, la app PREGUNTA si quiere
pasar todas las VMs encendidas a otro equipo por migración EN VIVO; después
ofrece abrir sus consolas remotas — el portátil descansa y el PC con enchufe
hace el trabajo.

Diseño:
- EvacuationMonitor: histéresis pura (testable sin Qt). Ofrece UNA vez por
  ciclo de descarga; se rearma al enchufar el cargador o recuperar nivel.
- vm_evacuation_blockers: una VM con GPU física o VirGL no puede migrar en
  vivo (mismas reglas que el preflight del motor) — se lista con su motivo.
- evacuate_running_vms: migra una a una con LiveMigrator (rollback por VM:
  si una falla, su origen queda corriendo y se continúa con la siguiente).
  Los CD conectados se expulsan antes (la ISO no existe en el destino).
- EvacuationDialog: la pregunta, con destino del registro del Hub y la lista
  de VMs con su veredicto.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

OFFER_TIERS = {"offload", "emergency", "critical"}
REARM_TIERS = {"normal", "eco"}


class EvacuationMonitor:
    """Decide cuándo ofrecer la evacuación. Con histéresis: una oferta por
    ciclo de descarga — tras ofrecer, no insiste hasta que la batería se
    recupere (cargador conectado o nivel normal/eco) y vuelva a caer."""

    def __init__(self) -> None:
        self.armed = True

    def should_offer(self, state: dict[str, Any]) -> bool:
        if not state.get("available") or state.get("charging"):
            self.armed = True
            return False
        tier = state.get("tier", "normal")
        if tier in REARM_TIERS:
            self.armed = True
            return False
        if tier in OFFER_TIERS and self.armed:
            self.armed = False
            return True
        return False


def vm_evacuation_blockers(xml: str) -> list[str]:
    """Motivos por los que una VM NO puede migrar en vivo (espejo del
    preflight del motor, para poder listárselos al usuario ANTES)."""
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError:
        return []
    blockers: list[str] = []
    if root.findall("./devices/hostdev"):
        blockers.append("GPU/dispositivo físico conectado")
    has_virgl = root.findall("./devices/video/model/acceleration[@accel3d='yes']") or [
        g for g in root.findall("./devices/graphics") if g.attrib.get("type") == "egl-headless"
    ]
    if has_virgl:
        blockers.append("aceleración 3D (VirGL)")
    return blockers


def _eject_cdroms(backend: Any, vm_name: str, xml: str) -> list[str]:
    """Expulsa los CD con ISO conectada (no existirán en el destino)."""
    ejected: list[str] = []
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError:
        return ejected
    for disk in root.findall("./devices/disk[@device='cdrom']"):
        source = disk.find("source")
        target = disk.find("target")
        if source is None or not source.attrib.get("file") or target is None:
            continue
        dev = target.attrib.get("dev", "")
        result = backend.virsh(
            ["change-media", vm_name, dev, "--eject", "--live", "--config"], check=False
        )
        if result.returncode == 0:
            ejected.append(source.attrib["file"])
    return ejected


def evacuate_running_vms(
    backend: Any,
    vm_names: list[str],
    target_uri: str,
    *,
    migrator_factory: Callable[[Any], Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Migra EN VIVO las VMs, una a una, al destino. Si una falla, su origen
    queda corriendo (rollback del motor) y se sigue con la siguiente."""
    from ..v1.live_migration import LiveMigrationPlan, LiveMigrator

    factory = migrator_factory or (lambda plan: LiveMigrator(backend, plan))
    note = progress or (lambda _msg: None)
    results: list[dict[str, Any]] = []
    for name in vm_names:
        note(f"Migrando en vivo {name} → {target_uri}…")
        try:
            xml = backend.get_vm(name).xml
            ejected = _eject_cdroms(backend, name, xml)
            if ejected:
                note(f"{name}: CD expulsado ({', '.join(ejected)})")
            plan = LiveMigrationPlan(vm_name=name, target_uri=target_uri, shared_storage=None)
            result = factory(plan).run()
        except Exception as exc:  # una VM no debe abortar la evacuación de las demás
            result = {"ok": False, "error": str(exc), "status": "failed"}
        entry = {
            "vm_name": name,
            "ok": bool(result.get("ok")),
            "error": result.get("error", ""),
            "status": result.get("status", ""),
            "downtime_ms": result.get("measured_downtime_ms"),
        }
        note(
            f"{name}: {'migrada (downtime ' + str(entry['downtime_ms']) + ' ms)' if entry['ok'] else 'FALLÓ — ' + str(entry['error'])[:160]}"
        )
        results.append(entry)
    migrated = [r["vm_name"] for r in results if r["ok"]]
    return {
        "ok": bool(results) and all(r["ok"] for r in results),
        "migrated": migrated,
        "results": results,
        "target_uri": target_uri,
    }


class EvacuationDialog(QDialog):
    """«Batería al X% — ¿pasar las máquinas a otro equipo?»

    candidates: filas de hub_target_candidates (registro del Hub).
    vms: [{"name": str, "blockers": [str]}] — solo VMs ENCENDIDAS.
    """

    def __init__(self, percent: int | None, candidates: list[dict], vms: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batería baja — evacuación de máquinas")
        self.setMinimumWidth(560)
        self.candidates = candidates
        self.vms = vms

        layout = QVBoxLayout(self)
        pct = f"{percent}%" if percent is not None else "baja"
        title = QLabel(f"🔋 Batería al {pct}. ¿Pasar las máquinas encendidas a otro equipo y seguir en remoto?")
        title.setWordWrap(True)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        info = QLabel(
            "Cada máquina se migra EN VIVO (sigue encendida durante el traslado). Los CD conectados "
            "se expulsan antes. Si una falla, queda corriendo aquí, intacta, y se continúa con las demás."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.target_combo = QComboBox()
        for row in candidates:
            label = row.get("label") or row.get("hostname") or row.get("host_id", "")
            if not row.get("ready"):
                label += f" — no disponible: {row.get('reason', '')}"
            self.target_combo.addItem(label, row)
            if not row.get("ready"):
                index = self.target_combo.count() - 1
                item = self.target_combo.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        layout.addWidget(QLabel("Equipo de destino (del registro del Hub):"))
        layout.addWidget(self.target_combo)

        self.vm_list = QListWidget()
        for vm in vms:
            blockers = vm.get("blockers") or []
            mark = "✅" if not blockers else "⛔"
            suffix = "" if not blockers else f" — se queda aquí: {', '.join(blockers)}"
            item = QListWidgetItem(f"{mark} {vm['name']}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, vm)
            if blockers:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.vm_list.addItem(item)
        layout.addWidget(self.vm_list)

        buttons = QDialogButtonBox()
        self.go_button = buttons.addButton("Migrar todo en vivo", QDialogButtonBox.ButtonRole.AcceptRole)
        later = buttons.addButton("Ahora no", QDialogButtonBox.ButtonRole.RejectRole)
        later.clicked.connect(self.reject)
        self.go_button.clicked.connect(self.accept)
        self.go_button.setEnabled(bool(self.evacuable_names()) and self.selected_target() is not None)
        self.target_combo.currentIndexChanged.connect(
            lambda *_: self.go_button.setEnabled(bool(self.evacuable_names()) and self.selected_target() is not None)
        )
        layout.addWidget(buttons)

    def evacuable_names(self) -> list[str]:
        return [vm["name"] for vm in self.vms if not vm.get("blockers")]

    def selected_target(self) -> dict | None:
        row = self.target_combo.currentData()
        return row if row and row.get("ready") else None
