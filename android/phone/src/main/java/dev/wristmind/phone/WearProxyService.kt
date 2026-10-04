package dev.wristmind.phone

import com.google.android.gms.tasks.Task
import com.google.android.gms.tasks.TaskCompletionSource
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import dev.wristmind.core.DeviceConfig
import dev.wristmind.core.DeviceConfigStore
import dev.wristmind.core.ProxyAssembler
import dev.wristmind.core.ProxyAssemblyResult
import dev.wristmind.core.ProxyChunker
import dev.wristmind.core.ProxyEnvelope
import dev.wristmind.core.ProxyJson
import dev.wristmind.core.ProxyOperations
import dev.wristmind.core.ProxyOutgoingCache
import dev.wristmind.core.ProxyProtocol
import dev.wristmind.core.ServerEvent
import dev.wristmind.core.WristMindApi
import dev.wristmind.core.WristMindApiException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.IOException

object PhoneConfigEvents {
    val tokenReceived = MutableSharedFlow<DeviceConfig>(extraBufferCapacity = 1)
}

class WearProxyService : WearableListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val assembler = ProxyAssembler()
    private val outgoing = ProxyOutgoingCache()

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onRequest(nodeId: String, path: String, request: ByteArray): Task<ByteArray>? {
        if (path != RPC_PATH) return null
        val completion = TaskCompletionSource<ByteArray>()
        scope.launch {
            completion.setResult(
                runCatching { withTimeout(ProxyProtocol.RPC_TIMEOUT_MS) { handleRequest(request) } }
                    .getOrElse { errorResponse(request, it) },
            )
        }
        return completion.task
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        dataEvents.filter { it.type == DataEvent.TYPE_CHANGED && it.dataItem.uri.path == WatchLink.CONFIG_PATH }
            .forEach { event ->
                val data = DataMapItem.fromDataItem(event.dataItem).dataMap
                val incomingToken = data.getString("device_token").orEmpty()
                if (incomingToken.isBlank()) return@forEach
                if (data.getString("origin") != "watch") return@forEach
                val store = DeviceConfigStore(this, "phone")
                val local = store.read(BuildConfig.WRISTMIND_BASE_URL)
                val config = DeviceConfig(data.getString("server_url") ?: BuildConfig.WRISTMIND_BASE_URL, incomingToken)
                if (local != config) {
                    store.save(config)
                    getSharedPreferences(PREFS, 0).edit().putBoolean(KEY_PAUSED, false).apply()
                    PhoneConfigEvents.tokenReceived.tryEmit(config)
                }
            }
    }

    private suspend fun handleRequest(request: ByteArray): ByteArray {
        val envelope = ProxyEnvelope.fromByteArray(request)
        if (paused()) return responseError(envelope, ProxyProtocol.ERROR_PAUSED, retryable = true)
        if (envelope.operation == ProxyOperations.FETCH_RESPONSE_PART) return fetchResponsePart(envelope)
        return when (val result = assembler.accept(envelope)) {
            is ProxyAssemblyResult.Incomplete -> response(
                envelope,
                ProxyJson.objectBytes { put("missing_parts", result.missingParts) },
                status = ProxyProtocol.STATUS_ACCEPTED,
            )
            is ProxyAssemblyResult.Rejected -> responseError(envelope, result.errorCode, result.retryable)
            is ProxyAssemblyResult.Complete -> execute(result.requestId, result.operation, result.payload)
        }
    }

    private suspend fun execute(requestId: String, operation: String, payload: ByteArray): ByteArray {
        val input = ProxyJson.objectFrom(payload)
        val store = DeviceConfigStore(this, "phone")
        var config = store.read(BuildConfig.WRISTMIND_BASE_URL)
        val publicApi = WristMindApi(config.serverUrl)
        val result = when (operation) {
            ProxyOperations.HEALTH -> {
                val healthy = publicApi.health()
                ProxyJson.objectBytes { put("ok", healthy) }
            }
            ProxyOperations.ENROLL -> {
                val enrolled = publicApi.enrollWatch(input.optString("name", "Xiaomi Watch 2"), input.getString("code"))
                config = DeviceConfig(config.serverUrl, enrolled.token)
                store.save(config)
                PhoneConfigEvents.tokenReceived.tryEmit(config)
                WatchLink(this).publishConfig(config.serverUrl, enrolled.token, paused = false)
                ProxyJson.deviceToken(enrolled)
            }
            else -> executeAuthorized(WristMindApi(config.serverUrl, requireToken(config.token)), operation, input)
        }
        return cacheAndFirst(requestId, operation, result)
    }

    private suspend fun executeAuthorized(api: WristMindApi, operation: String, input: JSONObject): ByteArray = when (operation) {
        ProxyOperations.REGISTER_PUSH_TOKEN -> {
            api.registerPushToken(input.getString("token"))
            ProxyJson.objectBytes()
        }
        ProxyOperations.FALLBACK_TICKET -> api.fallbackTicket().let { ticket ->
            ProxyJson.objectBytes { put("ticket", ticket.ticket); put("expires_at", ticket.expiresAt) }
        }
        ProxyOperations.MODES -> ProxyJson.modes(api.modes())
        ProxyOperations.CHATS -> ProxyJson.chats(api.chats())
        ProxyOperations.CREATE_CHAT -> ProxyJson.chat(
            api.createChat(input.getString("mode_id"), input.getString("client_request_id")),
        )
        ProxyOperations.CREATE_QUICK_CHAT -> ProxyJson.chat(
            api.createQuickChat(input.getString("client_request_id")),
        )
        ProxyOperations.DELETE_CHAT -> {
            api.deleteChat(input.getString("chat_id"))
            ProxyJson.objectBytes()
        }
        ProxyOperations.MESSAGES -> ProxyJson.messages(
            api.messages(input.getString("chat_id"), input.optInt("limit").takeIf { it > 0 }),
        )
        ProxyOperations.SEND_MESSAGE -> ProxyJson.job(
            api.sendMessage(
                input.getString("chat_id"),
                input.getString("request_id"),
                input.getString("text"),
                input.optBoolean("web_search"),
                input.optBoolean("web_research"),
                input.optBoolean("research_mode"),
            ),
        )
        ProxyOperations.SYNC_FALLBACK_MESSAGE -> {
            val status = api.syncFallbackMessage(
                input.getString("chat_id"),
                input.getString("request_id"),
                input.getString("user_text"),
                input.getString("assistant_text"),
            )
            ProxyJson.objectBytes { put("status", status) }
        }
        ProxyOperations.JOB -> ProxyJson.job(api.job(input.getString("job_id")))
        ProxyOperations.CANCEL_JOB -> ProxyJson.job(api.cancelJob(input.getString("job_id")))
        ProxyOperations.CHAT_SOURCE_CANDIDATES -> ProxyJson.chatSourceCandidates(
            api.chatSourceCandidates(input.getString("chat_id")),
        )
        ProxyOperations.SAVE_CHAT_SOURCE_CANDIDATE -> ProxyJson.job(
            api.saveChatSourceCandidate(
                input.getString("chat_id"), input.getString("candidate_id"), input.getString("request_id"),
            ),
        )
        ProxyOperations.DISMISS_CHAT_SOURCE_CANDIDATE -> {
            api.dismissChatSourceCandidate(input.getString("chat_id"), input.getString("candidate_id"))
            ProxyJson.objectBytes()
        }
        ProxyOperations.EVENTS_WINDOW -> ProxyJson.events(eventWindow(api, input.getString("job_id"), input.optLong("cursor")))
        else -> throw IllegalArgumentException("Unknown proxy operation: $operation")
    }

    private suspend fun eventWindow(api: WristMindApi, jobId: String, cursor: Long): List<ServerEvent> {
        val events = mutableListOf<ServerEvent>()
        var estimatedBytes = 0
        withTimeoutOrNull(ProxyProtocol.SSE_WINDOW_MS) {
            api.events(jobId, cursor)
                .takeWhile { event ->
                    estimatedBytes += event.data.toByteArray().size + 96
                    estimatedBytes <= ProxyProtocol.MAX_PAYLOAD_BYTES && events.size < MAX_EVENTS_PER_WINDOW
                }
                .collect(events::add)
        }
        return events
    }

    private fun cacheAndFirst(requestId: String, operation: String, payload: ByteArray): ByteArray {
        val parts = ProxyChunker.split(requestId, operation, payload, status = ProxyProtocol.STATUS_OK, httpStatus = 200, retryable = false)
        outgoing.put(requestId, parts)
        return parts.first().toByteArray()
    }

    private fun fetchResponsePart(envelope: ProxyEnvelope): ByteArray {
        val input = ProxyJson.objectFrom(envelope.payloadBytes())
        val target = input.getString("target_request_id")
        val index = input.getInt("part_index")
        return outgoing.get(target, index)?.toByteArray()
            ?: responseError(envelope, ProxyProtocol.ERROR_MISSING_PART, retryable = index >= 0)
    }

    private fun response(
        request: ProxyEnvelope,
        payload: ByteArray,
        status: String,
        httpStatus: Int? = null,
        errorCode: String? = null,
        retryable: Boolean? = null,
    ): ByteArray = ProxyChunker.split(
        request.requestId, request.operation, payload, status, httpStatus, errorCode, retryable,
    ).single().toByteArray()

    private fun responseError(request: ProxyEnvelope, code: String, retryable: Boolean, httpStatus: Int? = null): ByteArray =
        response(request, ByteArray(0), ProxyProtocol.STATUS_ERROR, httpStatus, code, retryable)

    private fun errorResponse(rawRequest: ByteArray, error: Throwable): ByteArray {
        val request = runCatching { ProxyEnvelope.fromByteArray(rawRequest) }.getOrElse {
            return ProxyChunker.split(
                "invalid", "invalid", ByteArray(0), ProxyProtocol.STATUS_ERROR, null,
                ProxyProtocol.ERROR_INVALID_ENVELOPE, false,
            ).single().toByteArray()
        }
        val apiError = error as? WristMindApiException
        val timedOut = error is TimeoutCancellationException
        return responseError(
            request,
            code = when {
                apiError != null -> "HTTP_${apiError.statusCode}"
                timedOut -> ProxyProtocol.ERROR_RPC_TIMEOUT
                else -> error.message.orEmpty().ifBlank { "PROXY_ERROR" }
            },
            retryable = timedOut || error is IOException && apiError == null,
            httpStatus = apiError?.statusCode,
        )
    }

    private fun paused() = getSharedPreferences(PREFS, 0).getBoolean(KEY_PAUSED, false)
    private fun requireToken(token: String) = token.takeIf(String::isNotBlank) ?: throw IOException("Companion is not paired")

    companion object {
        const val RPC_PATH = "/wristmind/proxy/v1"
        const val PREFS = "wristmind_companion"
        const val KEY_PAUSED = "paused"
        private const val MAX_EVENTS_PER_WINDOW = 128
    }
}
