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
import kotlinx.coroutines.flow.MutableSharedFlow

object WearConfigEvents {
    val tokenReceived = MutableSharedFlow<DeviceConfig>(extraBufferCapacity = 1)
}

class WearConfigService : WearableListenerService() {
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
