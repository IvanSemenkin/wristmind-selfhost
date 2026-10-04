package dev.wristmind.wear

import android.content.Context
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.flow.MutableSharedFlow

/** Keeps FCM payloads metadata-only and lets the normal authenticated API load fresh state. */
object WearPushEvents {
    val syncRequested = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val tokenReceived = MutableSharedFlow<String>(extraBufferCapacity = 1)
}

class WearPushService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        if (message.data[EVENT_KEY] != STATE_CHANGED) return
        WearPushStore(this).markSyncPending()
        WearPushEvents.syncRequested.tryEmit(Unit)
    }

    override fun onNewToken(token: String) {
        WearPushStore(this).saveToken(token)
        WearPushEvents.tokenReceived.tryEmit(token)
    }

    private companion object {
        const val EVENT_KEY = "event"
        const val STATE_CHANGED = "state_changed"
    }
}

class WearPushStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    fun saveToken(token: String) = preferences.edit().putString(KEY_TOKEN, token).apply()
    fun token(): String = preferences.getString(KEY_TOKEN, "").orEmpty()
    fun markSyncPending() = preferences.edit().putBoolean(KEY_SYNC_PENDING, true).apply()
    fun consumeSyncPending(): Boolean {
        val pending = preferences.getBoolean(KEY_SYNC_PENDING, false)
        if (pending) preferences.edit().remove(KEY_SYNC_PENDING).apply()
        return pending
    }

    private companion object {
        const val PREFERENCES = "wear_push"
        const val KEY_TOKEN = "fcm_token"
        const val KEY_SYNC_PENDING = "sync_pending"
    }
}
