"""Tests del módulo de resúmenes en español del Centro de control.

Funciones puras: no necesitan Qt ni servicios reales.
"""

import unittest

from hypergery_ubuntu.ui_qt.humanize import (
    V1_TAB_TITLES,
    humanize_activity_log,
    humanize_command_message,
    humanize_command_status,
    humanize_command_type,
    humanize_command_value,
    humanize_error,
    humanize_error_message,
    humanize_lab_action,
    humanize_network_label,
    humanize_v1,
    humanize_vm_status,
)


class HumanizeTitlesTest(unittest.TestCase):
    def test_all_v1_keys_have_spanish_titles(self):
        expected_keys = {
            "Dashboard",
            "Progress",
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


class HumanizeVmStatusTest(unittest.TestCase):
    def test_table_style_uses_uppercase_spanish(self):
        self.assertEqual(humanize_vm_status("shut off", "table"), "APAGADA")
        self.assertEqual(humanize_vm_status("shutoff", "table"), "APAGADA")
        self.assertEqual(humanize_vm_status("running", "table"), "ENCENDIDA")
        self.assertEqual(humanize_vm_status("paused", "table"), "EN PAUSA")
        self.assertEqual(humanize_vm_status("not created", "table"), "NO CREADA")
        self.assertEqual(humanize_vm_status("unknown", "table"), "DESCONOCIDA")

    def test_detail_style_uses_capitalized_spanish(self):
        self.assertEqual(humanize_vm_status("shut off"), "Apagada")
        self.assertEqual(humanize_vm_status("running"), "Encendida")
        self.assertEqual(humanize_vm_status("paused"), "En pausa")
        self.assertEqual(humanize_vm_status("unknown"), "Desconocida")

    def test_libvirt_variants_and_empty_values(self):
        # Los valores internos de libvirt no se modifican: esto solo presenta.
        self.assertEqual(humanize_vm_status("in shutdown running"), "Encendida")
        self.assertEqual(humanize_vm_status(""), "Desconocida")
        self.assertEqual(humanize_vm_status(None), "Desconocida")


class HumanizeCommandStatusTest(unittest.TestCase):
    def test_known_statuses(self):
        self.assertEqual(humanize_command_status("pending"), "PENDIENTE")
        self.assertEqual(humanize_command_status("running"), "EN CURSO")
        self.assertEqual(humanize_command_status("done"), "COMPLETADA")
        self.assertEqual(humanize_command_status("failed"), "FALLÓ")
        self.assertEqual(humanize_command_status("done", "detail"), "Completada")

    def test_unknown_status_passes_through_uppercased(self):
        self.assertEqual(humanize_command_status("weird"), "WEIRD")
        self.assertEqual(humanize_command_status(""), "DESCONOCIDA")


class HumanizeLabActionTest(unittest.TestCase):
    def test_actions_in_spanish(self):
        self.assertEqual(humanize_lab_action("start"), "arranque")
        self.assertEqual(humanize_lab_action("shutdown"), "apagado")
        self.assertEqual(humanize_lab_action("otra"), "otra")


class HumanizeNetworkLabelTest(unittest.TestCase):
    def test_network_jargon_in_spanish(self):
        self.assertEqual(humanize_network_label("subnet"), "Subred")
        self.assertEqual(humanize_network_label("bridge"), "Puente")
        self.assertEqual(humanize_network_label("unknown"), "desconocido")
        self.assertEqual(humanize_network_label("nat"), "NAT")


class HumanizeErrorMessageTest(unittest.TestCase):
    def test_missing_iso_english_marker(self):
        error = (
            "virsh --connect qemu:///system start ubuntu-test-v07 failed: "
            "error: Failed to start domain 'ubuntu-test-v07'\n"
            "error: Cannot access storage file "
            "'/mnt/hypergery-nas/ubuntu-26.04-live-server-amd64.iso': "
            "No such file or directory"
        )
        human = humanize_error_message(error)
        self.assertIn("falta la ISO ubuntu-26.04-live-server-amd64.iso", human)
        self.assertIn("Qué puedes hacer", human)
        self.assertIn("NAS está montado", human)
        self.assertIn("Detalle técnico:", human)
        # El detalle técnico no se pierde, pero va al final.
        self.assertLess(human.index("falta la ISO"), human.index("virsh"))

    def test_missing_file_spanish_marker(self):
        error = (
            "Failed to start domain: no se puede acceder al archivo almacén "
            "'/home/gerard/NAS_Gerard/disco.qcow2': No existe el archivo o el directorio"
        )
        human = humanize_error_message(error)
        self.assertIn("falta un archivo de disco (disco.qcow2)", human)
        self.assertIn("Detalle técnico:", human)

    def test_technical_start_error_without_path_gets_generic_summary(self):
        error = "virsh --connect qemu:///system start vm1 failed: error: Failed to start domain 'vm1'"
        human = humanize_error_message(error)
        self.assertTrue(human.startswith("No se pudo completar la operación"))
        self.assertIn("Detalle técnico:", human)
        self.assertNotIn("Traceback", human)

    def test_plain_spanish_message_passes_through_unchanged(self):
        message = "Selecciona una máquina primero."
        self.assertEqual(humanize_error_message(message), message)
        self.assertEqual(humanize_error_message(""), "")


class HumanizeCommandTypeTest(unittest.TestCase):
    def test_known_command_types_in_spanish(self):
        self.assertEqual(humanize_command_type("vm_start"), "Encender máquina")
        self.assertEqual(humanize_command_type("vm_shutdown"), "Apagar máquina")
        self.assertEqual(humanize_command_type("vm_force_off"), "Apagado forzado")
        self.assertEqual(humanize_command_type("import_vm_package"), "Importar máquina")
        self.assertEqual(humanize_command_type("receive_vm_package"), "Recibir máquina")
        self.assertEqual(humanize_command_type("ping"), "Comprobar equipo")
        self.assertEqual(humanize_command_type("migration_status"), "Estado del traslado")
        self.assertEqual(humanize_command_type("restore_vm_state_package"), "Reanudar máquina trasladada")

    def test_unknown_type_passes_through(self):
        # Los command_type internos nunca se inventan ni se modifican.
        self.assertEqual(humanize_command_type("weird_command"), "weird_command")
        self.assertEqual(humanize_command_type(""), "")
        self.assertEqual(humanize_command_type(None), "")


class HumanizeCommandMessageTest(unittest.TestCase):
    def test_executed_message_with_states(self):
        human = humanize_command_message("start executed on ubuntu (shut off -> running).")
        self.assertEqual(human, "Encendido ejecutado en ubuntu (antes apagada, ahora encendida)")

    def test_executed_message_other_actions(self):
        self.assertEqual(
            humanize_command_message("shutdown executed on web-01 (running -> shut off)."),
            "Apagado ejecutado en web-01 (antes encendida, ahora apagada)",
        )
        self.assertTrue(
            humanize_command_message("force off executed on web-01 (running -> shut off).").startswith(
                "Apagado forzado ejecutado en web-01"
            )
        )

    def test_backend_failed_to_start(self):
        human = humanize_command_message("Backend failed to start ubuntu: boom")
        self.assertIn("No se pudo encender la máquina ubuntu", human)
        self.assertIn("boom", human)

    def test_cannot_action_due_to_state(self):
        human = humanize_command_message(
            "Cannot start ubuntu: VM state is 'running'. Allowed states: shut off, shutoff."
        )
        self.assertEqual(human, "No se puede encender la máquina ubuntu: ahora mismo está encendida")

    def test_target_vm_already_exists(self):
        self.assertEqual(
            humanize_command_message("Target VM already exists: ubuntu-migrated"),
            "La máquina de destino ya existe: ubuntu-migrated",
        )
        self.assertEqual(
            humanize_command_message("Target VM name already exists locally: ubuntu-migrated"),
            "La máquina de destino ya existe en ese equipo: ubuntu-migrated",
        )

    def test_unknown_message_passes_through(self):
        self.assertEqual(humanize_command_message("hola"), "hola")
        self.assertEqual(humanize_command_message(""), "")


class HumanizeCommandValueTest(unittest.TestCase):
    def test_dict_with_message_is_translated(self):
        value = {
            "vm_name": "ubuntu",
            "message": "start executed on ubuntu (shut off -> running).",
        }
        self.assertIn("Encendido ejecutado en ubuntu", humanize_command_value(value))

    def test_dict_with_error_is_translated(self):
        value = {"error": "Backend failed to start ubuntu: boom"}
        self.assertIn("No se pudo encender la máquina ubuntu", humanize_command_value(value))

    def test_ping_result(self):
        self.assertEqual(
            humanize_command_value({"pong": True, "host_id": "gerard-MS-7E26"}),
            "El equipo gerard-MS-7E26 responde",
        )

    def test_payload_fields_without_json_braces(self):
        text = humanize_command_value({"vm_name": "ubuntu"})
        self.assertEqual(text, "máquina: ubuntu")
        self.assertNotIn("{", text)

    def test_opaque_dict_points_to_technical_detail(self):
        text = humanize_command_value({"items": [1, 2, 3]})
        self.assertIn("Detalle técnico", text)
        self.assertNotIn("{", text)


class HumanizeActivityLogTest(unittest.TestCase):
    QEMU_IMG_BLOCK = (
        "2026-06-07 20:21:59,887 INFO run: qemu-img info --output=json /tmp/ubuntu.qcow2\n"
        "2026-06-07 20:21:59,890 INFO stdout: {\n"
        '    "virtual-size": 42949672960,\n'
        '    "filename": "/tmp/ubuntu.qcow2",\n'
        '    "format": "qcow2",\n'
        '    "actual-size": 5793210368,\n'
        '    "dirty-flag": false\n'
        "}\n"
        "2026-06-07 20:22:00,100 INFO run: virsh --connect qemu:///system domstate ubuntu"
    )

    def test_qemu_img_json_collapses_to_spanish_summary(self):
        human = humanize_activity_log(self.QEMU_IMG_BLOCK)
        self.assertNotIn("dirty-flag", human)
        self.assertIn("sin cambios pendientes", human)
        self.assertIn("ubuntu.qcow2", human)
        self.assertIn("qcow2", human)
        # Las líneas normales no se tocan.
        self.assertIn("run: qemu-img info", human)
        self.assertIn("run: virsh --connect", human)

    def test_dirty_disk_is_flagged(self):
        text = '2026-06-07 10:00:00,000 INFO stdout: {"filename": "/x/a.qcow2", "format": "qcow2", "dirty-flag": true}'
        human = humanize_activity_log(text)
        self.assertIn("cambios pendientes: sí", human)

    def test_xml_dump_collapses_to_one_line(self):
        text = (
            "2026-06-07 10:00:00,000 INFO stdout: <domain type='kvm'>\n"
            "  <name>ubuntu</name>\n"
            "</domain>"
        )
        human = humanize_activity_log(text)
        self.assertNotIn("<domain", human)
        self.assertIn("Configuración de «ubuntu» leída (XML)", human)

    def test_plain_lines_are_untouched(self):
        text = (
            "2026-06-07 10:00:00,000 INFO run: virsh --connect qemu:///system domstate ubuntu\n"
            "2026-06-07 10:00:00,010 INFO stdout: shut off\n"
            "2026-06-07 10:00:00,020 INFO Creado laboratorio default-lab"
        )
        self.assertEqual(humanize_activity_log(text), text)

    def test_empty_log(self):
        self.assertEqual(humanize_activity_log(""), "")
        self.assertEqual(humanize_activity_log(None), "")


if __name__ == "__main__":
    unittest.main()
