package com.hypergery.companion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.hypergery.companion.AppViewModel
import com.hypergery.companion.data.VmInfo

/** Acción que requiere confirmación fuerte antes de tocar la VM. */
private data class PendingAction(val vm: VmInfo, val kind: String)

@Composable
fun VmListScreen(viewModel: AppViewModel, onBack: () -> Unit) {
    val state by viewModel.state.collectAsState()
    var pending by remember { mutableStateOf<PendingAction?>(null) }
    var snapshotName by remember { mutableStateOf("") }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onBack) { Text("Atrás") }
            Button(onClick = { viewModel.refresh() }) { Text("Actualizar") }
        }
        if (state.error.isNotEmpty()) Text(state.error, color = MaterialTheme.colorScheme.error)
        if (state.info.isNotEmpty()) Text(state.info)

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.vms) { vm ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("${vm.id} — ${vm.status}", style = MaterialTheme.typography.titleMedium)
                        Text("Host: ${vm.hostId.ifBlank { "local" }}  Lab: ${vm.labId}  ${vm.ramMb} MB / ${vm.cpu} vCPU")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            val running = vm.status.contains("run")
                            Button(
                                onClick = { pending = PendingAction(vm, "start") },
                                enabled = !running,
                            ) { Text("Arrancar") }
                            Button(
                                onClick = { pending = PendingAction(vm, "shutdown") },
                                enabled = running,
                            ) { Text("Apagar (ACPI)") }
                            OutlinedButton(onClick = { pending = PendingAction(vm, "snapshot") }) {
                                Text("Snapshot")
                            }
                        }
                    }
                }
            }
        }
    }

    pending?.let { action ->
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("Confirmar ${action.kind} de ${action.vm.id}") },
            text = {
                when (action.kind) {
                    "snapshot" -> Column {
                        Text("Crea un snapshot de la VM. Elige un nombre:")
                        OutlinedTextField(
                            value = snapshotName,
                            onValueChange = { snapshotName = it },
                            label = { Text("Nombre del snapshot") },
                            singleLine = true,
                        )
                    }
                    "shutdown" -> Text("Se enviará un apagado ACPI (ordenado). La VM puede ignorarlo si no tiene SO.")
                    else -> Text("Se arrancará la VM en su host.")
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        when (action.kind) {
                            "start" -> viewModel.startVm(action.vm.id)
                            "shutdown" -> viewModel.shutdownVm(action.vm.id)
                            "snapshot" -> if (snapshotName.isNotBlank()) {
                                viewModel.snapshotVm(action.vm.id, snapshotName.trim())
                            }
                        }
                        pending = null
                        snapshotName = ""
                    },
                ) { Text("Confirmar") }
            },
            dismissButton = { TextButton(onClick = { pending = null }) { Text("Cancelar") } },
        )
    }
}
