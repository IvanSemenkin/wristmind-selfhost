package dev.wristmind.wear

import android.util.Log

/**
 * TEMPORARY latency instrumentation for the "send → first visible token" metric.
 *
 * Contract: log identifiers, timestamps, durations and sizes only. Never log the
 * user question, the assistant answer, prompts, or any other message body.
 *
 * Filter with: adb logcat -s WristMindWear | grep latency_trace
 */
internal object WearLatencyTrace {
    private const val TAG = "WristMindWear"
    private const val PREFIX = "latency_trace"

    fun log(event: String, vararg fields: Pair<String, Any?>) {
        val payload = fields.joinToString(" ") { (key, value) -> "$key=${value ?: "-"}" }
        val line = "$PREFIX event=$event $payload"
        Log.i(TAG, line)
        WearDiagnosticLog.record("latency", line)
    }
}

/** Event names shared with the server-side latency trace. */
internal object WearLatencyEvents {
    const val SEND_STARTED = "SEND_STARTED"
    const val JOB_ACCEPTED = "JOB_ACCEPTED"
    const val SSE_SUBSCRIBE_START = "SSE_SUBSCRIBE_START"
    const val WATCH_FIRST_DELTA_RECEIVED = "WATCH_FIRST_DELTA_RECEIVED"
    const val WATCH_FIRST_VISIBLE_TEXT = "WATCH_FIRST_VISIBLE_TEXT"
    const val FALLBACK = "FALLBACK"
}
