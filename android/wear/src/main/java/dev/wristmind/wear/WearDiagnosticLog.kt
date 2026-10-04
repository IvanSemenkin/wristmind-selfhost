package dev.wristmind.wear

import android.content.Context
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.Executors

/** Bounded, private copy of content-free Wear transport diagnostics for manual export. */
internal object WearDiagnosticLog {
    private const val MAX_LINES = 240
    private const val MAX_FILE_BYTES = 160_000L
    private val lines = ArrayDeque<String>()
    private val writer = Executors.newSingleThreadExecutor()
    private var file: File? = null

    fun initialize(context: Context) {
        synchronized(lines) {
            if (file != null) return
            val target = File(context.noBackupFilesDir, "wear-diagnostics.log")
            runCatching { target.takeIf(File::exists)?.readLines()?.takeLast(MAX_LINES) }
                .getOrNull()?.forEach(lines::addLast)
            file = target
        }
    }

    fun record(category: String, message: String) {
        // The first delta has its own latency mark. Persisting every token would
        // crowd the useful connection/state transitions out of the bounded log.
        if (category == "answer" && message.startsWith("answer_trace event=sse_delta ")) return
        val safeMessage = message.replace(Regex("[\\r\\n\\t]"), " ").take(650)
        val line = "${System.currentTimeMillis()} $category $safeMessage"
        val target = synchronized(lines) {
            lines.addLast(line)
            while (lines.size > MAX_LINES) lines.removeFirst()
            file
        } ?: return
        // File I/O never runs in the send/SSE callback or on Compose's main thread.
        writer.execute {
            runCatching {
                target.appendText("$line\n")
                if (target.length() > MAX_FILE_BYTES) {
                    target.writeText(target.readLines().takeLast(MAX_LINES).joinToString("\n", postfix = "\n"))
                }
            }
        }
    }

    fun snapshot(limit: Int = 180): List<String> = synchronized(lines) {
        lines.toList().takeLast(limit)
    }
}
