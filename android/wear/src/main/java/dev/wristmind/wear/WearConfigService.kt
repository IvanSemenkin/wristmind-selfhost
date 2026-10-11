package dev.wristmind.wear

import android.content.Context
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import dev.wristmind.core.DeviceConfig
import dev.wristmind.core.DeviceConfigStore
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.launch
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow

object WearConfigEvents {
    val tokenReceived = MutableSharedFlow<DeviceConfig>(extraBufferCapacity = 1)
}

class WearConfigService : WearableListenerService() {
    private val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO)

    override fun onMessageReceived(event: com.google.android.gms.wearable.MessageEvent) {
        if (event.path !in setOf("/wristmind/install/config/v1", "/wristmind/install/probe/v1") || event.data.size > 16384) return
        scope.launch {
            val input = runCatching { org.json.JSONObject(event.data.decodeToString()) }.getOrNull() ?: return@launch
            val id = input.optString("request_id")
            if (!id.matches(Regex("[a-f0-9-]{36}"))) return@launch
            val prefs = getSharedPreferences("wristmind_install", 0)
            val now = android.os.SystemClock.elapsedRealtime()
            val ready = InstallChallenge.accepts(prefs.getString("nonce", ""), input.optString("nonce"), prefs.getLong("expires", 0), now)
            if (event.path == "/wristmind/install/probe/v1") {
                runCatching { Wearable.getMessageClient(this@WearConfigService).sendMessage(event.sourceNodeId,
                    "/wristmind/install/ack/v1", org.json.JSONObject().put("request_id", id).put("ready", ready)
                        .toString().toByteArray()).await() }
                return@launch
            }
            val ok = runCatching {
                require(ready)
                val url = input.getString("server_url")
                val uri = java.net.URI(url)
                require(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.userInfo == null &&
                    uri.query == null && uri.fragment == null && uri.path.orEmpty().trim('/') == "")
                val token = input.getString("device_token")
                require(token.isNotBlank())
                // Verify credentials before replacing any existing watch configuration.
                dev.wristmind.core.WristMindApi(url, token).chats()
                val config = DeviceConfig(url, token)
                synchronized(prefs) {
                    require(InstallChallenge.accepts(prefs.getString("nonce", ""), input.optString("nonce"),
                        prefs.getLong("expires", 0), android.os.SystemClock.elapsedRealtime()))
                    DeviceConfigStore(this@WearConfigService, "watch").save(config)
                    prefs.edit().remove("nonce").remove("expires").apply()
                }
                WearConfigEvents.tokenReceived.emit(config)
            }.isSuccess
            runCatching {
                Wearable.getMessageClient(this@WearConfigService).sendMessage(event.sourceNodeId,
                    "/wristmind/install/ack/v1", org.json.JSONObject().put("request_id", id).put("ok", ok)
                        .toString().toByteArray()).await()
            }
        }
    }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        dataEvents.filter { it.type == DataEvent.TYPE_CHANGED && it.dataItem.uri.path == CONFIG_PATH }
            .forEach { event ->
                val data = DataMapItem.fromDataItem(event.dataItem).dataMap
                val incomingToken = data.getString("device_token").orEmpty()
                if (incomingToken.isBlank()) return@forEach
                if (data.getString("origin") != "phone") return@forEach
                val store = DeviceConfigStore(this, "watch")
                val local = store.read(BuildConfig.WRISTMIND_BASE_URL)
                val config = DeviceConfig(data.getString("server_url") ?: BuildConfig.WRISTMIND_BASE_URL, incomingToken)
                if (local != config) {
                    store.save(config)
                    WearConfigEvents.tokenReceived.tryEmit(config)
                }
            }
    }

    companion object { const val CONFIG_PATH = "/wristmind/config/v1" }
}

class WearConfigPublisher(context: Context) {
    private val dataClient = Wearable.getDataClient(context)

    suspend fun publish(serverUrl: String, token: String) {
        val request = PutDataMapRequest.create(WearConfigService.CONFIG_PATH).apply {
            dataMap.putString("server_url", serverUrl.trimEnd('/'))
            dataMap.putString("device_token", token)
            dataMap.putBoolean("paused", false)
            dataMap.putLong("updated_at", System.currentTimeMillis())
            dataMap.putString("origin", "watch")
        }.asPutDataRequest().setUrgent()
        dataClient.putDataItem(request).await()
    }
}
