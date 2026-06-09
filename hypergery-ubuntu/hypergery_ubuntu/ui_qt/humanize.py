"""Resúmenes en lenguaje claro (español) para el Centro de control.

Funciones puras: reciben el payload de cada servicio v1 y devuelven HTML
sencillo pensado para personas no técnicas. El JSON completo sigue
disponible en la vista de "detalles técnicos"; aquí solo se traduce y
se resume lo importante.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any

OK = "✅"
WARN = "⚠️"
ERROR = "❌"
INFO = "ℹ️"
IDEA = "💡"

V1_TAB_TITLES = {
    "Telemetry": "Mi equipo",
    "Orchestrator": "Sugerencias",
    "Battery": "Batería",
    "NAS": "Copias en el NAS",
    "Network": "Redes",
    "Guests": "Usuarios",
    "External Nodes": "Equipos externos",
    "Logs": "Historial",
}

_NETWORK_MODES_ES = {
    "nat": "con salida a internet (NAT)",
    "internal": "aislada (sin internet)",
    "host_only": "solo visible desde este equipo",
    "bridged": "conectada a tu red local",
    "simulated": "simulada",
}

_ROLES_ES = {
    "Admin": "Administrador (puede hacer de todo)",
    "Operator": "Operador (gestiona máquinas y labs)",
    "Guest": "Invitado (solo sus labs asignados)",
}

_BATTERY_TIERS_ES = {
    "normal": "nivel normal",
    "eco": "modo ahorro recomendado",
    "offload": "conviene aligerar la carga",
    "emergency": "nivel de emergencia",
    "critical": "nivel CRÍTICO",
}

_BATTERY_ACTIONS_ES = {
    "reduce_refresh": "Bajar la frecuencia de actualización para ahorrar batería",
    "recommend_stop_heavy_vms": "Plantearse apagar las máquinas que más consumen",
    "prepare_teleport": "Preparar el envío de las máquinas a un equipo enchufado",
    "nas_commit": "Guardar una copia de los labs en el NAS mientras se pueda",
    "emergency_shutdown_recommended": "Enchufar el equipo o apagar las máquinas YA",
}

_LOG_CATEGORIES_ES = {
    "telemetry": "estado del equipo",
    "orchestrator": "sugerencias",
    "battery": "batería",
    "nas": "copias NAS",
    "network": "redes",
    "guest": "usuarios",
    "teleport": "teletransporte",
    "labx": "labs",
    "api": "API",
}

_SEVERITY_ICONS = {"info": INFO, "warning": WARN, "error": ERROR, "critical": ERROR, "debug": INFO}


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _gib(mib: Any) -> str:
    try:
        value = float(mib)
    except (TypeError, ValueError):
        return "?"
    if value <= 0:
        return "0"
    gib = value / 1024.0
    return f"{gib:.1f}".rstrip("0").rstrip(".")


def _fmt_when(iso_text: Any) -> str:
    """Fecha ISO → "06/06/2026 a las 18:32" (hora local del texto)."""
    text = str(iso_text or "").strip()
    if not text:
        return "fecha desconocida"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return moment.strftime("%d/%m/%Y a las %H:%M")


def _fmt_uptime(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "desconocido"
    if total <= 0:
        return "desconocido"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days} día{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if not days and minutes:
        parts.append(f"{minutes} min")
    return " y ".join(parts) if parts else "menos de un minuto"


def _line(icon: str, text: str) -> str:
    return f"<p style='margin:4px 0'>{icon} {text}</p>"


def _title(text: str) -> str:
    return f"<h3 style='margin:0 0 8px 0'>{text}</h3>"


def _muted(text: str) -> str:
    return f"<p style='margin:8px 0 0 0; color:#8a93a6'><i>{text}</i></p>"


# --------------------------------------------------------------------------- #
# Secciones                                                                    #
# --------------------------------------------------------------------------- #


def _telemetry(payload: dict[str, Any]) -> str:
    local = payload.get("local") or {}
    alerts = payload.get("alerts") or []
    out = [_title("¿Cómo va este equipo?")]

    cpu = local.get("cpu_percent")
    if cpu is not None:
        cpu_value = float(cpu)
        icon = OK if cpu_value < 80 else WARN
        out.append(_line(icon, f"Procesador trabajando al <b>{cpu_value:.0f}%</b>."))

    ram_total = local.get("ram_total_mib") or 0
    ram_free = local.get("ram_free_mib") or 0
    if ram_total:
        icon = OK if ram_free > ram_total * 0.15 else WARN
        out.append(_line(icon, f"Memoria: <b>{_gib(ram_free)} GiB libres</b> de {_gib(ram_total)} GiB."))

    disk_total = local.get("disk_total_mib") or 0
    disk_free = local.get("disk_free_mib") or 0
    if disk_total:
        icon = OK if disk_free > 10 * 1024 else WARN
        out.append(_line(icon, f"Disco: <b>{_gib(disk_free)} GiB libres</b> de {_gib(disk_total)} GiB."))

    battery = local.get("battery_percent")
    if battery is None:
        out.append(_line(INFO, "Sin batería: es un equipo de sobremesa o está siempre enchufado."))
    else:
        out.append(_line(OK if int(battery) > 30 else WARN, f"Batería al <b>{battery}%</b>."))

    out.append(_line(INFO, f"Encendido desde hace {_fmt_uptime(local.get('uptime_seconds'))}."))

    if alerts:
        out.append("<p style='margin:10px 0 4px 0'><b>Avisos:</b></p>")
        for alert in alerts:
            icon = _SEVERITY_ICONS.get(str(alert.get("severity")), WARN)
            out.append(_line(icon, _esc(alert.get("message", ""))))
    else:
        out.append(_line(OK, "<b>Todo en orden</b>: sin avisos."))
    return "".join(out)


def _orchestrator(payload: dict[str, Any]) -> str:
    plans = payload.get("plans") or []
    out = [_title("Sugerencias para tus máquinas")]
    moves = [plan for plan in plans if plan.get("is_move")]
    if not moves:
        out.append(_line(OK, "No hay nada que mover: tus máquinas están bien donde están."))
    else:
        for plan in moves:
            confidence = float(plan.get("confidence") or 0) * 100
            out.append(
                _line(
                    IDEA,
                    f"La máquina <b>{_esc(plan.get('vm_id'))}</b> iría mejor en "
                    f"<b>{_esc(plan.get('target_host'))}</b> (ahora está en {_esc(plan.get('current_host'))}). "
                    f"Motivo: {_esc(plan.get('reason'))} — confianza {confidence:.0f}%.",
                )
            )
            for warning in plan.get("warnings") or []:
                out.append(_line(WARN, _esc(warning)))
    out.append(_muted("Tranquilo: esto son solo sugerencias. HyperGery no mueve nada sin que tú lo pidas."))
    return "".join(out)


def _battery(payload: dict[str, Any]) -> str:
    state = payload.get("battery") or {}
    actions = payload.get("actions") or []
    out = [_title("Batería")]
    if not state.get("available"):
        out.append(_line(INFO, "Este equipo no tiene batería (o no se puede leer). Nada de qué preocuparse."))
        return "".join(out)

    percent = state.get("percent")
    tier = str(state.get("tier") or "normal")
    if state.get("charging"):
        out.append(_line(OK, f"Batería al <b>{percent}%</b> y <b>enchufada</b>: todo bien."))
    else:
        icon = OK if tier == "normal" else (WARN if tier in {"eco", "offload"} else ERROR)
        out.append(_line(icon, f"Batería al <b>{percent}%</b>, sin enchufar — {_BATTERY_TIERS_ES.get(tier, tier)}."))

    if actions:
        out.append("<p style='margin:10px 0 4px 0'><b>Qué conviene hacer:</b></p>")
        for action in actions:
            kind = str(action.get("kind") or "")
            out.append(_line(IDEA, _BATTERY_ACTIONS_ES.get(kind, _esc(action.get("reason", kind)))))
        out.append(_muted("HyperGery no hace nada de esto por su cuenta: son recomendaciones."))
    return "".join(out)


def _nas(payload: dict[str, Any]) -> str:
    health = payload.get("health") or {}
    commits = payload.get("commits") or []
    out = [_title("Copias de seguridad en el NAS")]
    if health.get("ok"):
        out.append(_line(OK, "El NAS está conectado y <b>funciona correctamente</b>."))
        out.append(_line(INFO, f"Espacio libre en el NAS: <b>{_gib(health.get('free_mib'))} GiB</b>."))
    elif not health.get("exists"):
        out.append(_line(ERROR, "No se encuentra la carpeta del NAS. ¿Está el NAS encendido y conectado?"))
        out.append(_muted(f"Carpeta esperada: {_esc(health.get('nas_root', ''))}"))
    elif not health.get("writable"):
        out.append(_line(ERROR, "El NAS se ve, pero <b>no se puede escribir</b> en él. Revisa permisos o espacio."))

    last = health.get("last_commit")
    if last:
        out.append(
            _line(
                INFO,
                f"Última copia: lab <b>{_esc(last.get('lab_id', '?'))}</b>, "
                f"guardada el {_fmt_when(last.get('created_at'))}.",
            )
        )
    else:
        out.append(_line(INFO, "Todavía no hay ninguna copia guardada."))

    if commits:
        out.append(f"<p style='margin:10px 0 4px 0'><b>Copias recientes ({len(commits)}):</b></p>")
        for commit in reversed(commits):
            out.append(
                _line(
                    "🗂️",
                    f"Lab <b>{_esc(commit.get('lab_id', '?'))}</b> — {_fmt_when(commit.get('created_at'))}.",
                )
            )
    return "".join(out)


def _network(payload: dict[str, Any]) -> str:
    networks = payload.get("networks") or []
    validation = payload.get("validation") or {}
    out = [_title("Redes de tus laboratorios")]
    if not networks:
        out.append(_line(INFO, "Todavía no hay redes: se crean automáticamente con cada laboratorio."))
        return "".join(out)

    if validation.get("ok"):
        out.append(_line(OK, "Las redes están bien configuradas, <b>sin conflictos</b> entre ellas."))
    for error in validation.get("errors") or []:
        out.append(_line(ERROR, _esc(error)))
    for warning in validation.get("warnings") or []:
        out.append(_line(WARN, _esc(warning)))

    out.append(f"<p style='margin:10px 0 4px 0'><b>Tus redes ({len(networks)}):</b></p>")
    for network in networks:
        mode = _NETWORK_MODES_ES.get(str(network.get("mode")), str(network.get("mode")))
        cidr = network.get("cidr") or "sin direcciones"
        out.append(
            _line("🌐", f"<b>{_esc(network.get('name'))}</b> (lab {_esc(network.get('lab_id'))}) — {mode}, direcciones {_esc(cidr)}.")
        )
    return "".join(out)


def _guests(payload: dict[str, Any]) -> str:
    users = payload.get("users") or []
    out = [_title("Personas que usan HyperGery")]
    if not users:
        out.append(_line(INFO, "No hay usuarios adicionales configurados: solo tú usas HyperGery en este equipo."))
        return "".join(out)
    for user in users:
        role = str(user.get("role") or "Guest")
        labs = user.get("assigned_labs") or []
        labs_text = ", ".join(_esc(lab) for lab in labs) if labs else "ninguno"
        out.append(
            _line(
                "👤",
                f"<b>{_esc(user.get('name'))}</b> — {_ROLES_ES.get(role, _esc(role))}. Labs asignados: {labs_text}.",
            )
        )
    return "".join(out)


def _external_nodes(payload: dict[str, Any]) -> str:
    nodes = payload.get("nodes") or []
    out = [_title("Equipos externos")]
    if not nodes:
        out.append(_line(INFO, "No hay equipos externos registrados."))
        out.append(
            _muted(
                "Un equipo externo es otro ordenador (fuera de tus dos hosts) que puede "
                "echar una mano ejecutando máquinas. Se añaden desde la línea de comandos."
            )
        )
        return "".join(out)
    for node in nodes:
        health = node.get("health") or {}
        reachable = bool(health.get("reachable")) if isinstance(health, dict) else False
        icon = OK if reachable else WARN
        status = "responde" if reachable else "no responde ahora mismo"
        out.append(
            _line(
                icon,
                f"<b>{_esc(node.get('name'))}</b> ({_esc(node.get('address') or 'sin dirección')}) — {status}.",
            )
        )
    return "".join(out)


def _logs(payload: dict[str, Any]) -> str:
    events = payload.get("events") or []
    out = [_title("Última actividad")]
    if not events:
        out.append(_line(INFO, "Todavía no hay actividad registrada."))
        return "".join(out)
    recent = list(events)[-30:]
    for event in reversed(recent):
        icon = _SEVERITY_ICONS.get(str(event.get("level")), INFO)
        category = _LOG_CATEGORIES_ES.get(str(event.get("category")), str(event.get("category") or ""))
        out.append(
            _line(
                icon,
                f"<span style='color:#8a93a6'>{_fmt_when(event.get('timestamp'))}</span> "
                f"<b>[{_esc(category)}]</b> {_esc(event.get('message', ''))}",
            )
        )
    if len(events) > len(recent):
        out.append(_muted(f"Mostrando los últimos {len(recent)} de {len(events)} eventos. El resto está en los detalles técnicos."))
    return "".join(out)


_RENDERERS = {
    "Telemetry": _telemetry,
    "Orchestrator": _orchestrator,
    "Battery": _battery,
    "NAS": _nas,
    "Network": _network,
    "Guests": _guests,
    "External Nodes": _external_nodes,
    "Logs": _logs,
}


def humanize_v1(key: str, payload: dict[str, Any]) -> str:
    """HTML en español claro para una sección del Centro de control."""
    renderer = _RENDERERS.get(key)
    if renderer is None or not isinstance(payload, dict):
        return _line(WARN, "No hay un resumen disponible para esta sección.")
    try:
        return renderer(payload)
    except Exception as exc:  # noqa: BLE001 — el resumen nunca debe romper la UI
        return _line(WARN, f"No se ha podido generar el resumen: {_esc(exc)}")


def humanize_error(key: str, message: str) -> str:
    """HTML para cuando una sección no se puede cargar."""
    title = V1_TAB_TITLES.get(key, key)
    return (
        _title(title)
        + _line(ERROR, f"No se ha podido cargar esta sección: {_esc(message)}")
        + _muted("Puede ser temporal. Prueba a pulsar «Actualizar» de nuevo.")
    )


# --------------------------------------------------------------------------- #
# Estados, acciones y errores visibles (solo presentación; los valores         #
# internos de libvirt/Hub no se tocan)                                          #
# --------------------------------------------------------------------------- #

# (detalle "Apagada", tabla "APAGADA") por tipo de estado normalizado.
_VM_STATES_ES = {
    "running": ("Encendida", "ENCENDIDA"),
    "shutoff": ("Apagada", "APAGADA"),
    "paused": ("En pausa", "EN PAUSA"),
    "not created": ("No creada", "NO CREADA"),
    "unknown": ("Desconocida", "DESCONOCIDA"),
}


def _vm_state_kind(state: Any) -> str:
    value = str(state or "").strip().lower()
    if value in {"not created", "not_created"}:
        return "not created"
    if "running" in value:
        return "running"
    if "paused" in value:
        return "paused"
    if "shut" in value or "off" in value:
        return "shutoff"
    return "unknown"


def humanize_vm_status(status: Any, style: str = "detail") -> str:
    """Estado libvirt → texto visible en español.

    style="table" → mayúsculas (APAGADA); "detail"/"title" → capitalizado (Apagada).
    El valor interno (shut off, running…) no se modifica nunca: esto es solo
    para mostrar.
    """
    detail, table = _VM_STATES_ES[_vm_state_kind(status)]
    return table if style == "table" else detail


_COMMAND_STATUS_ES = {
    "pending": ("Pendiente", "PENDIENTE"),
    "sent": ("Enviada", "ENVIADA"),
    "running": ("En curso", "EN CURSO"),
    "done": ("Completada", "COMPLETADA"),
    "failed": ("Falló", "FALLÓ"),
    "expired": ("Caducada", "CADUCADA"),
    "cancelled": ("Cancelada", "CANCELADA"),
}


def humanize_command_status(status: Any, style: str = "table") -> str:
    """Estado de una orden/traslado del Hub → texto visible en español."""
    value = str(status or "").strip().lower()
    pair = _COMMAND_STATUS_ES.get(value)
    if pair is None:
        pair = ("Desconocida", "DESCONOCIDA") if not value else (value, value.upper())
    return pair[1] if style == "table" else pair[0]


_LAB_ACTIONS_ES = {
    "start": "arranque",
    "shutdown": "apagado",
    "force_off": "apagado forzado",
}


def humanize_lab_action(action: Any) -> str:
    """Acción de laboratorio (start/shutdown) → palabra en español."""
    value = str(action or "").strip().lower()
    return _LAB_ACTIONS_ES.get(value, value)


_NETWORK_LABELS_ES = {
    "subnet": "Subred",
    "bridge": "Puente",
    "bridge_name": "Puente",
    "network": "Red",
    "unknown": "desconocido",
    "nat": "NAT",
    "isolated": "aislada",
}


def humanize_network_label(label: Any) -> str:
    """Etiqueta técnica de red (subnet, bridge…) → texto visible en español."""
    value = str(label or "").strip()
    return _NETWORK_LABELS_ES.get(value.lower(), value)


# Señales de "falta un archivo" en errores de libvirt/virsh (ES y EN).
_MISSING_FILE_MARKERS = (
    "cannot access storage file",
    "no such file or directory",
    "no existe el archivo o el directorio",
    "no se puede acceder al archivo",
)

# Señales de error técnico de arranque que conviene encapsular.
_TECHNICAL_START_MARKERS = (
    "failed to start domain",
    "virsh",
    "qemu:///system",
)


def _find_missing_file(text: str) -> str:
    """Devuelve la ruta/nombre del archivo que falta, si se puede extraer."""
    lowered = text.lower()
    if not any(marker in lowered for marker in _MISSING_FILE_MARKERS):
        return ""
    # Rutas entre comillas simples (formato habitual de libvirt) o rutas absolutas.
    for pattern in (r"'(/[^']+)'", r"(/\S+\.(?:iso|qcow2|img|raw))"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def humanize_error_message(error_text: Any) -> str:
    """Error técnico → resumen humano en español + detalle técnico al final.

    Si el texto no contiene jerga conocida (virsh, Failed to start domain,
    archivos que faltan…), se devuelve tal cual. Nunca se pierde el detalle
    técnico: queda al final, después de la explicación.
    """
    text = str(error_text or "").strip()
    if not text:
        return text
    lowered = text.lower()
    missing = _find_missing_file(text)
    technical = any(marker in lowered for marker in _TECHNICAL_START_MARKERS)
    if not missing and not technical:
        return text

    if missing:
        base = missing.rsplit("/", 1)[-1]
        if base.lower().endswith(".iso"):
            summary = f"No se pudo encender la máquina porque falta la ISO {base}."
        else:
            summary = f"No se pudo encender la máquina porque falta un archivo de disco ({base})."
        steps = (
            "Qué puedes hacer:\n"
            "1. Comprueba que el NAS está montado.\n"
            "2. Corrige la ruta de la ISO o del disco en la configuración de la máquina.\n"
            "3. Si estás haciendo una migración de prueba, usa la opción sin ISO cuando corresponda."
        )
    else:
        summary = "No se pudo completar la operación con la máquina virtual."
        steps = (
            "Qué puedes hacer:\n"
            "1. Comprueba que la máquina y sus archivos existen en este equipo.\n"
            "2. Revisa el Diagnóstico (libvirt y KVM deben estar en verde).\n"
            "3. Vuelve a intentarlo; si sigue fallando, copia el detalle técnico."
        )
    return f"{summary}\n\n{steps}\n\nDetalle técnico:\n{text}"


# --------------------------------------------------------------------------- #
# Tareas remotas: tipos de orden y mensajes del agente (solo presentación;     #
# los command_type y payloads del Hub no se tocan)                             #
# --------------------------------------------------------------------------- #

_COMMAND_TYPES_ES = {
    "ping": "Comprobar equipo",
    "preflight": "Comprobación previa",
    "list_vms": "Listar máquinas",
    "receive_vm_package": "Recibir máquina",
    "import_vm_package": "Importar máquina",
    "migration_status": "Estado del traslado",
    "vm_start": "Encender máquina",
    "vm_shutdown": "Apagar máquina",
    "vm_force_off": "Apagado forzado",
    "restore_vm_state_package": "Reanudar máquina trasladada",
}


def humanize_command_type(command_type: Any) -> str:
    """Tipo de orden del Hub (vm_start, ping…) → texto visible en español."""
    value = str(command_type or "").strip()
    return _COMMAND_TYPES_ES.get(value, value)


# "start"/"shutdown"/"force off" tal y como los escribe el agente en sus
# mensajes (action.replace("_", " ")).
_VM_ACTION_NOUNS_ES = {"start": "Encendido", "shutdown": "Apagado", "force off": "Apagado forzado"}
_VM_ACTION_VERBS_ES = {"start": "encender", "shutdown": "apagar", "force off": "forzar el apagado de"}

_EXECUTED_RE = re.compile(r"^(start|shutdown|force off) executed on (\S+?)(?: \(([^)]+) -> ([^)]+)\))?\.?$")
_BACKEND_FAILED_RE = re.compile(r"^Backend failed to (start|shutdown|force off) (\S+?): ?(.*)$", re.DOTALL)
_CANNOT_STATE_RE = re.compile(r"^Cannot (start|shutdown|force off) (\S+?): VM state is '([^']+)'\.", re.DOTALL)
_TARGET_EXISTS_RE = re.compile(r"^Target VM (name )?already exists( locally)?:? ?(\S*)$")


def humanize_command_message(message: Any) -> str:
    """Mensaje/error técnico del agente → frase en español.

    Si el texto no coincide con ningún patrón conocido se devuelve tal cual:
    nunca se inventa una traducción.
    """
    text = str(message or "").strip()
    if not text:
        return text

    match = _EXECUTED_RE.match(text)
    if match:
        noun = _VM_ACTION_NOUNS_ES[match.group(1)]
        states = ""
        if match.group(3) and match.group(4):
            before = humanize_vm_status(match.group(3)).lower()
            after = humanize_vm_status(match.group(4)).lower()
            states = f" (antes {before}, ahora {after})"
        return f"{noun} ejecutado en {match.group(2)}{states}"

    match = _BACKEND_FAILED_RE.match(text)
    if match:
        verb = _VM_ACTION_VERBS_ES[match.group(1)]
        base = f"No se pudo {verb} la máquina {match.group(2)}"
        detail = match.group(3).strip()
        return f"{base}: {detail}" if detail else base

    match = _CANNOT_STATE_RE.match(text)
    if match:
        verb = _VM_ACTION_VERBS_ES[match.group(1)]
        state = humanize_vm_status(match.group(3)).lower()
        return f"No se puede {verb} la máquina {match.group(2)}: ahora mismo está {state}"

    match = _TARGET_EXISTS_RE.match(text)
    if match:
        name = match.group(3)
        where = " en ese equipo" if match.group(2) else ""
        suffix = f": {name}" if name else ""
        return f"La máquina de destino ya existe{where}{suffix}"

    return text


# Campos habituales de payload/result de las órdenes → etiqueta en español.
_COMMAND_FIELDS_ES = (
    ("vm_name", "máquina"),
    ("source_vm_name", "máquina origen"),
    ("target_vm_name", "máquina destino"),
    ("host_id", "equipo"),
    ("target_host_id", "equipo destino"),
    ("migration_id", "traslado"),
)


def humanize_command_value(value: Any) -> str:
    """Datos/Resultado de una orden del Hub → resumen corto en español.

    Evita enseñar JSON crudo en la tabla; el JSON completo sigue disponible
    con «Copiar resultado».
    """
    if isinstance(value, dict):
        message = value.get("message") or value.get("error")
        if message:
            return humanize_command_message(str(message))
        if value.get("pong"):
            host = str(value.get("host_id") or "")
            return f"El equipo {host} responde" if host else "El equipo responde"
        parts = [f"{label}: {value[key]}" for key, label in _COMMAND_FIELDS_ES if value.get(key)]
        if parts:
            return " · ".join(parts)
        return "Detalle técnico (JSON) — usa «Copiar resultado»"
    return humanize_command_message(str(value))


# --------------------------------------------------------------------------- #
# Registro de actividad: resumen de los bloques técnicos (JSON de qemu-img,    #
# XML de libvirt). El detalle completo sigue en el archivo de registro.        #
# --------------------------------------------------------------------------- #

_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+)\s+(INFO|WARNING|ERROR|DEBUG|CRITICAL)\s(.*)$"
)


def _gib_bytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "?"
    if size < 0:
        return "?"
    return f"{size / 1024 ** 3:.1f}".rstrip("0").rstrip(".")


def _summarize_disk_info(info: dict[str, Any]) -> str:
    """JSON de `qemu-img info` → una línea en español."""
    name = str(info.get("filename") or "").rsplit("/", 1)[-1] or "disco"
    fmt = str(info.get("format") or "?")
    if bool(info.get("dirty-flag")):
        pending = "cambios pendientes: sí (la máquina no se cerró limpiamente)"
    else:
        pending = "sin cambios pendientes"
    return (
        f"Disco {name} ({fmt}): {pending} · "
        f"tamaño máximo {_gib_bytes(info.get('virtual-size'))} GiB, "
        f"ocupa {_gib_bytes(info.get('actual-size'))} GiB"
    )


def _summarize_log_message(message: str) -> str | None:
    """Resumen en español de un mensaje del registro, o None si se deja igual."""
    stripped = message.strip()
    for head in ("stdout: ", "stderr: "):
        if stripped.startswith(head):
            payload_text = stripped[len(head):].strip()
            break
    else:
        return None
    if payload_text.startswith("{"):
        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and ("dirty-flag" in data or "virtual-size" in data):
            return _summarize_disk_info(data)
        if isinstance(data, dict):
            return f"Datos técnicos (JSON, {len(data)} campos) — detalle en el archivo de registro"
        return None
    if payload_text.startswith("<"):
        name_match = re.search(r"<name>([^<]+)</name>", payload_text)
        target = f" de «{name_match.group(1)}»" if name_match else ""
        return f"Configuración{target} leída (XML) — detalle en el archivo de registro"
    return None


def humanize_activity_log(text: Any) -> str:
    """Tail del registro → mismo registro con los bloques técnicos resumidos.

    Las líneas normales no se tocan; solo los volcados multilínea (JSON de
    qemu-img, XML de libvirt) se sustituyen por una línea en español. El
    detalle completo sigue en el archivo hypergery.log.
    """
    prefixes: list[str] = []
    entries: list[list[str]] = []
    for line in str(text or "").splitlines():
        match = _LOG_LINE_RE.match(line)
        if match:
            prefixes.append(f"{match.group(1)} {match.group(2)} ")
            entries.append([match.group(3)])
        elif entries:
            entries[-1].append(line)
        else:
            prefixes.append("")
            entries.append([line])
    out: list[str] = []
    for prefix, body in zip(prefixes, entries):
        summary = _summarize_log_message("\n".join(body))
        if summary is not None:
            out.append(prefix + summary)
        else:
            out.append(prefix + body[0])
            out.extend(body[1:])
    return "\n".join(out)
