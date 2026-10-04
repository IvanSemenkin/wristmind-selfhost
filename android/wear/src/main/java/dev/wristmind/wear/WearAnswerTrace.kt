package dev.wristmind.wear

import android.util.Log

/**
 * TEMPORARY diagnostics for the "streamed answer disappears after completion" defect.
 *
 * Contract: log identifiers, lengths and lifecycle labels only. Never log the user
 * question, the assistant answer, or any other message body. Remove this file and
 * every `WearAnswerTrace` call site once the defect is closed.
 *
 * Filter with: adb logcat -s WristMindWear | grep answer_trace
 */
internal object WearAnswerTrace {
    private const val PREFIX = "answer_trace"

    fun log(event: String, vararg fields: Pair<String, Any?>) {
        val payload = fields.joinToString(" ") { (key, value) -> "$key=${value ?: "-"}" }
        val line = "$PREFIX event=$event $payload"
        Log.i(TAG, line)
        WearDiagnosticLog.record("answer", line)
    }

    /** Short, stable label for a message id without leaking content. */
    fun idKind(id: String?): String = when {
        id == null -> "none"
        id == STREAMING_ANSWER_ID -> "streaming"
        id.startsWith("local-") -> "local"
        else -> "server"
    }

    /** Length summary of a message list: counts plus the last assistant content size. */
    fun listShape(messages: List<dev.wristmind.core.ChatMessage>): String {
        val blankAssistants = messages.count { it.role == "assistant" && it.content.isBlank() }
        val lastAssistant = messages.lastOrNull { it.role == "assistant" }
        return "messages=${messages.size} blank_assistants=$blankAssistants " +
            "last_assistant_chars=${lastAssistant?.content?.length ?: -1}"
    }
}

private const val TAG = "WristMindWear"
