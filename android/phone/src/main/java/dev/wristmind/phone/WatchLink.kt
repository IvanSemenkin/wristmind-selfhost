package dev.wristmind.phone

import android.content.Context
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await

data class WatchLinkStatus(val reachable: Boolean, val nodeName: String = "Xiaomi Watch 2")

class WatchLink(context: Context) {
    private val capabilityClient = Wearable.getCapabilityClient(context)
    private val dataClient = Wearable.getDataClient(context)

    suspend fun inspect(): WatchLinkStatus {
        val capability = capabilityClient
            .getCapability(CAPABILITY, CapabilityClient.FILTER_REACHABLE)
            .await()
        val node = capability.nodes.firstOrNull()
        return WatchLinkStatus(node != null, node?.displayName ?: "Xiaomi Watch 2")
    }

    suspend fun publishConfig(serverUrl: String, token: String, paused: Boolean) {
        val request = PutDataMapRequest.create(CONFIG_PATH).apply {
            dataMap.putString("server_url", serverUrl.trim().trimEnd('/'))
            dataMap.putString("device_token", token)
            dataMap.putBoolean("paused", paused)
            dataMap.putLong("updated_at", System.currentTimeMillis())
            dataMap.putString("origin", "phone")
        }.asPutDataRequest().setUrgent()
        dataClient.putDataItem(request).await()
    }

    companion object {
        const val CAPABILITY = "wristmind_watch"
        const val CONFIG_PATH = "/wristmind/config/v1"
    }
}
