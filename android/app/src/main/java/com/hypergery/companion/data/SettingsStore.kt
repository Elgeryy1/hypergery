package com.hypergery.companion.data

import android.content.Context

/** Pareado: URL del Hub + token (secreto) en SharedPreferences privadas. */
class SettingsStore(context: Context) {

    private val prefs = context.getSharedPreferences("hypergery", Context.MODE_PRIVATE)

    var hubUrl: String
        get() = prefs.getString("hub_url", "") ?: ""
        set(value) = prefs.edit().putString("hub_url", value.trim().trimEnd('/')).apply()

    var apiToken: String
        get() = prefs.getString("api_token", "") ?: ""
        set(value) = prefs.edit().putString("api_token", value.trim()).apply()

    val isPaired: Boolean get() = hubUrl.isNotBlank() && apiToken.isNotBlank()

    fun clear() = prefs.edit().clear().apply()

    /** Acepta un pair_uri de `hypergery-cli hub pairing-info`:
     *  hypergery://pair?url=<hubUrl>&token=<token> */
    fun applyPairUri(uri: String): Boolean {
        if (!uri.startsWith("hypergery://pair?")) return false
        val params = uri.substringAfter('?').split('&').mapNotNull {
            val (key, _, value) = it.partition3()
            if (key.isEmpty() || value.isEmpty()) null else key to java.net.URLDecoder.decode(value, "UTF-8")
        }.toMap()
        val url = params["url"] ?: return false
        val token = params["token"] ?: return false
        hubUrl = url
        apiToken = token
        return true
    }
}

private fun String.partition3(): Triple<String, String, String> {
    val index = indexOf('=')
    return if (index < 0) Triple(this, "", "") else Triple(take(index), "=", substring(index + 1))
}
