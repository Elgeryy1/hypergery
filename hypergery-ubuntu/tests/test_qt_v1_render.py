"""Tests del Centro de control sin JSON crudo (ui_qt/v1_render.py).

Cada sección se renderiza con (a) un dict realista, (b) un dict vacío, (c)
None y (d) un envelope de error {ok:False, error:...}. En todos los casos el
builder debe devolver un QWidget y nunca lanzar excepciones.
"""

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from hypergery_ubuntu.ui_qt import v1_render


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


# Un dict realista por sección, con las formas que produce main_window._v1_collect.
REALISTIC = {
    "Telemetry": {
        "local": {
            "host_id": "laptop-1",
            "cpu_percent": 42.5,
            "ram_total_mib": 16384,
            "ram_free_mib": 8192,
            "disk_total_mib": 512000,
            "disk_free_mib": 120000,
            "battery_percent": 76,
            "battery_status": "discharging",
            "uptime_seconds": 93600,
            "network_interfaces": ["eth0", "wlan0"],
        },
        "alerts": [
            {"severity": "warning", "kind": "ram_low", "host": "laptop-1", "message": "Low RAM."},
            {"severity": "info", "kind": "battery_eco", "host": "laptop-1", "message": "Battery eco."},
        ],
    },
    "Orchestrator": {
        "plans": [
            {
                "lab_id": "lab-a",
                "vm_id": "vm-1",
                "current_host": "laptop-1",
                "target_host": "home-pc",
                "reason": "Battery low; move to home_pc.",
                "confidence": 0.85,
                "warnings": ["Battery is low."],
                "weight": "heavy",
                "is_move": True,
            },
            {
                "lab_id": "lab-a",
                "vm_id": "vm-2",
                "current_host": "laptop-1",
                "target_host": "laptop-1",
                "reason": "Stays put.",
                "confidence": 0.8,
                "warnings": [],
                "weight": "light",
                "is_move": False,
            },
        ],
        "dry_run": True,
    },
    "Battery": {
        "battery": {
            "available": True,
            "percent": 18,
            "status": "discharging",
            "charging": False,
            "tier": "offload",
            "thresholds": {"eco": 60, "offload": 30, "emergency": 15, "critical": 5},
        },
        "actions": [
            {"kind": "reduce_refresh", "reason": "Lower refresh.", "prepared": True, "execute": False},
            {"kind": "prepare_teleport", "reason": "Prepare teleport.", "prepared": True, "execute": False},
        ],
    },
    "NAS": {
        "health": {
            "nas_root": "/mnt/nas",
            "exists": True,
            "readable": True,
            "writable": True,
            "free_mib": 1048576,
            "ok": True,
            "last_commit": {"lab_id": "lab-a", "created_at": "2026-06-01T10:00:00+00:00"},
        },
        "commits": [
            {
                "lab_id": "lab-a",
                "commit_id": "commit-1",
                "created_at": "2026-06-01T10:00:00+00:00",
                "files": [{"path": "lab_manifest.json", "size_bytes": 120}],
                "include_disks": False,
            }
        ],
    },
    "Network": {
        "networks": [
            {
                "id": "hg-net-lab-a",
                "lab_id": "lab-a",
                "name": "lab-a-net",
                "cidr": "10.0.0.0/24",
                "mode": "nat",
                "gateway": "10.0.0.1",
                "isolated": False,
            }
        ],
        "validation": {"ok": True, "errors": [], "warnings": [], "events": []},
    },
    "Guests": {
        "users": [
            {
                "id": "ana",
                "name": "Ana",
                "role": "Operator",
                "assigned_labs": ["lab-a"],
                "extra_permissions": [],
                "effective_permissions": ["can_view_labs", "can_start_vm"],
            }
        ]
    },
    "External Nodes": {
        "nodes": [
            {
                "id": "isard-1",
                "name": "Isard",
                "type": "isard",
                "address": "http://isard.local",
                "status": "online",
                "capabilities": ["can_run_vms"],
                "ram_mib": 32768,
                "health": {"node_id": "isard-1", "type": "isard", "reachable": True, "status": "online"},
            }
        ]
    },
    "Dashboard": {
        "hosts": [
            {
                "id": "home-pc",
                "name": "PC de casa",
                "status": "online",
                "ram_total_mib": 32768,
                "ram_free_mib": 20480,
                "last_seen": "2026-06-10T10:00:00+00:00",
                "tags": ["hub"],
            },
            {
                "id": "laptop-1",
                "name": "Portátil",
                "status": "offline",
                "ram_total_mib": 16384,
                "ram_free_mib": 0,
                "last_seen": "2026-06-09T22:00:00+00:00",
                "tags": [],
            },
        ],
        "local_telemetry": {"cpu_percent": 12.0, "ram_free_mib": 20480},
        "alerts": [
            {"severity": "warning", "kind": "host_offline", "message": "Portátil sin señal."}
        ],
        "vms_total": 5,
        "vms_by_state": {"running": 2, "shut off": 3},
        "battery": {"available": True, "percent": 64, "charging": False, "tier": "normal"},
    },
    "Progress": {
        "operations": [
            {
                "operation_id": "op-1",
                "kind": "live_migration",
                "status": "running",
                "phase": "pre-copy",
                "percent": 41.5,
                "message": "Copiando memoria…",
                "error": "",
                "updated_at": "2026-06-10T10:00:05+00:00",
            },
            {
                "operation_id": "op-2",
                "kind": "backup_verify",
                "status": "failed",
                "phase": "boot",
                "percent": 80.0,
                "message": "",
                "error": "La VM temporal no arrancó.",
                "updated_at": "2026-06-10T09:55:00+00:00",
            },
        ]
    },
    "Logs": {
        "events": [
            {
                "timestamp": "2026-06-01T10:00:00+00:00",
                "level": "info",
                "category": "nas",
                "message": "NAS commit done.",
            },
            {
                "timestamp": "2026-06-01T10:01:00+00:00",
                "level": "error",
                "category": "teleport",
                "message": "Teleport failed.",
            },
        ]
    },
}

ERROR_ENVELOPE = {"ok": False, "data": None, "error": {"code": "E_TEST", "message": "Algo falló"}}


@pytest.mark.parametrize("section", v1_render.supported_sections())
def test_realistic_dict_returns_widget(qt_app, section):
    widget = v1_render.build_v1_widget(section, REALISTIC[section])
    assert isinstance(widget, QWidget)


@pytest.mark.parametrize("section", v1_render.supported_sections())
def test_empty_dict_returns_widget(qt_app, section):
    widget = v1_render.build_v1_widget(section, {})
    assert isinstance(widget, QWidget)


@pytest.mark.parametrize("section", v1_render.supported_sections())
def test_none_returns_widget(qt_app, section):
    widget = v1_render.build_v1_widget(section, None)
    assert isinstance(widget, QWidget)


@pytest.mark.parametrize("section", v1_render.supported_sections())
def test_error_envelope_returns_widget(qt_app, section):
    widget = v1_render.build_v1_widget(section, dict(ERROR_ENVELOPE))
    assert isinstance(widget, QWidget)


def test_short_error_envelope(qt_app):
    widget = v1_render.build_v1_widget("Telemetry", {"ok": False, "error": "x"})
    assert isinstance(widget, QWidget)


def test_unknown_section_falls_back(qt_app):
    widget = v1_render.build_v1_widget("does-not-exist", {"foo": "bar"})
    assert isinstance(widget, QWidget)


def test_render_fallback_never_raises(qt_app):
    for value in (None, 123, "text", [1, 2, 3], {"nested": {"a": 1}}, object()):
        assert isinstance(v1_render.render_fallback(value), QWidget)


@pytest.mark.parametrize("section", v1_render.supported_sections())
def test_wrong_types_in_payload(qt_app, section):
    # Cada clave esperada lleva un tipo equivocado: no debe lanzar.
    junk = {
        "local": 5,
        "alerts": "nope",
        "plans": {"bad": 1},
        "battery": [1, 2],
        "actions": 9,
        "health": "x",
        "commits": None,
        "networks": 7,
        "validation": [],
        "users": "x",
        "nodes": 3,
        "events": {"bad": True},
    }
    widget = v1_render.build_v1_widget(section, junk)
    assert isinstance(widget, QWidget)


def test_api_envelope_unwrapped(qt_app):
    # El builder debe aceptar también el envelope ok=True envolviendo el data.
    envelope = {"ok": True, "data": REALISTIC["Battery"], "error": None}
    widget = v1_render.build_v1_widget("Battery", envelope)
    assert isinstance(widget, QWidget)


def test_dashboard_and_progress_are_humanized_not_raw_json(qt_app):
    """HG-BUG-0022: las secciones nuevas renderizan tarjetas/tablas, nunca el
    QTextEdit del fallback JSON."""
    from PySide6.QtWidgets import QTextEdit

    for section in ("Dashboard", "Progress"):
        widget = v1_render.build_v1_widget(section, REALISTIC[section])
        assert isinstance(widget, QWidget)
        assert not widget.findChildren(QTextEdit), f"{section} cayó al fallback JSON"
