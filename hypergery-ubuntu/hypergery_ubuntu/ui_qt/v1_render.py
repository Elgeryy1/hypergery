"""Capa de presentación del Centro de control (v1).

Funciones puras que convierten los diccionarios de los servicios v1 en
widgets Qt legibles (tablas, tarjetas y chips de estado) en lugar de mostrar
JSON en bruto. No tienen estado y nunca lanzan excepciones: cualquier forma
inesperada del dato cae en `render_fallback`, que muestra el JSON con sangría.

Punto de entrada: `build_v1_widget(section, data) -> QWidget`.

Las claves de sección coinciden con las del Centro de control
(`main_window.V1_TAB_KEYS` / `humanize.V1_TAB_TITLES`):

    Telemetry, Orchestrator, Battery, NAS, Network, Guests,
    External Nodes, Logs

Los textos visibles están en español; los identificadores internos
(libvirt, claves del Hub, etc.) no se modifican.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import humanize

# --------------------------------------------------------------------------- #
# Utilidades de presentación (objectNames reutilizados de styles.py)           #
# --------------------------------------------------------------------------- #

# Chips de estado: (estado normalizado) -> objectName del tema.
_CHIP_OBJECTS = {
    "ok": "statusChipOk",
    "warn": "statusChipWarn",
    "bad": "statusChipBad",
    "neutral": "statusChip",
}

# Callouts (banners) por tono.
_CALLOUT_OBJECTS = {
    "ok": "calloutOk",
    "warn": "calloutWarn",
    "info": "calloutInfo",
    "danger": "calloutDanger",
}

# Severidad de evento/alerta -> tono de chip/callout.
_SEVERITY_TONE = {
    "info": "info",
    "debug": "info",
    "warning": "warn",
    "warn": "warn",
    "error": "danger",
    "critical": "danger",
}


def _as_dict(data: object) -> dict[str, Any]:
    """Devuelve `data` como dict, o {} si no lo es."""
    return data if isinstance(data, dict) else {}


def _as_list(value: object) -> list[Any]:
    """Devuelve `value` como lista, o [] si no es una lista/tupla."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _text(value: Any, default: str = "—") -> str:
    """Texto seguro para mostrar (None/'' -> default)."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _container() -> tuple[QWidget, QVBoxLayout]:
    """Widget vertical base con márgenes coherentes con el resto del tema."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    return widget, layout


def _scrollable(inner: QWidget) -> QWidget:
    """Envuelve un widget en un área con scroll vertical (listas largas)."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(inner)
    return area


def _title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    label.setWordWrap(True)
    return label


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("mutedLabel")
    label.setWordWrap(True)
    return label


def _chip(text: str, tone: str = "neutral") -> QLabel:
    """Etiqueta tipo chip (OK/WARN/FAIL) con el objectName del tema."""
    label = QLabel(text)
    label.setObjectName(_CHIP_OBJECTS.get(tone, "statusChip"))
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    return label


def _callout(text: str, tone: str = "info") -> QLabel:
    """Banner informativo/de error con el objectName del tema."""
    label = QLabel(text)
    label.setObjectName(_CALLOUT_OBJECTS.get(tone, "calloutInfo"))
    label.setWordWrap(True)
    return label


def _stat_card(value: str, caption: str, *, tone: str = "neutral") -> QWidget:
    """Tarjeta con una cifra grande (statBig) y una etiqueta (statLabel)."""
    card = QFrame()
    card.setObjectName("softPanel")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(2)
    big = QLabel(value)
    big.setObjectName(
        {"ok": "statBigOk", "bad": "statBigBad"}.get(tone, "statBig")
    )
    caption_label = QLabel(caption)
    caption_label.setObjectName("statLabel")
    caption_label.setWordWrap(True)
    layout.addWidget(big)
    layout.addWidget(caption_label)
    return card


def _stat_row(cards: Sequence[QWidget]) -> QWidget:
    """Fila horizontal de tarjetas de estadística."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for card in cards:
        layout.addWidget(card, 1)
    layout.addStretch()
    return row


def _form_card(title: str, rows: Sequence[tuple[str, Any]]) -> QWidget:
    """Tarjeta con un título y un QFormLayout (resumen de un objeto)."""
    card = QFrame()
    card.setObjectName("panel")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(16, 14, 16, 14)
    outer.setSpacing(8)
    heading = QLabel(title)
    heading.setObjectName("metricLabel")
    outer.addWidget(heading)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(6)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    for label_text, value in rows:
        key = QLabel(_text(label_text))
        key.setObjectName("metricLabel")
        if isinstance(value, QWidget):
            field: QWidget = value
        else:
            field = QLabel(_text(value))
            field.setObjectName("metricValue")
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(key, field)
    outer.addLayout(form)
    return card


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> QTableWidget:
    """Tabla de solo lectura con cabeceras (cada celda admite str o QWidget-chip)."""
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels([str(head) for head in headers])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setAlternatingRowColors(True)
    table.setWordWrap(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setStretchLastSection(True)
    for row_index, row in enumerate(rows):
        for col_index in range(len(headers)):
            value = row[col_index] if col_index < len(row) else ""
            if isinstance(value, QWidget):
                wrapper = QWidget()
                box = QHBoxLayout(wrapper)
                box.setContentsMargins(6, 2, 6, 2)
                box.addWidget(value)
                box.addStretch()
                table.setCellWidget(row_index, col_index, wrapper)
            else:
                item = QTableWidgetItem(_text(value, ""))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row_index, col_index, item)
    table.resizeRowsToContents()
    return table


def _empty(text: str) -> QWidget:
    """Panel vacío con un mensaje en español."""
    frame = QFrame()
    frame.setObjectName("emptyPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 24, 18, 24)
    label = QLabel(text)
    label.setObjectName("mutedLabel")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(label)
    return frame


# --------------------------------------------------------------------------- #
# Envoltura de error/envelope                                                  #
# --------------------------------------------------------------------------- #


def _maybe_error_envelope(data: dict[str, Any]) -> QWidget | None:
    """Si `data` es un envelope con ok=False, devuelve un callout de error.

    Reconoce el envelope de `v1.api.envelope`: {ok, data, error, ...}.
    Devuelve None cuando no es un envelope de error, para que el llamador
    siga renderizando con normalidad.
    """
    if "ok" not in data or data.get("ok"):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        message = _text(error.get("message"), "Error desconocido")
        code = _text(error.get("code"), "")
        detail = f"{message} ({code})" if code and code != "—" else message
    else:
        detail = _text(error, "Error desconocido")

    widget, layout = _container()
    layout.addWidget(_title_label("No se pudo cargar esta sección"))
    layout.addWidget(_callout(detail, tone="danger"))
    layout.addWidget(
        _muted_label("Puede ser temporal. Prueba a pulsar «Actualizar» de nuevo.")
    )
    return widget


def _unwrap_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Si `data` es un envelope correcto ({ok:True, data:{...}}), devuelve su
    `data`; en otro caso devuelve `data` tal cual. Permite alimentar los
    builders tanto con el dict directo como con el envelope de la API."""
    if data.get("ok") is True and isinstance(data.get("data"), dict):
        return data["data"]
    return data


# --------------------------------------------------------------------------- #
# render_fallback                                                              #
# --------------------------------------------------------------------------- #


def render_fallback(data: object) -> QWidget:
    """Vista de respaldo: JSON con sangría, de solo lectura. Nunca lanza."""
    widget, layout = _container()
    layout.addWidget(
        _muted_label("Vista de detalle (datos en bruto): no se encontró un formato específico.")
    )
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:  # noqa: BLE001 — el respaldo nunca debe fallar
        text = repr(data)
    view = QTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
    view.setPlainText(text)
    layout.addWidget(view, 1)
    return widget


# --------------------------------------------------------------------------- #
# Builders por sección                                                          #
# --------------------------------------------------------------------------- #


def _alert_rows(alerts: list[Any]) -> list[QWidget]:
    """Lista de chips/callouts para una lista de alertas/eventos."""
    widgets: list[QWidget] = []
    for alert in alerts:
        item = _as_dict(alert)
        severity = str(item.get("severity") or item.get("level") or "info").lower()
        tone = _SEVERITY_TONE.get(severity, "warn")
        message = _text(item.get("message"), "Aviso sin descripción")
        widgets.append(_callout(message, tone=tone))
    return widgets


def _render_telemetry(data: dict[str, Any]) -> QWidget:
    local = _as_dict(data.get("local"))
    alerts = _as_list(data.get("alerts"))
    widget, layout = _container()
    layout.addWidget(_title_label("¿Cómo va este equipo?"))

    cards: list[QWidget] = []

    cpu = local.get("cpu_percent")
    if cpu is not None:
        try:
            cpu_value = float(cpu)
            cards.append(
                _stat_card(
                    f"{cpu_value:.0f}%",
                    "Procesador",
                    tone="ok" if cpu_value < 80 else "bad",
                )
            )
        except (TypeError, ValueError):
            pass

    ram_total = local.get("ram_total_mib") or 0
    ram_free = local.get("ram_free_mib") or 0
    if ram_total:
        try:
            tone = "ok" if float(ram_free) > float(ram_total) * 0.15 else "bad"
        except (TypeError, ValueError):
            tone = "neutral"
        cards.append(
            _stat_card(
                f"{humanize._gib(ram_free)} GiB",
                f"Memoria libre · de {humanize._gib(ram_total)} GiB",
                tone=tone,
            )
        )

    disk_total = local.get("disk_total_mib") or 0
    disk_free = local.get("disk_free_mib") or 0
    if disk_total:
        try:
            tone = "ok" if float(disk_free) > 10 * 1024 else "bad"
        except (TypeError, ValueError):
            tone = "neutral"
        cards.append(
            _stat_card(
                f"{humanize._gib(disk_free)} GiB",
                f"Disco libre · de {humanize._gib(disk_total)} GiB",
                tone=tone,
            )
        )

    battery = local.get("battery_percent")
    if battery is not None:
        try:
            tone = "ok" if int(battery) > 30 else "bad"
        except (TypeError, ValueError):
            tone = "neutral"
        cards.append(_stat_card(f"{_text(battery)}%", "Batería", tone=tone))

    if cards:
        layout.addWidget(_stat_row(cards))

    rows: list[tuple[str, Any]] = [
        ("Equipo", _text(local.get("host_id"))),
        ("Encendido desde hace", humanize._fmt_uptime(local.get("uptime_seconds"))),
    ]
    if battery is None:
        rows.append(("Batería", "Sin batería (equipo de sobremesa o siempre enchufado)"))
    interfaces = _as_list(local.get("network_interfaces"))
    if interfaces:
        rows.append(("Interfaces de red", ", ".join(_text(i, "") for i in interfaces)))
    layout.addWidget(_form_card("Resumen del equipo", rows))

    if alerts:
        layout.addWidget(_title_label(f"Avisos ({len(alerts)})"))
        for callout in _alert_rows(alerts):
            layout.addWidget(callout)
    else:
        layout.addWidget(_callout("Todo en orden: sin avisos.", tone="ok"))

    return _scrollable(widget)


def _render_orchestrator(data: dict[str, Any]) -> QWidget:
    plans = _as_list(data.get("plans"))
    widget, layout = _container()
    layout.addWidget(_title_label("Sugerencias para tus máquinas"))

    moves = [_as_dict(plan) for plan in plans if _as_dict(plan).get("is_move")]
    if not plans:
        layout.addWidget(_empty("No hay máquinas que analizar todavía."))
    elif not moves:
        layout.addWidget(
            _callout(
                "No hay nada que mover: tus máquinas están bien donde están.",
                tone="ok",
            )
        )
    else:
        rows: list[list[Any]] = []
        for plan in moves:
            try:
                confidence = f"{float(plan.get('confidence') or 0) * 100:.0f}%"
            except (TypeError, ValueError):
                confidence = "—"
            rows.append(
                [
                    _text(plan.get("vm_id")),
                    _text(plan.get("current_host")),
                    _text(plan.get("target_host")),
                    _text(plan.get("reason")),
                    confidence,
                ]
            )
        layout.addWidget(
            _table(
                ["Máquina", "Ahora en", "Iría a", "Motivo", "Confianza"],
                rows,
            )
        )
        warnings = [
            warning
            for plan in moves
            for warning in _as_list(plan.get("warnings"))
        ]
        for warning in warnings:
            layout.addWidget(_callout(_text(warning), tone="warn"))

    layout.addWidget(
        _muted_label(
            "Tranquilo: esto son solo sugerencias. HyperGery no mueve nada sin que tú lo pidas."
        )
    )
    return _scrollable(widget)


def _render_battery(data: dict[str, Any]) -> QWidget:
    state = _as_dict(data.get("battery"))
    actions = _as_list(data.get("actions"))
    widget, layout = _container()
    layout.addWidget(_title_label("Batería"))

    if not state.get("available"):
        layout.addWidget(
            _callout(
                "Este equipo no tiene batería (o no se puede leer). Nada de qué preocuparse.",
                tone="info",
            )
        )
        return _scrollable(widget)

    percent = _text(state.get("percent"))
    tier = str(state.get("tier") or "normal")
    charging = bool(state.get("charging"))
    tier_text = humanize._BATTERY_TIERS_ES.get(tier, tier)

    # chip_tone usa los tonos de chip (ok/warn/bad); _callout usa danger en
    # lugar de bad, así que mapeamos al pasar el tono al callout.
    _CHIP_TO_CALLOUT = {"ok": "ok", "warn": "warn", "bad": "danger"}
    if charging:
        layout.addWidget(_callout(f"Batería al {percent}% y enchufada: todo bien.", tone="ok"))
        chip_tone = "ok"
    else:
        chip_tone = "ok" if tier == "normal" else ("warn" if tier in {"eco", "offload"} else "bad")
        layout.addWidget(
            _callout(
                f"Batería al {percent}%, sin enchufar — {tier_text}.",
                tone=_CHIP_TO_CALLOUT.get(chip_tone, "warn"),
            )
        )

    state_chip = _chip(
        humanize._BATTERY_TIERS_ES.get(tier, tier).upper(),
        tone=chip_tone,
    )
    layout.addWidget(
        _form_card(
            "Estado de la batería",
            [
                ("Carga", f"{percent}%"),
                ("Enchufada", "Sí" if charging else "No"),
                ("Nivel", state_chip),
                ("Estado del sistema", _text(state.get("status"))),
            ],
        )
    )

    if actions:
        layout.addWidget(_title_label("Qué conviene hacer"))
        rows: list[list[Any]] = []
        for action in actions:
            item = _as_dict(action)
            kind = str(item.get("kind") or "")
            label = humanize._BATTERY_ACTIONS_ES.get(kind, _text(item.get("reason"), kind))
            prepared = "Preparada" if item.get("prepared") else "Solo sugerida"
            rows.append([label, prepared])
        layout.addWidget(_table(["Recomendación", "Estado"], rows))
        layout.addWidget(
            _muted_label("HyperGery no hace nada de esto por su cuenta: son recomendaciones.")
        )
    return _scrollable(widget)


def _render_nas(data: dict[str, Any]) -> QWidget:
    health = _as_dict(data.get("health"))
    commits = _as_list(data.get("commits"))
    widget, layout = _container()
    layout.addWidget(_title_label("Copias de seguridad en el NAS"))

    if health.get("ok"):
        layout.addWidget(_callout("El NAS está conectado y funciona correctamente.", tone="ok"))
    elif not health.get("exists"):
        layout.addWidget(
            _callout(
                "No se encuentra la carpeta del NAS. ¿Está el NAS encendido y conectado?",
                tone="danger",
            )
        )
    elif not health.get("writable"):
        layout.addWidget(
            _callout(
                "El NAS se ve, pero no se puede escribir en él. Revisa permisos o espacio.",
                tone="danger",
            )
        )

    rows: list[tuple[str, Any]] = [
        ("Carpeta del NAS", _text(health.get("nas_root"))),
        ("Espacio libre", f"{humanize._gib(health.get('free_mib'))} GiB"),
        ("Se puede leer", "Sí" if health.get("readable") else "No"),
        ("Se puede escribir", "Sí" if health.get("writable") else "No"),
    ]
    last = _as_dict(health.get("last_commit"))
    if last:
        rows.append(
            (
                "Última copia",
                f"lab {_text(last.get('lab_id'))} · {humanize._fmt_when(last.get('created_at'))}",
            )
        )
    else:
        rows.append(("Última copia", "Todavía no hay ninguna copia guardada"))
    layout.addWidget(_form_card("Estado del NAS", rows))

    if commits:
        layout.addWidget(_title_label(f"Copias recientes ({len(commits)})"))
        table_rows: list[list[Any]] = []
        for commit in reversed(commits):
            item = _as_dict(commit)
            files = _as_list(item.get("files"))
            table_rows.append(
                [
                    _text(item.get("lab_id")),
                    humanize._fmt_when(item.get("created_at")),
                    str(len(files)),
                    "Sí" if item.get("include_disks") else "No",
                ]
            )
        layout.addWidget(
            _table(["Laboratorio", "Guardada", "Archivos", "Con discos"], table_rows)
        )
    return _scrollable(widget)


def _render_network(data: dict[str, Any]) -> QWidget:
    networks = _as_list(data.get("networks"))
    validation = _as_dict(data.get("validation"))
    widget, layout = _container()
    layout.addWidget(_title_label("Redes de tus laboratorios"))

    if validation.get("ok"):
        layout.addWidget(
            _callout("Las redes están bien configuradas, sin conflictos entre ellas.", tone="ok")
        )
    for error in _as_list(validation.get("errors")):
        layout.addWidget(_callout(_text(error), tone="danger"))
    for warning in _as_list(validation.get("warnings")):
        layout.addWidget(_callout(_text(warning), tone="warn"))

    if not networks:
        layout.addWidget(
            _empty("Todavía no hay redes: se crean automáticamente con cada laboratorio.")
        )
        return _scrollable(widget)

    layout.addWidget(_title_label(f"Tus redes ({len(networks)})"))
    rows: list[list[Any]] = []
    for network in networks:
        item = _as_dict(network)
        mode = str(item.get("mode") or "")
        mode_text = humanize._NETWORK_MODES_ES.get(mode, mode or "—")
        rows.append(
            [
                _text(item.get("name")),
                _text(item.get("lab_id")),
                mode_text,
                _text(item.get("cidr"), "sin direcciones"),
                _text(item.get("gateway"), "—"),
            ]
        )
    layout.addWidget(
        _table(["Red", "Laboratorio", "Tipo", "Direcciones", "Puerta de enlace"], rows)
    )
    return _scrollable(widget)


def _render_guests(data: dict[str, Any]) -> QWidget:
    users = _as_list(data.get("users"))
    widget, layout = _container()
    layout.addWidget(_title_label("Personas que usan HyperGery"))

    if not users:
        layout.addWidget(
            _empty(
                "No hay usuarios adicionales configurados: solo tú usas HyperGery en este equipo."
            )
        )
        return _scrollable(widget)

    rows: list[list[Any]] = []
    for user in users:
        item = _as_dict(user)
        role = str(item.get("role") or "Guest")
        role_text = humanize._ROLES_ES.get(role, role)
        labs = _as_list(item.get("assigned_labs"))
        labs_text = ", ".join(_text(lab, "") for lab in labs) if labs else "ninguno"
        permissions = _as_list(item.get("effective_permissions"))
        rows.append(
            [
                _text(item.get("name")),
                role_text,
                labs_text,
                str(len(permissions)),
            ]
        )
    layout.addWidget(_table(["Nombre", "Rol", "Labs asignados", "Permisos"], rows))
    return _scrollable(widget)


def _render_external_nodes(data: dict[str, Any]) -> QWidget:
    nodes = _as_list(data.get("nodes"))
    widget, layout = _container()
    layout.addWidget(_title_label("Equipos externos"))

    if not nodes:
        layout.addWidget(_empty("No hay equipos externos registrados."))
        layout.addWidget(
            _muted_label(
                "Un equipo externo es otro ordenador (fuera de tus dos hosts) que puede "
                "echar una mano ejecutando máquinas. Se añaden desde la línea de comandos."
            )
        )
        return _scrollable(widget)

    rows: list[list[Any]] = []
    for node in nodes:
        item = _as_dict(node)
        health = _as_dict(item.get("health"))
        reachable = bool(health.get("reachable"))
        chip = _chip("RESPONDE" if reachable else "NO RESPONDE", tone="ok" if reachable else "warn")
        rows.append(
            [
                _text(item.get("name")),
                _text(item.get("type")),
                _text(item.get("address"), "sin dirección"),
                chip,
            ]
        )
    layout.addWidget(_table(["Equipo", "Tipo", "Dirección", "Estado"], rows))
    return _scrollable(widget)


def _render_logs(data: dict[str, Any]) -> QWidget:
    events = _as_list(data.get("events"))
    widget, layout = _container()
    layout.addWidget(_title_label("Última actividad"))

    if not events:
        layout.addWidget(_empty("Todavía no hay actividad registrada."))
        return _scrollable(widget)

    recent = events[-30:]
    rows: list[list[Any]] = []
    for event in reversed(recent):
        item = _as_dict(event)
        level = str(item.get("level") or "info").lower()
        tone = _SEVERITY_TONE.get(level, "neutral")
        category = str(item.get("category") or "")
        category_text = humanize._LOG_CATEGORIES_ES.get(category, category or "—")
        rows.append(
            [
                _chip(level.upper(), tone=tone),
                humanize._fmt_when(item.get("timestamp")),
                category_text,
                _text(item.get("message"), ""),
            ]
        )
    layout.addWidget(_table(["Nivel", "Cuándo", "Categoría", "Mensaje"], rows))
    if len(events) > len(recent):
        layout.addWidget(
            _muted_label(
                f"Mostrando los últimos {len(recent)} de {len(events)} eventos. "
                "El resto está en los detalles técnicos."
            )
        )
    return _scrollable(widget)


# --------------------------------------------------------------------------- #
# Dispatcher                                                                    #
# --------------------------------------------------------------------------- #

_BUILDERS: dict[str, Callable[[dict[str, Any]], QWidget]] = {
    "Telemetry": _render_telemetry,
    "Orchestrator": _render_orchestrator,
    "Battery": _render_battery,
    "NAS": _render_nas,
    "Network": _render_network,
    "Guests": _render_guests,
    "External Nodes": _render_external_nodes,
    "Logs": _render_logs,
}


def supported_sections() -> tuple[str, ...]:
    """Claves de sección que `build_v1_widget` sabe renderizar."""
    return tuple(_BUILDERS)


def build_v1_widget(section: str, data: object) -> QWidget:
    """Construye el widget temático para una sección del Centro de control.

    `section` es una de las claves de `supported_sections()`. `data` es el
    dict que esa pestaña muestra hoy como JSON (o un envelope de la API).
    Ante cualquier sección desconocida, forma inesperada o error, recurre a
    `render_fallback`. Nunca lanza excepciones.
    """
    try:
        as_dict = _as_dict(data)

        # Envelope de error de la API: se muestra de forma prominente.
        error_widget = _maybe_error_envelope(as_dict)
        if error_widget is not None:
            return error_widget

        builder = _BUILDERS.get(section)
        if builder is None:
            return render_fallback(data)

        if not isinstance(data, dict):
            return render_fallback(data)

        payload = _unwrap_envelope(as_dict)
        return builder(payload)
    except Exception:  # noqa: BLE001 — el Centro de control nunca debe romperse
        return render_fallback(data)
