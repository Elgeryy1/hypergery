package com.hypergery.companion.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.hypergery.companion.AppViewModel

@Composable
fun AppNavigation(viewModel: AppViewModel) {
    val navController = rememberNavController()
    val state by viewModel.state.collectAsState()
    val start = if (state.paired) "dashboard" else "pairing"

    NavHost(navController = navController, startDestination = start) {
        composable("pairing") {
            PairingScreen(viewModel) {
                navController.navigate("dashboard") { popUpTo("pairing") { inclusive = true } }
            }
        }
        composable("dashboard") {
            DashboardScreen(
                viewModel,
                onOpenVms = { navController.navigate("vms") },
                onUnpair = {
                    viewModel.unpair()
                    navController.navigate("pairing") { popUpTo("dashboard") { inclusive = true } }
                },
            )
        }
        composable("vms") {
            VmListScreen(viewModel, onBack = { navController.popBackStack() })
        }
    }
}
