package com.hypergery.companion.data

import org.json.JSONObject

/** Modelos + parsing del sobre del API v1: {ok, data, error, timestamp}. */

data class ApiError(val code: String, val message: String)

data class Envelope(val ok: Boolean, val data: JSONObject?, val error: ApiError?) {
    companion object {
        fun parse(body: String): Envelope {
            val json = JSONObject(body)
            val error = json.optJSONObject("error")?.let {
                ApiError(it.optString("code", "error"), it.optString("message", ""))
            }
            return Envelope(json.optBoolean("ok", false), json.optJSONObject("data"), error)
        }
    }
}

data class HostInfo(
    val id: String,
    val name: String,
    val status: String,
    val ramFreeMib: Long,
    val ramTotalMib: Long,
)

data class VmInfo(
    val id: String,
    val status: String,
    val hostId: String,
    val labId: String,
    val ramMb: Long,
    val cpu: Int,
)

data class DashboardInfo(
    val hosts: List<HostInfo>,
    val vmsTotal: Int,
    val vmsByState: Map<String, Int>,
    val alerts: List<String>,
    val batteryPercent: Int?,
)

data class ProgressInfo(
    val operationId: String,
    val kind: String,
    val status: String,
    val phase: String,
    val percent: Double,
    val message: String,
    val version: Int,
)

object Parsers {
    fun host(json: JSONObject): HostInfo = HostInfo(
        id = json.optString("id", json.optString("host_id", "?")),
        name = json.optString("name", ""),
        status = json.optString("status", "unknown"),
        ramFreeMib = json.optLong("ram_free_mib", 0),
        ramTotalMib = json.optLong("ram_total_mib", 0),
    )

    fun vm(json: JSONObject): VmInfo = VmInfo(
        id = json.optString("id", json.optString("vm_name", "?")),
        status = json.optString("status", json.optString("state", "unknown")),
        hostId = json.optString("host_id", ""),
        labId = json.optString("lab_id", ""),
        ramMb = json.optLong("ram_mb", json.optLong("ram_mib", 0)),
        cpu = json.optInt("cpu", json.optInt("vcpus", 0)),
    )

    fun dashboard(json: JSONObject): DashboardInfo {
        val hostsJson = json.optJSONArray("hosts")
        val hosts = buildList {
            if (hostsJson != null) for (i in 0 until hostsJson.length()) add(host(hostsJson.getJSONObject(i)))
        }
        val byState = mutableMapOf<String, Int>()
        json.optJSONObject("vms_by_state")?.let { states ->
            for (key in states.keys()) byState[key] = states.optInt(key, 0)
        }
        val alertsJson = json.optJSONArray("alerts")
        val alerts = buildList {
            if (alertsJson != null) for (i in 0 until alertsJson.length()) {
                val alert = alertsJson.opt(i)
                add(if (alert is JSONObject) alert.optString("message", alert.toString()) else alert.toString())
            }
        }
        val battery = json.optJSONObject("battery")
        val percent = battery?.let { if (it.has("percent") && !it.isNull("percent")) it.optInt("percent") else null }
        return DashboardInfo(
            hosts = hosts,
            vmsTotal = json.optInt("vms_total", 0),
            vmsByState = byState,
            alerts = alerts,
            batteryPercent = percent,
        )
    }

    fun progress(json: JSONObject): ProgressInfo = ProgressInfo(
        operationId = json.optString("operation_id", ""),
        kind = json.optString("kind", ""),
        status = json.optString("status", ""),
        phase = json.optString("phase", ""),
        percent = json.optDouble("percent", 0.0),
        message = json.optString("message", ""),
        version = json.optInt("version", 0),
    )
}
