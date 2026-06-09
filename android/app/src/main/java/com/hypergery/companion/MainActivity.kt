package com.hypergery.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.hypergery.companion.data.SettingsStore
import com.hypergery.companion.ui.AppNavigation

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val settings = SettingsStore(applicationContext)
        val factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = AppViewModel(settings) as T
        }
        val viewModel = ViewModelProvider(this, factory)[AppViewModel::class.java]
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface {
                    AppNavigation(viewModel)
                }
            }
        }
    }
}
