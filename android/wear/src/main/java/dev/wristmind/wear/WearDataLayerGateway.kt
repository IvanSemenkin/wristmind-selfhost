package dev.wristmind.wear

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.Wearable
import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import dev.wristmind.core.ChatSourceCandidate
import dev.wristmind.core.DeviceToken
import dev.wristmind.core.FallbackTicket
import dev.wristmind.core.Job
import dev.wristmind.core.Mode
import dev.wristmind.core.ProxyAssembler
import dev.wristmind.core.ProxyAssemblyResult
import dev.wristmind.core.ProxyChunker
import dev.wristmind.core.ProxyEnvelope
import dev.wristmind.core.ProxyJson
import dev.wristmind.core.ProxyOperations
import dev.wristmind.core.ProxyProtocol
import dev.wristmind.core.ServerEvent
import dev.wristmind.core.WristMindApiException
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.ensureActive
import org.json.JSONObject

interface ProxyWearGateway : WearGateway {
    suspend fun isReachable(): Boolean
}

class DataLayerProxyGateway(context: Context) : ProxyWearGateway {
    private val capabilityClient = Wearable.getCapabilityClient(context)
    private val messageClient = Wearable.getMessageClient(context)

    override suspend fun speechStream(body: JSONObject): JSONObject = ProxyJson.objectFrom(rpc(ProxyOperations.SPEECH_STREAM, body.toString().toByteArray()))

    override suspend fun isReachable(): Boolean = resolveNodeId() != null

    override suspend fun health(): Boolean = ProxyJson.objectFrom(rpc(ProxyOperations.HEALTH)).optBoolean("ok")

    override suspend fun enroll(code: String): DeviceToken = ProxyJson.parseDeviceToken(
        rpc(ProxyOperations.ENROLL, ProxyJson.objectBytes { put("name", "Xiaomi Watch 2"); put("code", code) }),
    )

    override suspend fun registerPushToken(token: String) {
        rpc(ProxyOperations.REGISTER_PUSH_TOKEN, ProxyJson.objectBytes { put("token", token) })
    }
    override suspend fun fallbackTicket(): FallbackTicket = ProxyJson.objectFrom(
        rpc(ProxyOperations.FALLBACK_TICKET),
    ).let { FallbackTicket(it.getString("ticket"), it.getString("expires_at")) }

    override suspend fun modes(): List<Mode> = ProxyJson.parseModes(rpc(ProxyOperations.MODES))
    override suspend fun chats(): List<Chat> = ProxyJson.parseChats(rpc(ProxyOperations.CHATS))
    override suspend fun createChat(modeId: String, clientRequestId: String): Chat = ProxyJson.parseChat(
        rpc(
            ProxyOperations.CREATE_CHAT,
            ProxyJson.objectBytes { put("mode_id", modeId); put("client_request_id", clientRequestId) },
            clientRequestId,
        ),
    )
    override suspend fun createQuickChat(clientRequestId: String): Chat = ProxyJson.parseChat(
        rpc(
            ProxyOperations.CREATE_QUICK_CHAT,
            ProxyJson.objectBytes { put("client_request_id", clientRequestId) },
            clientRequestId,
        ),
    )
    override suspend fun deleteChat(chatId: String) {
        rpc(ProxyOperations.DELETE_CHAT, ProxyJson.objectBytes { put("chat_id", chatId) })
    }
    override suspend fun messages(chatId: String): List<ChatMessage> = ProxyJson.parseMessages(
        rpc(ProxyOperations.MESSAGES, ProxyJson.objectBytes { put("chat_id", chatId); put("limit", WEAR_HISTORY_PAGE_SIZE) }),
    )
    override suspend fun sendMessage(chatId: String, requestId: String, text: String, webSearch: Boolean, webResearch: Boolean, researchMode: Boolean): Job = ProxyJson.parseJob(
        rpc(
            ProxyOperations.SEND_MESSAGE,
            ProxyJson.objectBytes {
                put("chat_id", chatId); put("request_id", requestId); put("text", text); put("web_search", webSearch); put("web_research", webResearch); put("research_mode", researchMode)
            },
            requestId,
        ),
    )
    override suspend fun syncFallbackMessage(chatId: String, requestId: String, userText: String, assistantText: String): String =
        ProxyJson.objectFrom(
            rpc(
                ProxyOperations.SYNC_FALLBACK_MESSAGE,
                ProxyJson.objectBytes {
                    put("chat_id", chatId); put("request_id", requestId)
                    put("user_text", userText); put("assistant_text", assistantText)
                },
                requestId,
            ),
        ).getString("status")
    override suspend fun job(jobId: String): Job = ProxyJson.parseJob(
        rpc(ProxyOperations.JOB, ProxyJson.objectBytes { put("job_id", jobId) }),
    )
    override suspend fun cancelJob(jobId: String): Job = ProxyJson.parseJob(
        rpc(ProxyOperations.CANCEL_JOB, ProxyJson.objectBytes { put("job_id", jobId) }),
    )
    override suspend fun chatSourceCandidates(chatId: String): List<ChatSourceCandidate> = ProxyJson.parseChatSourceCandidates(
        rpc(ProxyOperations.CHAT_SOURCE_CANDIDATES, ProxyJson.objectBytes { put("chat_id", chatId) }),
    )
    override suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String): Job = ProxyJson.parseJob(
        rpc(ProxyOperations.SAVE_CHAT_SOURCE_CANDIDATE, ProxyJson.objectBytes {
            put("chat_id", chatId); put("candidate_id", candidateId); put("request_id", requestId)
        }, requestId),
    )
    override suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String) {
        rpc(ProxyOperations.DISMISS_CHAT_SOURCE_CANDIDATE, ProxyJson.objectBytes {
            put("chat_id", chatId); put("candidate_id", candidateId)
        })
    }

    override fun events(jobId: String, after: Long): Flow<ServerEvent> = flow {
        var cursor = after
        var terminal = false
        var window = 0
        while (!terminal) {
            window += 1
            val events = ProxyJson.parseEvents(
                rpc(
                    ProxyOperations.EVENTS_WINDOW,
                    ProxyJson.objectBytes { put("job_id", jobId); put("cursor", cursor) },
                ),
            )
            WearAnswerTrace.log(
                "sse_route",
                "route" to "data_layer",
                "job_id" to jobId,
                "window" to window,
                "after" to cursor,
                "events" to events.size,
                "delta_chars" to events.sumOf { event ->
                    runCatching { JSONObject(event.data).optString("text").length }.getOrDefault(0)
                },
                "terminal" to events.any { it.type == "complete" || it.type == "error" || it.type == "cancelled" },
            )
            events.forEach { event ->
                cursor = maxOf(cursor, event.id)
                emit(event)
                terminal = terminal || event.type == "complete" || event.type == "error" || event.type == "cancelled"
            }
        }
    }

    private suspend fun rpc(operation: String, payload: ByteArray = ProxyJson.objectBytes(), requestId: String = UUID.randomUUID().toString()): ByteArray {
        val nodeId = resolveNodeId() ?: throw IOException("Companion недоступен")
        val requestParts = ProxyChunker.split(requestId, operation, payload)
        var firstResponse: ProxyEnvelope? = null
        requestParts.forEachIndexed { index, part ->
            val response = send(nodeId, part)
            checkResponse(response)
            if (index < requestParts.lastIndex) {
                if (response.status != ProxyProtocol.STATUS_ACCEPTED) throw IOException("Некорректный ответ proxy")
            } else {
                firstResponse = response
            }
        }
        val initial = checkNotNull(firstResponse)
        val assembler = ProxyAssembler()
        var result = assembler.accept(initial)
        if (result is ProxyAssemblyResult.Incomplete) {
            for (index in result.missingParts) {
                val fetched = fetchPart(nodeId, requestId, index)
                checkResponse(fetched)
                result = assembler.accept(fetched)
                if (result is ProxyAssemblyResult.Rejected) break
            }
        }
        return when (result) {
            is ProxyAssemblyResult.Complete -> result.payload
            is ProxyAssemblyResult.Rejected -> throw IOException("Proxy: ${result.errorCode}")
            is ProxyAssemblyResult.Incomplete -> throw IOException("Proxy: ${ProxyProtocol.ERROR_MISSING_PART}")
        }
    }

    private suspend fun fetchPart(nodeId: String, targetRequestId: String, partIndex: Int): ProxyEnvelope {
        val control = ProxyChunker.split(
            UUID.randomUUID().toString(),
            ProxyOperations.FETCH_RESPONSE_PART,
            ProxyJson.objectBytes { put("target_request_id", targetRequestId); put("part_index", partIndex) },
        ).single()
        return runCatching { send(nodeId, control) }.getOrElse { send(nodeId, control) }
    }

    private suspend fun send(nodeId: String, envelope: ProxyEnvelope): ProxyEnvelope = withTimeout(ProxyProtocol.RPC_TIMEOUT_MS) {
        ProxyEnvelope.fromByteArray(messageClient.sendRequest(nodeId, RPC_PATH, envelope.toByteArray()).await())
    }

    private fun checkResponse(response: ProxyEnvelope) {
        if (response.status != ProxyProtocol.STATUS_ERROR) return
        response.httpStatus?.let { throw WristMindApiException(it, response.errorCode.orEmpty()) }
        throw ProxyGatewayException(response.errorCode.orEmpty().ifBlank { "PROXY_ERROR" }, response.retryable == true)
    }

    private suspend fun resolveNodeId(): String? = withTimeoutOrNull(NODE_RESOLVE_TIMEOUT_MS) {
        capabilityClient
            .getCapability(PHONE_CAPABILITY, CapabilityClient.FILTER_REACHABLE)
            .await().nodes.firstOrNull()?.id
    }

    companion object {
        const val PHONE_CAPABILITY = "wristmind_companion"
        const val RPC_PATH = "/wristmind/proxy/v1"
    }
}

class ProxyGatewayException(val code: String, val canRetry: Boolean) : IOException("Proxy: $code")

class FailoverWearGateway(
    private val direct: WearGateway,
    private val proxy: ProxyWearGateway,
    private val sendLogger: (String) -> Unit = { message ->
        Log.i(TAG, message)
        WearDiagnosticLog.record("route", message)
    },
    private val onRoute: (usingProxy: Boolean, phoneReachable: Boolean) -> Unit = { _, _ -> },
) : WearGateway {
    private var cachedPhoneReachable: Boolean? = null
    private var phoneCheckedAt = 0L

    /**
     * Whether the phone companion answers, bounded and cached.
     *
     * `getCapability(...).await()` has no timeout of its own and can block for
     * many seconds while the phone sleeps or the Data Layer reconnects. Probing
     * it after every successful request used to add tens of seconds to a single
     * refresh, so the query is capped and its result is reused.
     *
     * [force] is for the failure path, where the answer decides whether the proxy
     * is worth trying at all.
     */
    private suspend fun phoneReachable(force: Boolean = false): Boolean {
        val now = monotonicMillis()
        val cached = cachedPhoneReachable
        if (!force && cached != null && now - phoneCheckedAt < PHONE_PROBE_TTL_MS) return cached
        val value = withTimeoutOrNull(PHONE_PROBE_TIMEOUT_MS) {
            runCatching { proxy.isReachable() }.getOrDefault(false)
        } ?: false
        cachedPhoneReachable = value
        phoneCheckedAt = now
        return value
    }

    private val speechProxyRoutes = java.util.concurrent.ConcurrentHashMap<String, Boolean>()

    override suspend fun speechStream(body: JSONObject): JSONObject {
        val id = body.getString("session_id")
        val action = body.getString("action")
        try {
            if (speechProxyRoutes[id] == true) {
                try {
                    return proxy.speechStream(body)
                } catch (error: Throwable) {
                    if (error !is TimeoutCancellationException && !error.isDirectTransportFailure()) throw error
                    kotlinx.coroutines.currentCoroutineContext().ensureActive()
                    speechProxyRoutes.remove(id)
                }
            }
            return try {
                withTimeout(if (action == "finish") 30_000L else 20_000L) {
                    direct.speechStream(body)
                }.also { onRoute(false, cachedPhoneReachable ?: false) }
            } catch (error: Throwable) {
                if (error !is TimeoutCancellationException && !error.isDirectTransportFailure()) throw error
                kotlinx.coroutines.currentCoroutineContext().ensureActive()
                // Start/chunk/finish are idempotent: repeat the same packet when a
                // radio handover lost its response, before abandoning direct HTTPS.
                try {
                    return withTimeout(if (action == "finish") 30_000L else 12_000L) {
                        direct.speechStream(body)
                    }.also { onRoute(false, cachedPhoneReachable ?: false) }
                } catch (retryError: Throwable) {
                    if (retryError !is TimeoutCancellationException && !retryError.isDirectTransportFailure()) throw retryError
                    kotlinx.coroutines.currentCoroutineContext().ensureActive()
                    if (!phoneReachable(force = true)) throw retryError
                }
                proxy.speechStream(body).also {
                    // Once a live recording switches transport, avoid paying a failed direct
                    // connect budget again for each audio packet.
                    speechProxyRoutes[id] = true
                    onRoute(true, true)
                }
            }
        } finally {
            if (action == "finish" || action == "cancel") speechProxyRoutes.remove(id)
        }
    }

    override suspend fun health(): Boolean = try {
        val healthy = direct.health()
        if (healthy) {
            onRoute(false, phoneReachable())
            true
        } else {
            onRoute(true, phoneReachable(force = true))
            proxy.health()
        }
    } catch (error: Throwable) {
        if (!error.isDirectTransportFailure()) throw error
        onRoute(true, phoneReachable(force = true))
        proxy.health()
    }

    override suspend fun enroll(code: String) = directFirst({ direct.enroll(code) }, { proxy.enroll(code) })
    override suspend fun registerPushToken(token: String) = directFirst(
        { direct.registerPushToken(token) }, { proxy.registerPushToken(token) },
    )
    override suspend fun fallbackTicket() = directFirst(direct::fallbackTicket, proxy::fallbackTicket)
    override suspend fun modes() = directFirst(direct::modes, proxy::modes)
    override suspend fun chats() = directFirst(direct::chats, proxy::chats)
    override suspend fun createChat(modeId: String, clientRequestId: String) = createFirst(
        clientRequestId,
        { direct.createChat(modeId, clientRequestId) },
        { proxy.createChat(modeId, clientRequestId) },
    )
    override suspend fun createQuickChat(clientRequestId: String) = createFirst(
        clientRequestId,
        { direct.createQuickChat(clientRequestId) },
        { proxy.createQuickChat(clientRequestId) },
    )
    override suspend fun deleteChat(chatId: String) = directFirst({ direct.deleteChat(chatId) }, { proxy.deleteChat(chatId) })
    override suspend fun messages(chatId: String) = directFirst({ direct.messages(chatId) }, { proxy.messages(chatId) })
    override suspend fun sendMessage(chatId: String, requestId: String, text: String, webSearch: Boolean, webResearch: Boolean, researchMode: Boolean): Job {
        val startedAt = monotonicMillis()
        sendLogger("send_route request_id=$requestId event=direct_start elapsed_ms=0")
        return try {
            withTimeout(DIRECT_SEND_BUDGET_MS) { direct.sendMessage(chatId, requestId, text, webSearch, webResearch, researchMode) }
                .also {
                    // A successful POST must return its job without a Data Layer probe.
                    // Other connection checks update phone reachability separately.
                    onRoute(false, cachedPhoneReachable ?: false)
                    sendLogger("send_route request_id=$requestId event=direct_accepted elapsed_ms=${monotonicMillis() - startedAt}")
                }
        } catch (error: Throwable) {
            if (error !is TimeoutCancellationException && !error.isDirectTransportFailure()) throw error
            sendLogger("send_route request_id=$requestId event=direct_recovery_start elapsed_ms=${monotonicMillis() - startedAt}")
            val recoveryError = try {
                val job = withTimeout(DIRECT_RECOVERY_BUDGET_MS) {
                    direct.recoverSendMessage(chatId, requestId, text, webSearch, webResearch, researchMode)
                }
                onRoute(false, cachedPhoneReachable ?: false)
                sendLogger("send_route request_id=$requestId event=direct_recovery_accepted elapsed_ms=${monotonicMillis() - startedAt}")
                return job
            } catch (retryError: Throwable) {
                if (retryError !is TimeoutCancellationException && !retryError.isDirectTransportFailure()) throw retryError
                retryError
            }
            val phone = phoneReachable(force = true)
            if (!phone) {
                onRoute(false, false)
                sendLogger("send_route request_id=$requestId event=proxy_skipped elapsed_ms=${monotonicMillis() - startedAt} reason=phone_unreachable")
                throw recoveryError
            }
            onRoute(true, true)
            sendLogger(
                "send_route request_id=$requestId event=proxy_start elapsed_ms=${monotonicMillis() - startedAt} reason=${recoveryError.javaClass.simpleName}",
            )
            withTimeout(PROXY_SEND_BUDGET_MS) {
                proxy.sendMessage(chatId, requestId, text, webSearch, webResearch, researchMode)
            }.also {
                sendLogger("send_route request_id=$requestId event=proxy_accepted elapsed_ms=${monotonicMillis() - startedAt}")
            }
        }
    }
    override suspend fun syncFallbackMessage(chatId: String, requestId: String, userText: String, assistantText: String) = directFirst(
        { direct.syncFallbackMessage(chatId, requestId, userText, assistantText) },
        { proxy.syncFallbackMessage(chatId, requestId, userText, assistantText) },
    )
    override suspend fun job(jobId: String) = directFirst({ direct.job(jobId) }, { proxy.job(jobId) })
    override suspend fun cancelJob(jobId: String) = directFirst({ direct.cancelJob(jobId) }, { proxy.cancelJob(jobId) })
    override suspend fun chatSourceCandidates(chatId: String) = directFirst(
        { direct.chatSourceCandidates(chatId) }, { proxy.chatSourceCandidates(chatId) },
    )
    override suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String): Job {
        val startedAt = monotonicMillis()
        sendLogger("source_save request_id=$requestId event=direct_start elapsed_ms=0")
        return try {
            withTimeout(DIRECT_SEND_BUDGET_MS) { direct.saveChatSourceCandidate(chatId, candidateId, requestId) }
                .also { sendLogger("source_save request_id=$requestId event=direct_accepted elapsed_ms=${monotonicMillis() - startedAt}") }
        } catch (error: Throwable) {
            if (error !is TimeoutCancellationException && !error.isDirectTransportFailure()) throw error
            sendLogger("source_save request_id=$requestId event=proxy_start elapsed_ms=${monotonicMillis() - startedAt}")
            proxy.saveChatSourceCandidate(chatId, candidateId, requestId)
        }
    }
    override suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String) = directFirst(
        { direct.dismissChatSourceCandidate(chatId, candidateId) }, { proxy.dismissChatSourceCandidate(chatId, candidateId) },
    )
    override fun events(jobId: String, after: Long): Flow<ServerEvent> = flow {
        var cursor = after
        try {
            direct.events(jobId, cursor).collect { event ->
                cursor = maxOf(cursor, event.id)
                emit(event)
            }
        } catch (error: Throwable) {
            WearAnswerTrace.log(
                "sse_route_switch",
                "job_id" to jobId,
                "cursor" to cursor,
                "error" to error.javaClass.simpleName,
                "direct_transport_failure" to error.isDirectTransportFailure(),
            )
            if (!error.isDirectTransportFailure()) throw error
            val phone = phoneReachable(force = true)
            onRoute(true, phone)
            proxy.events(jobId, cursor).collect { emit(it) }
        }
    }

    private suspend fun <T> directFirst(directCall: suspend () -> T, proxyCall: suspend () -> T): T = try {
        directCall().also { onRoute(false, phoneReachable()) }
    } catch (error: Throwable) {
        if (!error.isDirectTransportFailure()) throw error
        val phone = runCatching { proxy.isReachable() }.getOrDefault(false)
        onRoute(true, phone)
        proxyCall()
    }

    private suspend fun <T> createFirst(
        requestId: String,
        directCall: suspend () -> T,
        proxyCall: suspend () -> T,
    ): T {
        val startedAt = monotonicMillis()
        sendLogger("create_route request_id=$requestId event=direct_start elapsed_ms=0")
        return try {
            directCall().also {
                onRoute(false, phoneReachable())
                sendLogger("create_route request_id=$requestId event=direct_accepted elapsed_ms=${monotonicMillis() - startedAt}")
            }
        } catch (error: Throwable) {
            if (!error.isDirectTransportFailure()) throw error
            val phone = phoneReachable(force = true)
            onRoute(true, phone)
            sendLogger(
                "create_route request_id=$requestId event=proxy_start elapsed_ms=${monotonicMillis() - startedAt} reason=${error.javaClass.simpleName}",
            )
            proxyCall().also {
                sendLogger("create_route request_id=$requestId event=proxy_accepted elapsed_ms=${monotonicMillis() - startedAt}")
            }
        }
    }
}

// How long a direct send may take before the phone proxy is used instead.
//
// It must cover a real mobile round trip: an accepted send only queues a job, but
// on a weak link the body itself can take many seconds to arrive. 1.2 s made a
// healthy-but-waking network look unavailable and turned an outbox item into a
// false red error; 5 s was still short of a bad mobile round trip.
private const val DIRECT_SEND_BUDGET_MS = 25_000L
private const val DIRECT_RECOVERY_BUDGET_MS = 5_000L
private const val PROXY_SEND_BUDGET_MS = 8_000L

/**
 * A Data Layer capability query is a Play Services round trip that can outlive a
 * visible screen. It must never decide how long a chat list takes to appear, so
 * it is capped and its answer is reused for [PHONE_PROBE_TTL_MS].
 */
private const val PHONE_PROBE_TIMEOUT_MS = 700L
private const val PHONE_PROBE_TTL_MS = 60_000L
private const val NODE_RESOLVE_TIMEOUT_MS = 2_000L
private const val TAG = "WristMindWear"

private fun monotonicMillis(): Long = System.nanoTime() / 1_000_000L

internal fun Throwable.isDirectTransportFailure(): Boolean = this is IOException && this !is WristMindApiException
