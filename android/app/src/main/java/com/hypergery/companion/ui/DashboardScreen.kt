package com.hypergery.companion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.hypergery.companion.AppViewModel

@Composable
fun DashboardScreen(viewModel: AppViewModel, onOpenVms: () -> Unit, onUnpair: () -> Unit) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(Unit) { viewModel.refresh() }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { viewModel.refresh() }) { Text("Actualizar") }
            Button(onClick = onOpenVms) { Text("Máquinas (${state.vms.size})") }
            OutlinedButton(onClick = onUnpair) { Text("Desparear") }
        }
        if (state.error.isNotEmpty()) Text(state.error, color = MaterialTheme.colorScheme.error)
        if (state.info.isNotEmpty()) Text(state.info)

        val dashboard = state.dashboard
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (dashboard != null) {
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("Estado", style = MaterialTheme.typography.titleMedium)
                            Text("VMs: ${dashboard.vmsTotal}  " +
                                dashboard.vmsByState.entries.joinToString { "${it.key}=${it.value}" })
                            dashboard.batteryPercent?.let { Text("Batería: $it%") }
                        }
                    }
                }
                items(dashboard.hosts) { host ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("${host.name.ifBlank { host.id }} — ${host.status}")
                            if (host.ramTotalMib > 0) {
                                Text("RAM libre: ${host.ramFreeMib}/${host.ramTotalMib} MiB")
                            }
                        }
                    }
                }
                items(dashboard.alerts) { alert ->
                    Text("⚠ $alert", color = MaterialTheme.colorScheme.error)
                }
            }
            items(state.operations) { op ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${op.kind}: ${op.phase} — ${op.status}")
                        LinearProgressIndicator(
                            progress = { (op.percent / 100.0).toFloat() },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (op.message.isNotEmpty()) Text(op.message, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}
