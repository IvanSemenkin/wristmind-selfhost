package dev.wristmind.core

import org.json.JSONObject
import java.security.MessageDigest
import java.util.Base64

object ProxyProtocol {
    const val VERSION = 1
    const val MAX_PART_BYTES = 48 * 1024
    const val MAX_PARTS = 64
    const val MAX_PAYLOAD_BYTES = 3 * 1024 * 1024
    // The phone may need to wake its mobile-radio connection before it can
    // forward a request from the watch. Eight seconds was shorter than the
    // API client's 15-second connect timeout, so a valid request could be
    // cancelled locally before it ever reached the server.
    const val RPC_TIMEOUT_MS = 25_000L
    const val ASSEMBLY_TIMEOUT_MS = 120_000L
    const val OUTGOING_CACHE_MS = 5 * 60_000L
    const val SSE_WINDOW_MS = 6_000L

    const val STATUS_OK = "OK"
    const val STATUS_ACCEPTED = "PART_ACCEPTED"
    const val STATUS_ERROR = "ERROR"

    const val ERROR_INVALID_ENVELOPE = "INVALID_ENVELOPE"
    const val ERROR_LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    const val ERROR_PART_CONFLICT = "PART_CONFLICT"
    const val ERROR_CHECKSUM = "CHECKSUM_MISMATCH"
    const val ERROR_ASSEMBLY_TIMEOUT = "ASSEMBLY_TIMEOUT"
    const val ERROR_RPC_TIMEOUT = "RPC_TIMEOUT"
    const val ERROR_MISSING_PART = "MISSING_PART"
    const val ERROR_PAUSED = "PAUSED"
}

object ProxyOperations {
    const val SPEECH_STREAM = "speech_stream"
    const val HEALTH = "health"
    const val ENROLL = "enroll"
    const val MODES = "modes"
    const val CHATS = "chats"
    const val CREATE_CHAT = "create_chat"
    const val CREATE_QUICK_CHAT = "create_quick_chat"
    const val DELETE_CHAT = "delete_chat"
    const val MESSAGES = "messages"
    const val SEND_MESSAGE = "send_message"
    const val JOB = "job"
    const val CANCEL_JOB = "cancel_job"
    const val CHAT_SOURCE_CANDIDATES = "chat_source_candidates"
    const val SAVE_CHAT_SOURCE_CANDIDATE = "save_chat_source_candidate"
    const val DISMISS_CHAT_SOURCE_CANDIDATE = "dismiss_chat_source_candidate"
    const val EVENTS_WINDOW = "events_window"
    const val REGISTER_PUSH_TOKEN = "register_push_token"
    const val FALLBACK_TICKET = "fallback_ticket"
    const val SYNC_FALLBACK_MESSAGE = "sync_fallback_message"
    const val FETCH_RESPONSE_PART = "fetch_response_part"
}

data class ProxyEnvelope(
    val protocolVersion: Int = ProxyProtocol.VERSION,
    val requestId: String,
    val operation: String,
    val partIndex: Int,
    val partCount: Int,
    val totalBytes: Int,
    val checksumSha256: String,
    val payloadBase64: String,
    val status: String? = null,
    val httpStatus: Int? = null,
    val errorCode: String? = null,
    val retryable: Boolean? = null,
) {
    fun payloadBytes(): ByteArray = Base64.getDecoder().decode(payloadBase64)

    fun toByteArray(): ByteArray = JSONObject().apply {
        put("protocolVersion", protocolVersion)
        put("requestId", requestId)
        put("operation", operation)
        put("partIndex", partIndex)
        put("partCount", partCount)
        put("totalBytes", totalBytes)
        put("checksumSha256", checksumSha256)
        put("payloadBase64", payloadBase64)
        status?.let { put("status", it) }
        httpStatus?.let { put("httpStatus", it) }
        errorCode?.let { put("errorCode", it) }
        retryable?.let { put("retryable", it) }
    }.toString().toByteArray(Charsets.UTF_8)

    companion object {
        fun fromByteArray(bytes: ByteArray): ProxyEnvelope {
            val json = JSONObject(bytes.toString(Charsets.UTF_8))
            return ProxyEnvelope(
                protocolVersion = json.getInt("protocolVersion"),
                requestId = json.getString("requestId"),
                operation = json.getString("operation"),
                partIndex = json.getInt("partIndex"),
                partCount = json.getInt("partCount"),
                totalBytes = json.getInt("totalBytes"),
                checksumSha256 = json.getString("checksumSha256"),
                payloadBase64 = json.getString("payloadBase64"),
                status = json.optString("status").takeIf(String::isNotBlank),
                httpStatus = if (json.has("httpStatus")) json.getInt("httpStatus") else null,
                errorCode = json.optString("errorCode").takeIf(String::isNotBlank),
                retryable = if (json.has("retryable")) json.getBoolean("retryable") else null,
            )
        }
    }
}

object ProxyChunker {
    fun split(
        requestId: String,
        operation: String,
        payload: ByteArray,
        status: String? = null,
        httpStatus: Int? = null,
        errorCode: String? = null,
        retryable: Boolean? = null,
    ): List<ProxyEnvelope> {
        require(requestId.isNotBlank()) { "requestId is required" }
        require(operation.isNotBlank()) { "operation is required" }
        require(payload.size <= ProxyProtocol.MAX_PAYLOAD_BYTES) { ProxyProtocol.ERROR_LIMIT_EXCEEDED }
        val checksum = sha256(payload)
        val chunks = if (payload.isEmpty()) {
            listOf(ByteArray(0))
        } else {
            (payload.indices step ProxyProtocol.MAX_PART_BYTES).map { start ->
                payload.copyOfRange(start, minOf(start + ProxyProtocol.MAX_PART_BYTES, payload.size))
            }
        }
        require(chunks.size <= ProxyProtocol.MAX_PARTS) { ProxyProtocol.ERROR_LIMIT_EXCEEDED }
        return chunks.mapIndexed { index, bytes ->
            ProxyEnvelope(
                requestId = requestId,
                operation = operation,
                partIndex = index,
                partCount = chunks.size,
                totalBytes = payload.size,
                checksumSha256 = checksum,
                payloadBase64 = Base64.getEncoder().encodeToString(bytes),
                status = status,
                httpStatus = httpStatus,
                errorCode = errorCode,
                retryable = retryable,
            )
        }
    }
}

sealed interface ProxyAssemblyResult {
    data class Incomplete(val missingParts: List<Int>) : ProxyAssemblyResult
    data class Complete(val requestId: String, val operation: String, val payload: ByteArray) : ProxyAssemblyResult
    data class Rejected(val errorCode: String, val retryable: Boolean) : ProxyAssemblyResult
}

class ProxyAssembler(private val clockMs: () -> Long = System::currentTimeMillis) {
    private data class Assembly(
        val createdAt: Long,
        val operation: String,
        val partCount: Int,
        val totalBytes: Int,
        val checksum: String,
        val parts: MutableMap<Int, ByteArray> = mutableMapOf(),
    )

    private val assemblies = mutableMapOf<String, Assembly>()

    @Synchronized
    fun accept(envelope: ProxyEnvelope): ProxyAssemblyResult {
        val now = clockMs()
        val expired = assemblies.filterValues { now - it.createdAt > ProxyProtocol.ASSEMBLY_TIMEOUT_MS }.keys
        expired.forEach(assemblies::remove)
        if (envelope.requestId in expired) {
            return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_ASSEMBLY_TIMEOUT, retryable = true)
        }
        val part = runCatching { envelope.payloadBytes() }.getOrElse {
            return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_INVALID_ENVELOPE, retryable = false)
        }
        if (
            envelope.protocolVersion != ProxyProtocol.VERSION ||
            envelope.requestId.isBlank() || envelope.operation.isBlank() ||
            envelope.partCount !in 1..ProxyProtocol.MAX_PARTS ||
            envelope.partIndex !in 0 until envelope.partCount ||
            envelope.totalBytes !in 0..ProxyProtocol.MAX_PAYLOAD_BYTES ||
            part.size > ProxyProtocol.MAX_PART_BYTES
        ) return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_LIMIT_EXCEEDED, retryable = false)

        val assembly = assemblies.getOrPut(envelope.requestId) {
            Assembly(now, envelope.operation, envelope.partCount, envelope.totalBytes, envelope.checksumSha256)
        }
        if (
            assembly.operation != envelope.operation || assembly.partCount != envelope.partCount ||
            assembly.totalBytes != envelope.totalBytes || assembly.checksum != envelope.checksumSha256
        ) {
            assemblies.remove(envelope.requestId)
            return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_PART_CONFLICT, retryable = false)
        }
        val previous = assembly.parts[envelope.partIndex]
        if (previous != null && !previous.contentEquals(part)) {
            assemblies.remove(envelope.requestId)
            return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_PART_CONFLICT, retryable = false)
        }
        assembly.parts[envelope.partIndex] = part
        val missing = (0 until assembly.partCount).filterNot(assembly.parts::containsKey)
        if (missing.isNotEmpty()) return ProxyAssemblyResult.Incomplete(missing)

        val payload = ByteArray(assembly.totalBytes)
        var offset = 0
        for (index in 0 until assembly.partCount) {
            val bytes = checkNotNull(assembly.parts[index])
            if (offset + bytes.size > payload.size) {
                assemblies.remove(envelope.requestId)
                return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_LIMIT_EXCEEDED, retryable = false)
            }
            bytes.copyInto(payload, offset)
            offset += bytes.size
        }
        assemblies.remove(envelope.requestId)
        if (offset != assembly.totalBytes || sha256(payload) != assembly.checksum) {
            return ProxyAssemblyResult.Rejected(ProxyProtocol.ERROR_CHECKSUM, retryable = true)
        }
        return ProxyAssemblyResult.Complete(envelope.requestId, envelope.operation, payload)
    }
}

class ProxyOutgoingCache(private val clockMs: () -> Long = System::currentTimeMillis) {
    private data class Cached(val createdAt: Long, val parts: List<ProxyEnvelope>)
    private val values = mutableMapOf<String, Cached>()

    @Synchronized fun put(requestId: String, parts: List<ProxyEnvelope>) {
        purge()
        values[requestId] = Cached(clockMs(), parts)
    }

    @Synchronized fun get(requestId: String, partIndex: Int): ProxyEnvelope? {
        purge()
        return values[requestId]?.parts?.getOrNull(partIndex)
    }

    private fun purge() {
        val now = clockMs()
        values.entries.removeAll { now - it.value.createdAt > ProxyProtocol.OUTGOING_CACHE_MS }
    }
}

internal fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(bytes)
    .joinToString("") { "%02x".format(it) }
