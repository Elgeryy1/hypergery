package com.hypergery.companion

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hypergery.companion.api.ApiClient
import com.hypergery.companion.api.ApiException
import com.hypergery.companion.data.DashboardInfo
import com.hypergery.companion.data.ProgressInfo
import com.hypergery.companion.data.SettingsStore
import com.hypergery.companion.data.VmInfo
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

data class UiState(
    val paired: Boolean = false,
    val loading: Boolean = false,
    val error: String = "",
    val info: String = "",
    val dashboard: DashboardInfo? = null,
    val vms: List<VmInfo> = emptyList(),
    val operations: List<ProgressInfo> = emptyList(),
)

class AppViewModel(private val settings: SettingsStore) : ViewModel() {

    private val _state = MutableStateFlow(UiState(paired = settings.isPaired))
    val state: StateFlow<UiState> = _state
    private var client: ApiClient? = if (settings.isPaired) ApiClient(settings.hubUrl, settings.apiToken) else null
    private var pollJob: Job? = null

    fun pair(url: String, token: String, onSuccess: () -> Unit) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = "")
            try {
                val candidate = ApiClient(url.trim().trimEnd('/'), token.trim())
                candidate.dashboard() // valida URL + token con una llamada real autenticada
                settings.hubUrl = url
                settings.apiToken = token
                client = candidate
                _state.value = _state.value.copy(paired = true, loading = false)
                refresh()
                onSuccess()
            } catch (e: Exception) {
                _state.value = _state.value.copy(loading = false, error = friendly(e))
            }
        }
    }

    fun unpair() {
        settings.clear()
        client = null
        pollJob?.cancel()
        _state.value = UiState(paired = false)
    }

    fun refresh() {
        val api = client ?: return
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = "")
            try {
                val dashboard = api.dashboard()
                val vms = api.listVms()
                val ops = api.activeOperations()
                _state.value = _state.value.copy(
                    loading = false, dashboard = dashboard, vms = vms, operations = ops,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(loading = false, error = friendly(e))
            }
        }
    }

    fun startVm(vmId: String) = action("Arrancando $vmId…") { it.startVm(vmId) }

    fun shutdownVm(vmId: String) = action("Apagado ACPI de $vmId…") { it.shutdownVm(vmId) }

    fun snapshotVm(vmId: String, name: String) = action("Snapshot $name de $vmId…") { it.snapshotVm(vmId, name) }

    private fun action(label: String, block: suspend (ApiClient) -> Unit) {
        val api = client ?: return
        viewModelScope.launch {
            _state.value = _state.value.copy(info = label, error = "")
            try {
                block(api)
                delay(800)
                refresh()
                _state.value = _state.value.copy(info = "")
            } catch (e: Exception) {
                _state.value = _state.value.copy(info = "", error = friendly(e))
            }
        }
    }

    /** Long-poll de eventos de progreso del Hub (TD-9). */
    fun watchOperation(operationId: String) {
        val api = client ?: return
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            var since = -1
            while (true) {
                try {
                    val op = api.waitProgress(operationId, since)
                    since = op.version
                    _state.value = _state.value.copy(
                        operations = _state.value.operations.filter { it.operationId != op.operationId } + op,
                    )
                    if (op.status != "running") break
                } catch (e: Exception) {
                    _state.value = _state.value.copy(error = friendly(e))
                    break
                }
            }
        }
    }

    private fun friendly(e: Exception): String = when {
        e is ApiException && e.statusCode == 401 -> "Token rechazado: vuelve a parear con el Hub."
        e is ApiException && e.statusCode == 403 -> "Tu usuario no tiene permiso para esa acción."
        else -> e.message ?: "Error de red — ¿VPN/WireGuard activa?"
    }
}
