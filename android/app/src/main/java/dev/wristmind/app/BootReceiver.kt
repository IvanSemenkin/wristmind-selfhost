package dev.wristmind.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (
            intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            val preferences = context.getSharedPreferences("wristmind_service", Context.MODE_PRIVATE)
            if (preferences.getBoolean("bridge_enabled", false)) {
                context.startForegroundService(
                    Intent(context, VoiceAssistantService::class.java)
                        .setAction(VoiceAssistantService.ACTION_START_BRIDGE),
                )
            }
        }
    }
}
