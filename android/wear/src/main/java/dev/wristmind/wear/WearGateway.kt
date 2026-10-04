package dev.wristmind.wear

import android.os.SystemClock
import android.util.Log
import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import dev.wristmind.core.ChatSourceCandidate
import dev.wristmind.core.DeviceToken
import dev.wristmind.core.FallbackAnswer
import dev.wristmind.core.FallbackTicket
import dev.wristmind.core.Job
import dev.wristmind.core.Mode
import dev.wristmind.core.ServerEvent
import dev.wristmind.core.WristMindApi
import kotlinx.coroutines.flow.Flow
import okhttp3.Call
import okhttp3.Connection
import okhttp3.EventListener
import okhttp3.OkHttpClient
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Proxy
import java.util.concurrent.TimeUnit

internal const val WEAR_HISTORY_PAGE_SIZE = 60

interface WearGateway {
    suspend fun health(): Boolean
    suspend fun enroll(code: String): DeviceToken
    suspend fun registerPushToken(token: String)
    suspend fun fallbackTicket(): FallbackTicket
    suspend fun modes(): List<Mode>
    suspend fun chats(): List<Chat>
    suspend fun createChat(modeId: String, clientRequestId: String): Chat
    suspend fun createQuickChat(clientRequestId: String): Chat
    suspend fun deleteChat(chatId: String)
    suspend fun messages(chatId: String): List<ChatMessage>
    suspend fun sendMessage(chatId: String, requestId: String, text: String, webSearch: Boolean, webResearch: Boolean = false, researchMode: Boolean = false): Job
    suspend fun syncFallbackMessage(chatId: String, requestId: String, userText: String, assistantText: String): String
    suspend fun job(jobId: String): Job
    suspend fun cancelJob(jobId: String): Job
    suspend fun chatSourceCandidates(chatId: String): List<ChatSourceCandidate>
    suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String): Job
    suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String)
    fun events(jobId: String, after: Long): Flow<ServerEvent>
}

class DirectWearGateway(
    private val baseUrl: () -> String,
    private val token: () -> String,
) : WearGateway {
    /**
     * Reads (lists, messages, health) on a watch that mostly lives on mobile data.
     *
     * A 2 s connect / 10 s call budget treated a waking radio as a dead network:
     * the request was aborted, reported as a transport failure and replayed through
     * the phone proxy, which is far slower than simply waiting a little longer.
     */
    private val interactiveClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .eventListenerFactory { WearSendTimingListener() }
        .build()

    /**
     * Message sends. The POST only queues a job and returns 202, but the body has to
     * cross a weak mobile link first, so the budget is wider than a single radio
     * wake-up.
     */
    private val sendClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .callTimeout(40, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .eventListenerFactory { WearSendTimingListener() }
        .build()

    private val streamingClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(2, TimeUnit.MINUTES)
        .retryOnConnectionFailure(true)
        .eventListenerFactory { WearSendTimingListener() }
        .build()

    /**
     * Creating a chat is a write, exactly like sending a message. The interactive
     * client's short connect budget aborted a request while the watch radio was
     * still waking, which pushed the create onto the phone proxy and its 25-second
     * RPC timeout — the "chat creates, but the screen spins for 30 seconds" case.
     */
    private val createClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .eventListenerFactory { WearSendTimingListener() }
        .build()

    private fun authorized() = WristMindApi(baseUrl(), token(), interactiveClient)
    private fun sendAuthorized() = WristMindApi(baseUrl(), token(), sendClient)
    private fun createAuthorized() = WristMindApi(baseUrl(), token(), createClient)
    private fun streamingAuthorized() = WristMindApi(baseUrl(), token(), streamingClient)

    override suspend fun health() = WristMindApi(baseUrl(), client = interactiveClient).health()

    override suspend fun enroll(code: String) = WristMindApi(baseUrl(), client = interactiveClient).enrollWatch(
        name = "Xiaomi Watch 2",
        code = code,
    )

    override suspend fun registerPushToken(token: String) = authorized().registerPushToken(token)
    override suspend fun fallbackTicket() = authorized().fallbackTicket()

    override suspend fun modes() = authorized().modes()
    override suspend fun chats() = authorized().chats()
    override suspend fun createChat(modeId: String, clientRequestId: String) =
        createAuthorized().createChat(modeId, clientRequestId)
    override suspend fun createQuickChat(clientRequestId: String) = createAuthorized().createQuickChat(clientRequestId)
    override suspend fun deleteChat(chatId: String) = authorized().deleteChat(chatId)
    override suspend fun messages(chatId: String) = authorized().messages(chatId, WEAR_HISTORY_PAGE_SIZE)
    override suspend fun sendMessage(chatId: String, requestId: String, text: String, webSearch: Boolean, webResearch: Boolean, researchMode: Boolean) =
        sendAuthorized().sendMessage(chatId, requestId, text, webSearch, webResearch, researchMode)
    override suspend fun syncFallbackMessage(chatId: String, requestId: String, userText: String, assistantText: String) =
        sendAuthorized().syncFallbackMessage(chatId, requestId, userText, assistantText)

    override suspend fun job(jobId: String) = authorized().job(jobId)
    override suspend fun cancelJob(jobId: String) = authorized().cancelJob(jobId)
    override suspend fun chatSourceCandidates(chatId: String) = authorized().chatSourceCandidates(chatId)
    override suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String) =
        sendAuthorized().saveChatSourceCandidate(chatId, candidateId, requestId)
    override suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String) =
        authorized().dismissChatSourceCandidate(chatId, candidateId)
    override fun events(jobId: String, after: Long) = streamingAuthorized().events(jobId, after)
        .also { WearAnswerTrace.log("sse_route", "route" to "direct", "job_id" to jobId, "after" to after) }
}

class FallbackWearClient(
    private val baseUrl: () -> String,
    private val ticket: () -> String,
) {
    private val healthClient = OkHttpClient.Builder()
        // Also reached from a watch on mobile data: a 4 s budget reported "fallback
        // unavailable" while the radio was still waking.
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .callTimeout(12, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
    private val answerClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(100, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .callTimeout(105, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    suspend fun health(): Boolean = WristMindApi(baseUrl(), client = healthClient).fallbackHealth()

    suspend fun respond(
        requestId: String,
        chatId: String,
        modeName: String,
        systemPrompt: String,
        history: List<ChatMessage>,
        text: String,
        requestedWebSearch: Boolean,
    ): FallbackAnswer = WristMindApi(baseUrl(), ticket(), answerClient).fallbackRespond(
        requestId, chatId, modeName, systemPrompt, history, text, requestedWebSearch,
    )
}

private class WearSendTimingListener : EventListener() {
    private val startedAt = SystemClock.elapsedRealtime()
    private fun requestId(call: Call) = call.request().tag(String::class.java)
    private fun log(call: Call, event: String, suffix: String = "") {
        val requestId = requestId(call) ?: return
        val line = "wear_transport request_id=$requestId event=$event elapsed_ms=${SystemClock.elapsedRealtime() - startedAt}$suffix"
        Log.i(TAG, line)
        WearDiagnosticLog.record("transport", line)
    }

    override fun callStart(call: Call) = log(call, "call_start")

    override fun dnsStart(call: Call, domainName: String) = log(call, "dns_start", " host=$domainName")
    override fun dnsEnd(call: Call, domainName: String, inetAddressList: List<InetAddress>) =
        log(call, "dns_end", " addresses=${inetAddressList.size}")
    override fun connectStart(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy) =
        log(call, "connect_start", " address=$inetSocketAddress")
    override fun secureConnectStart(call: Call) = log(call, "tls_start")
    override fun secureConnectEnd(call: Call, handshake: okhttp3.Handshake?) = log(call, "tls_end")
    override fun connectionAcquired(call: Call, connection: Connection) =
        log(call, "connection_acquired", " protocol=${connection.protocol()}")
    override fun responseHeadersEnd(call: Call, response: okhttp3.Response) =
        log(call, "response_headers", " status=${response.code}")
    override fun callEnd(call: Call) = log(call, "call_end")
    override fun callFailed(call: Call, ioe: java.io.IOException) =
        log(call, "call_failed", " error=${ioe.javaClass.simpleName}")

    private companion object {
        const val TAG = "WristMindWear"
    }
}

internal object WearRetryPolicy {
    const val MAX_SEND_ATTEMPTS = 3
    const val SEND_RETRY_DELAY_MS = 1_000L
    const val MAX_STREAM_RECONNECTS = 3
    val BACKOFF_MS = longArrayOf(500, 1_000, 2_000)
}
