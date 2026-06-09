package com.hypergery.companion

import com.hypergery.companion.data.Envelope
import com.hypergery.companion.data.Parsers
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ParsersTest {

    @Test
    fun `envelope parses ok payload`() {
        val envelope = Envelope.parse("""{"ok": true, "data": {"x": 1}, "error": null}""")
        assertTrue(envelope.ok)
        assertEquals(1, envelope.data?.optInt("x"))
        assertNull(envelope.error)
    }

    @Test
    fun `envelope parses error payload`() {
        val envelope = Envelope.parse(
            """{"ok": false, "data": null, "error": {"code": "auth_required", "message": "token"}}""",
        )
        assertFalse(envelope.ok)
        assertEquals("auth_required", envelope.error?.code)
    }

    @Test
    fun `vm parser maps v1 fields`() {
        val vm = Parsers.vm(
            JSONObject(
                """{"id": "dc01", "status": "running", "host_id": "pc", "lab_id": "asr-lab",
                    "ram_mb": 2048, "cpu": 2}""",
            ),
        )
        assertEquals("dc01", vm.id)
        assertEquals("running", vm.status)
        assertEquals("asr-lab", vm.labId)
        assertEquals(2048, vm.ramMb)
    }

    @Test
    fun `dashboard parser aggregates`() {
        val dashboard = Parsers.dashboard(
            JSONObject(
                """{"hosts": [{"id": "pc", "status": "online", "ram_free_mib": 8000, "ram_total_mib": 16000}],
                    "vms_total": 3, "vms_by_state": {"running": 2, "shut off": 1},
                    "alerts": [{"message": "RAM baja"}],
                    "battery": {"percent": 76}}""",
            ),
        )
        assertEquals(1, dashboard.hosts.size)
        assertEquals("pc", dashboard.hosts[0].id)
        assertEquals(3, dashboard.vmsTotal)
        assertEquals(2, dashboard.vmsByState["running"])
        assertEquals(listOf("RAM baja"), dashboard.alerts)
        assertEquals(76, dashboard.batteryPercent)
    }

    @Test
    fun `progress parser reads long poll payload`() {
        val progress = Parsers.progress(
            JSONObject(
                """{"operation_id": "op-1", "kind": "live-migration", "status": "running",
                    "phase": "switchover", "percent": 62.5, "message": "Pre-copy", "version": 7}""",
            ),
        )
        assertEquals("op-1", progress.operationId)
        assertEquals("switchover", progress.phase)
        assertEquals(62.5, progress.percent, 0.01)
        assertEquals(7, progress.version)
    }
}
