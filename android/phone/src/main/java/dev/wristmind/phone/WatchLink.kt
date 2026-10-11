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

/** Point-to-point setup: do not broadcast a new device token to every paired watch. */
suspend fun WatchLink.configure(context: android.content.Context, serverUrl: String, token: String, nonce: String) {
    val nodes = Wearable.getCapabilityClient(context)
        .getCapability(WatchLink.CAPABILITY, CapabilityClient.FILTER_REACHABLE).await().nodes
    require(nodes.size == 1) {
        if (nodes.isEmpty()) "Откройте WristMind на часах. Проверьте сопряжение с телефоном в приложении производителя и повторите передачу настроек."
        else "Подключено несколько часов. Оставьте доступными только устанавливаемые часы и повторите."
    }
    val node = nodes.single()
    val client = Wearable.getMessageClient(context)
    val id = java.util.UUID.randomUUID().toString()
    val probeId = java.util.UUID.randomUUID().toString()
    val ready = kotlinx.coroutines.CompletableDeferred<Boolean>()
    val reply = kotlinx.coroutines.CompletableDeferred<Boolean>()
    val listener = com.google.android.gms.wearable.MessageClient.OnMessageReceivedListener { event ->
        if (event.sourceNodeId == node.id && event.path == INSTALL_ACK_PATH) {
            runCatching { org.json.JSONObject(event.data.decodeToString()) }.getOrNull()?.let {
                if (it.optString("request_id") == probeId) ready.complete(it.optBoolean("ready"))
                if (it.optString("request_id") == id) reply.complete(it.optBoolean("ok"))
            }
        }
    }
    client.addListener(listener).await()
    try {
        client.sendMessage(node.id, "/wristmind/install/probe/v1", org.json.JSONObject()
            .put("request_id", probeId).put("nonce", nonce).toString().toByteArray()).await()
        require(kotlinx.coroutines.withTimeout(15000) { ready.await() }) {
            "Часы в ADB и часы, сопряжённые с телефоном, не совпадают либо требуют обновления. Настройки не отправлены."
        }
        val data = org.json.JSONObject().put("nonce", nonce).put("request_id", id).put("server_url", serverUrl)
            .put("device_token", token).toString().toByteArray()
        client.sendMessage(node.id, INSTALL_CONFIG_PATH, data).await()
        require(kotlinx.coroutines.withTimeout(30000) { reply.await() }) {
            "Настройки переданы, но часы не подтвердили доступ к серверу. Проверьте интернет часов и повторите."
        }
    } finally { client.removeListener(listener).await() }
}

const val INSTALL_CONFIG_PATH = "/wristmind/install/config/v1"
const val INSTALL_ACK_PATH = "/wristmind/install/ack/v1"
