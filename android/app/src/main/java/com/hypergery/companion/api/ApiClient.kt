package com.hypergery.companion.api

import com.hypergery.companion.data.DashboardInfo
import com.hypergery.companion.data.Envelope
import com.hypergery.companion.data.Parsers
import com.hypergery.companion.data.ProgressInfo
import com.hypergery.companion.data.VmInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ApiException(message: String, val statusCode: Int = 0) : Exception(message)

/**
 * Cliente del API v1 de HyperGery (token bearer obligatorio).
 *
 * Solo expone las acciones SEGURAS del companion: start, ACPI shutdown y
 * snapshot con confirmación. Nada destructivo.
 */
class ApiClient(baseUrl: String, private val token: String) {

    private val base = baseUrl.trimEnd('/')
    private val json = "application/json".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(70, TimeUnit.SECONDS) // > timeout máximo del long-poll (60s)
        .build()

    private fun request(method: String, path: String, payload: JSONObject? = null): Envelope {
        val builder = Request.Builder()
            .url(base + path)
            .header("Authorization", "Bearer $token")
            .header("Accept", "application/json")
        when (method) {
            "GET" -> builder.get()
            "POST" -> builder.post((payload ?: JSONObject()).toString().toRequestBody(json))
            else -> throw ApiException("Unsupported method $method")
        }
        client.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (response.code == 401) throw ApiException("Token rechazado por el Hub (401).", 401)
            val envelope = try {
                Envelope.parse(body)
            } catch (e: Exception) {
                throw ApiException("Respuesta no válida del API (${response.code}).", response.code)
            }
            if (!envelope.ok) {
                throw ApiException(envelope.error?.message ?: "Error ${response.code}", response.code)
            }
            return envelope
        }
    }

    suspend fun health(): Boolean = withContext(Dispatchers.IO) {
        request("GET", "/health").ok
    }

    suspend fun dashboard(): DashboardInfo = withContext(Dispatchers.IO) {
        val data = request("GET", "/dashboard").data ?: JSONObject()
        Parsers.dashboard(data.optJSONObject("dashboard") ?: JSONObject())
    }

    suspend fun listVms(): List<VmInfo> = withContext(Dispatchers.IO) {
        val data = request("GET", "/vms").data ?: JSONObject()
        val items = data.optJSONArray("vms")
        buildList {
            if (items != null) for (i in 0 until items.length()) add(Parsers.vm(items.getJSONObject(i)))
        }
    }

    suspend fun startVm(vmId: String) = vmAction(vmId, "start")

    suspend fun shutdownVm(vmId: String) = vmAction(vmId, "shutdown")

    suspend fun snapshotVm(vmId: String, snapshotName: String) = withContext(Dispatchers.IO) {
        request(
            "POST",
            "/vms/${encode(vmId)}/snapshot",
            JSONObject().put("confirm", true).put("snapshot_name", snapshotName),
        )
        Unit
    }

    private suspend fun vmAction(vmId: String, action: String) = withContext(Dispatchers.IO) {
        request("POST", "/vms/${encode(vmId)}/$action")
        Unit
    }

    suspend fun activeOperations(): List<ProgressInfo> = withContext(Dispatchers.IO) {
        val data = request("GET", "/progress?active=1").data ?: JSONObject()
        val items = data.optJSONArray("operations")
        buildList {
            if (items != null) for (i in 0 until items.length()) add(Parsers.progress(items.getJSONObject(i)))
        }
    }

    /** Long-poll TD-9: bloquea hasta que la operación avance. */
    suspend fun waitProgress(operationId: String, sinceVersion: Int, timeoutSeconds: Int = 25): ProgressInfo =
        withContext(Dispatchers.IO) {
            val data = request(
                "GET",
                "/progress/${encode(operationId)}?since=$sinceVersion&timeout=$timeoutSeconds",
            ).data ?: JSONObject()
            Parsers.progress(data.optJSONObject("operation") ?: JSONObject())
        }

    private fun encode(value: String): String = java.net.URLEncoder.encode(value, "UTF-8")
}
