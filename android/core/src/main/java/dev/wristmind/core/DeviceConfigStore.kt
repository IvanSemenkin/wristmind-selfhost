package dev.wristmind.core

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

data class DeviceConfig(val serverUrl: String, val token: String)

class DeviceConfigStore(context: Context, profile: String) {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()
    private val preferences = EncryptedSharedPreferences.create(
        context,
        "wristmind_$profile",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun read(defaultUrl: String): DeviceConfig {
        val savedUrl = preferences.getString("server_url", defaultUrl).orEmpty()
        val serverUrl = if (savedUrl.trim().trimEnd('/') == LEGACY_PUBLIC_URL) {
            defaultUrl.trim().trimEnd('/')
        } else savedUrl
        if (serverUrl != savedUrl) {
            preferences.edit().putString("server_url", serverUrl).apply()
        }
        return DeviceConfig(
            serverUrl = serverUrl,
            token = preferences.getString("device_token", "").orEmpty(),
        )
    }

    fun save(config: DeviceConfig) {
        preferences.edit()
            .putString("server_url", config.serverUrl.trim().trimEnd('/'))
            .putString("device_token", config.token)
            .apply()
    }

    fun clearToken() = preferences.edit().remove("device_token").apply()

    fun fallbackTicket(): String = preferences.getString("fallback_ticket", "").orEmpty()

    fun saveFallbackTicket(ticket: String) {
        preferences.edit().putString("fallback_ticket", ticket).apply()
    }

    fun clearFallbackTicket() = preferences.edit().remove("fallback_ticket").apply()

    private companion object {
        const val LEGACY_PUBLIC_URL = "https://wm.arlienix.space"
    }
}
