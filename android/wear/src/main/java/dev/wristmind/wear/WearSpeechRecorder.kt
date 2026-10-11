package dev.wristmind.wear

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import android.os.SystemClock
import java.io.ByteArrayOutputStream
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONObject

internal data class SpeechRecordingState(
    val phase: String = "ready",
    val seconds: Int = 0,
    val levels: List<Float> = emptyList(),
    val text: String = "",
    val error: String? = null,
)

/** Bounded live PCM capture. Transport runs independently from the microphone. */
internal class WearSpeechRecorder(private val request: suspend (JSONObject) -> JSONObject) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutableState = MutableStateFlow(SpeechRecordingState())
    val state = mutableState.asStateFlow()
    private val sessionId = UUID.randomUUID().toString()
    private val stopping = AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    private val started = AtomicBoolean(false)
    private val chunks = Channel<ByteArray>(80)
    private var audio: AudioRecord? = null
    private var capture: Job? = null
    private var sender: Job? = null

    private suspend fun send(input: JSONObject): JSONObject {
        val startedAt = SystemClock.elapsedRealtime()
        try { return request(input) }
        finally {
            val line = "speech_transport action=${input.optString("action")} seq=${input.optInt("seq", -1)} wire_chars=${input.optString("data").length} elapsed_ms=${SystemClock.elapsedRealtime() - startedAt}"
            Log.i("WristMindWear", line)
            WearDiagnosticLog.record("speech", line)
        }
    }

    private fun body(action: String) = JSONObject().put("session_id", sessionId).put("action", action)

    @SuppressLint("MissingPermission")
    fun start() {
        if (cancelled.get() || !started.compareAndSet(false, true)) return
        sender = scope.launch {
            try {
                send(body("start"))
                var seq = 0
                for (chunk in chunks) {
                    val batch = ByteArrayOutputStream().apply { write(chunk) }
                    // Coalesce queued fragments on a weak link, keeping bounded request sizes.
                    while (batch.size() <= 48_000) {
                        val extra = chunks.tryReceive().getOrNull() ?: break
                        batch.write(extra)
                    }
                    val packet = speechAudioPacket(batch.toByteArray())
                    send(body("chunk").put("seq", seq++)
                        .put("encoding", packet.encoding).put("data", packet.data))
                }
                val result = send(body("finish"))
                if (!cancelled.get()) mutableState.update { it.copy(phase = "done", text = result.optString("text")) }
            } catch (error: CancellationException) {
                if (error !is TimeoutCancellationException) throw error
                stopping.set(true)
                runCatching { audio?.stop() }
                capture?.cancel()
                if (!cancelled.get()) mutableState.update {
                    it.copy(phase = "error", error = "Соединение прервалось. Попробуйте ещё раз")
                }
                withTimeoutOrNull(8_000) { runCatching { send(body("cancel")) } }
            } catch (error: Exception) {
                stopping.set(true)
                runCatching { audio?.stop() }
                capture?.cancel()
                if (!cancelled.get()) mutableState.update {
                    it.copy(phase = "error", error = error.message ?: "Не удалось распознать речь")
                }
                withTimeoutOrNull(8_000) { runCatching { send(body("cancel")) } }
            }
        }
        capture = scope.launch {
            var recorder: AudioRecord? = null
            try {
                val minimum = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
                check(minimum > 0) { "Микрофон недоступен" }
                recorder = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16_000,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum * 2, 12_800))
                check(recorder.state == AudioRecord.STATE_INITIALIZED) { "Микрофон недоступен" }
                audio = recorder
                ensureActive()
                if (stopping.get()) return@launch
                recorder.startRecording()
                mutableState.update { it.copy(phase = "recording") }
                val buffer = ByteArray(3_200)
                var total = 0
                val packet = ByteArrayOutputStream()
                while (isActive && !stopping.get() && total < 960_000) {
                    val count = recorder.read(buffer, 0, minOf(buffer.size, 960_000 - total))
                    if (count <= 0) {
                        if (stopping.get()) break
                        error("Микрофон недоступен")
                    }
                    packet.write(buffer, 0, count)
                    total += count
                    var energy = 0.0
                    for (index in 0 until count - 1 step 2) {
                        val value = ((buffer[index].toInt() and 255) or (buffer[index + 1].toInt() shl 8)).toShort().toDouble() / 32768
                        energy += value * value
                    }
                    val level = (sqrt(energy / (count / 2)) * 6).coerceIn(0.0, 1.0).toFloat()
                    mutableState.update { it.copy(seconds = total / 32_000, levels = (it.levels + level).takeLast(32)) }
                    if (packet.size() >= 12_800) { chunks.send(packet.toByteArray()); packet.reset() }
                }
                if (packet.size() > 0 && !cancelled.get()) chunks.send(packet.toByteArray())
                chunks.close()
                if (!cancelled.get()) mutableState.update { if (it.phase == "recording") it.copy(phase = "recognizing") else it }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                sender?.cancel()
                chunks.close()
                if (!cancelled.get()) mutableState.update { it.copy(phase = "error", error = error.message ?: "Микрофон недоступен") }
                withTimeoutOrNull(8_000) { runCatching { send(body("cancel")) } }
            } finally {
                runCatching { recorder?.stop() }
                recorder?.release()
                audio = null
            }
        }
    }

    fun finish() {
        if (mutableState.value.phase != "recording") return
        stopping.set(true)
        mutableState.update { it.copy(phase = "recognizing") }
        runCatching { audio?.stop() } // Unblock read, then flush the final partial packet.
    }

    fun cancel() {
        if (!cancelled.compareAndSet(false, true)) return
        stopping.set(true)
        mutableState.update { it.copy(phase = "cancelled") }
        runCatching { audio?.stop() }
        capture?.cancel()
        sender?.cancel()
        chunks.cancel()
        scope.launch {
            try {
                if (started.get()) withTimeoutOrNull(8_000) { runCatching { send(body("cancel")) } }
            } finally { scope.cancel() }
        }
    }
}
