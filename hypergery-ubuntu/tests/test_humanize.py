"""Tests del módulo de resúmenes en español del Centro de control.

Funciones puras: no necesitan Qt ni servicios reales.
"""

import unittest

from hypergery_ubuntu.ui_qt.humanize import (
    V1_TAB_TITLES,
    humanize_error,
    humanize_v1,
)


class HumanizeTitlesTest(unittest.TestCase):
    def test_all_v1_keys_have_spanish_titles(self):
        expected_keys = {
            "Telemetry",
            "Orchestrator",
            "Battery",
            "NAS",
            "Network",
            "Guests",
            "External Nodes",
            "Logs",
        }
        self.assertEqual(set(V1_TAB_TITLES), expected_keys)


class HumanizeTelemetryTest(unittest.TestCase):
    def test_healthy_host_reads_naturally(self):
        html = humanize_v1(
            "Telemetry",
            {
                "local": {
                    "cpu_percent": 12.0,
                    "ram_total_mib": 32768,
                    "ram_free_mib": 20480,
                    "disk_total_mib": 512000,
                    "disk_free_mib": 256000,
                    "battery_percent": None,
                    "uptime_seconds": 90000,
                },
                "alerts": [],
            },
        )
        self.assertIn("Procesador trabajando al <b>12%</b>", html)
        self.assertIn("20 GiB libres", html)
        self.assertIn("sobremesa", html)
        self.assertIn("Todo en orden", html)
        self.assertIn("1 día", html)

    def test_alerts_are_listed(self):
        html = humanize_v1(
            "Telemetry",
            {
                "local": {"cpu_percent": 95.0},
                "alerts": [{"severity": "warning", "message": "Low RAM: 100 MiB free"}],
            },
        )
        self.assertIn("Avisos", html)
        self.assertIn("Low RAM", html)
        self.assertNotIn("Todo en orden", html)


class HumanizeOrchestratorTest(unittest.TestCase):
    def test_no_moves_is_reassuring(self):
        html = humanize_v1("Orchestrator", {"plans": [], "dry_run": True})
        self.assertIn("están bien donde están", html)
        self.assertIn("solo sugerencias", html)

    def test_move_plan_is_explained(self):
        html = humanize_v1(
            "Orchestrator",
            {
                "plans": [
                    {
                        "vm_id": "web-01",
                        "current_host": "sobremesa",
                        "target_host": "portatil",
                        "reason": "more free RAM",
                        "confidence": 0.8,
                        "is_move": True,
                        "warnings": [],
                    }
                ]
            },
        )
        self.assertIn("web-01", html)
        self.assertIn("portatil", html)
        self.assertIn("80%", html)


class HumanizeBatteryTest(unittest.TestCase):
    def test_no_battery_is_not_alarming(self):
        html = humanize_v1("Battery", {"battery": {"available": False}, "actions": []})
        self.assertIn("no tiene batería", html)

    def test_low_battery_translates_actions(self):
        html = humanize_v1(
            "Battery",
            {
                "battery": {"available": True, "percent": 15, "charging": False, "tier": "emergency"},
                "actions": [{"kind": "nas_commit", "reason": "Battery at 15%"}],
            },
        )
        self.assertIn("15%", html)
        self.assertIn("emergencia", html)
        self.assertIn("copia de los labs en el NAS", html)


class HumanizeNasTest(unittest.TestCase):
    def test_missing_nas_explains_in_plain_words(self):
        html = humanize_v1(
            "NAS",
            {"health": {"ok": False, "exists": False, "nas_root": "/mnt/nas"}, "commits": []},
        )
        self.assertIn("No se encuentra la carpeta del NAS", html)
        self.assertIn("/mnt/nas", html)

    def test_healthy_nas_with_commits(self):
        html = humanize_v1(
            "NAS",
            {
                "health": {
                    "ok": True,
                    "exists": True,
                    "writable": True,
                    "free_mib": 1024000,
                    "last_commit": {"lab_id": "asr-lab", "created_at": "2026-06-05T18:32:00+00:00"},
                },
                "commits": [{"lab_id": "asr-lab", "created_at": "2026-06-05T18:32:00+00:00"}],
            },
        )
        self.assertIn("funciona correctamente", html)
        self.assertIn("asr-lab", html)
        self.assertIn("05/06/2026", html)


class HumanizeNetworkTest(unittest.TestCase):
    def test_networks_listed_with_translated_mode(self):
        html = humanize_v1(
            "Network",
            {
                "networks": [
                    {"id": "hg-net-a", "name": "hg-net-a", "lab_id": "a", "mode": "nat", "cidr": "10.0.0.0/24"}
                ],
                "validation": {"ok": True, "errors": [], "warnings": []},
            },
        )
        self.assertIn("sin conflictos", html)
        self.assertIn("salida a internet", html)
        self.assertIn("10.0.0.0/24", html)


class HumanizeGuestsTest(unittest.TestCase):
    def test_empty_users_is_friendly(self):
        html = humanize_v1("Guests", {"users": []})
        self.assertIn("solo tú", html)

    def test_roles_are_translated(self):
        html = humanize_v1(
            "Guests",
            {"users": [{"name": "ana", "role": "Guest", "assigned_labs": ["asr-lab"]}]},
        )
        self.assertIn("ana", html)
        self.assertIn("Invitado", html)
        self.assertIn("asr-lab", html)


class HumanizeLogsTest(unittest.TestCase):
    def test_events_show_newest_first_with_icons(self):
        html = humanize_v1(
            "Logs",
            {
                "events": [
                    {"timestamp": "2026-06-06T10:00:00+00:00", "level": "info", "category": "nas", "message": "older"},
                    {"timestamp": "2026-06-06T11:00:00+00:00", "level": "error", "category": "network", "message": "newer"},
                ]
            },
        )
        self.assertLess(html.index("newer"), html.index("older"))
        self.assertIn("copias NAS", html)
        self.assertIn("redes", html)


class HumanizeRobustnessTest(unittest.TestCase):
    def test_unknown_key_never_raises(self):
        html = humanize_v1("Nope", {"x": 1})
        self.assertIn("No hay un resumen disponible", html)

    def test_malformed_payload_never_raises(self):
        html = humanize_v1("Telemetry", {"local": "not-a-dict", "alerts": None})
        self.assertIsInstance(html, str)

    def test_error_message_is_escaped_and_in_spanish(self):
        html = humanize_error("NAS", "boom <script>")
        self.assertIn("No se ha podido cargar", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Copias en el NAS", html)


if __name__ == "__main__":
    unittest.main()
