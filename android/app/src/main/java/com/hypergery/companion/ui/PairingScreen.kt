package com.hypergery.companion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.hypergery.companion.AppViewModel

@Composable
fun PairingScreen(viewModel: AppViewModel, onPaired: () -> Unit) {
    val state by viewModel.state.collectAsState()
    var url by remember { mutableStateOf("http://") }
    var token by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("HyperGery", style = MaterialTheme.typography.headlineLarge)
        Text(
            "Parear con el Hub: ejecuta `hypergery-cli hub pairing-info` en el PC " +
                "y copia la URL del API v1 y el token. Conéctate por VPN/WireGuard/Tailscale.",
            style = MaterialTheme.typography.bodyMedium,
        )
        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("URL del API (http://100.x.y.z:8799)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("Token (secreto)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
        )
        if (state.error.isNotEmpty()) {
            Text(state.error, color = MaterialTheme.colorScheme.error)
        }
        if (state.loading) {
            CircularProgressIndicator()
        } else {
            Button(
                onClick = { viewModel.pair(url, token, onPaired) },
                enabled = url.length > 8 && token.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Parear")
            }
        }
    }
}
