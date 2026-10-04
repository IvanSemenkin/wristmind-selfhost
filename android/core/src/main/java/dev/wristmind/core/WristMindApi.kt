package dev.wristmind.core

import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class WristMindApi(
    baseUrl: String,
    private val token: String? = null,
    private val client: OkHttpClient = sharedClient,
) {
    private val root = baseUrl.trim().trimEnd('/')

    init {
        require(root.startsWith("http://") || root.startsWith("https://")) {
            "Адрес сервера должен начинаться с http:// или https://"
        }
    }

    suspend fun health(): Boolean = request("/health").optString("status") == "ok"


    suspend fun enrollAdmin(name: String, bootstrapSecret: String): DeviceToken {
        val body = JSONObject().put("name", name).put("kind", "PHONE")
        return parseDeviceToken(request("/v1/devices/admin/enroll", "POST", body) {
            header("X-WristMind-Bootstrap", bootstrapSecret)
        })
    }

    suspend fun createPairingCode(): PairingCode {
        val json = request("/v1/devices/pairing-codes", "POST", JSONObject())
        return PairingCode(json.getString("code"), json.getString("expires_at"))
    }

    suspend fun models(): List<ModelOption> = requestArray("/v1/models").map { json ->
        ModelOption(json.getString("id"), json.getString("label"), json.getString("provider"))
    }

    suspend fun globalPrompt(): String =
        request("/v1/settings").getString("global_system_prompt")

    suspend fun updateGlobalPrompt(prompt: String): String {
        val body = JSONObject().put("global_system_prompt", prompt)
        return request("/v1/settings", "PUT", body).getString("global_system_prompt")
    }

    suspend fun enrollWatch(name: String, code: String): DeviceToken {
        val body = JSONObject().put("name", name).put("kind", "WATCH").put("code", code)
        return parseDeviceToken(request("/v1/devices/enroll", "POST", body))
    }

    suspend fun revokeSelf() {
        request("/v1/devices/self", "DELETE")
    }

    suspend fun registerPushToken(token: String) {
        request("/v1/devices/self/push-token", "PUT", JSONObject().put("token", token))
    }

    suspend fun fallbackTicket(): FallbackTicket {
        val json = request("/v1/devices/self/fallback-ticket")
        return FallbackTicket(json.getString("ticket"), json.getString("expires_at"))
    }

    suspend fun modes(): List<Mode> = requestArray("/v1/modes").map(::parseMode)

    suspend fun createMode(
        name: String,
        systemPrompt: String,
        modelId: String = "openrouter:google/gemini-2.5-flash-lite",
    ): Mode {
        val body = JSONObject()
            .put("name", name)
            .put("color", "#65F5C2")
            .put("icon", "spark")
            .put("system_prompt", systemPrompt)
            .put("response_model_id", modelId)
        return parseMode(request("/v1/modes", "POST", body))
    }

    suspend fun chats(): List<Chat> = requestArray("/v1/chats").map(::parseChat)

    suspend fun createChat(
        modeId: String,
        clientRequestId: String,
        title: String = "Новый чат",
    ): Chat {
        val body = JSONObject()
            .put("mode_id", modeId)
            .put("title", title)
            .put("client_request_id", clientRequestId)
        return parseChat(request("/v1/chats", "POST", body) {
            tag(String::class.java, "create_chat:$clientRequestId")
        })
    }

    suspend fun createQuickChat(clientRequestId: String): Chat = parseChat(
        request(
            "/v1/chats/quick",
            "POST",
            JSONObject().put("client_request_id", clientRequestId),
        ) {
            tag(String::class.java, "create_quick_chat:$clientRequestId")
        },
    )

    suspend fun deleteChat(chatId: String) {
        request("/v1/chats/$chatId", "DELETE")
    }

    suspend fun messages(chatId: String, limit: Int? = null): List<ChatMessage> {
        val query = limit?.let { "?limit=$it" }.orEmpty()
        return requestArray("/v1/chats/$chatId/messages$query").map(::parseMessage)
    }

    suspend fun sendMessage(
        chatId: String,
        requestId: String,
        text: String,
        webSearch: Boolean = false,
        webResearch: Boolean = false,
        researchMode: Boolean = false,
    ): Job {
        val body = JSONObject()
            .put("client_request_id", requestId)
            .put("text", text)
            .put("web_search", webSearch)
            .put("web_research", webResearch)
            .put("research_mode", researchMode)
        val json = request("/v1/chats/$chatId/messages", "POST", body) {
            tag(String::class.java, requestId)
            header("X-WristMind-Client-Sent-Ms", System.currentTimeMillis().toString())
        }
        return Job(json.getString("id"), json.getString("status"))
    }

    suspend fun syncFallbackMessage(
        chatId: String,
        requestId: String,
        userText: String,
        assistantText: String,
    ): String {
        val body = JSONObject()
            .put("request_id", requestId)
            .put("user_text", userText)
            .put("assistant_text", assistantText)
        return request("/v1/chats/$chatId/fallback-messages", "POST", body).getString("status")
    }

    suspend fun fallbackHealth(): Boolean =
        request("/fallback/health").optString("status") == "ok"

    suspend fun fallbackRespond(
        requestId: String,
        chatId: String,
        modeName: String,
        systemPrompt: String,
        history: List<ChatMessage>,
        text: String,
        requestedWebSearch: Boolean,
    ): FallbackAnswer {
        val historyJson = JSONArray()
        history.forEach { message ->
            if (message.role == "user" || message.role == "assistant") {
                historyJson.put(
                    JSONObject()
                        .put("role", message.role)
                        .put("content", message.content),
                )
            }
        }
        val body = JSONObject()
            .put("request_id", requestId)
            .put("chat_id", chatId)
            .put("mode_name", modeName)
            .put("system_prompt", systemPrompt)
            .put("history", historyJson)
            .put("text", text)
            .put("requested_web_search", requestedWebSearch)
        val json = request("/fallback/v1/respond", "POST", body)
        return FallbackAnswer(
            requestId = json.getString("request_id"),
            answer = json.getString("answer"),
            degraded = json.optBoolean("degraded", true),
            sourcesAvailable = json.optBoolean("sources_available", false),
        )
    }

    suspend fun job(jobId: String): Job {
        val json = request("/v1/jobs/$jobId")
        return Job(json.getString("id"), json.getString("status"))
    }

    suspend fun cancelJob(jobId: String): Job {
        val json = request("/v1/jobs/$jobId/cancel", "POST")
        return Job(json.getString("id"), json.getString("status"))
    }

    suspend fun chatSourceCandidates(chatId: String): List<ChatSourceCandidate> =
        requestArray("/v1/chats/$chatId/source-candidates").map(::parseChatSourceCandidate)

    suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String): Job {
        val json = request(
            "/v1/chats/$chatId/source-candidates/$candidateId/save",
            "POST",
            JSONObject().put("client_request_id", requestId),
        )
        return Job(json.getString("id"), json.getString("status"))
    }

    suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String) {
        request("/v1/chats/$chatId/source-candidates/$candidateId", "DELETE")
    }

    /**
     * Diagnostic-only latency event. The server records it and never returns
     * anything the caller needs, so a failure is unimportant by design.
     */
    suspend fun reportLatency(payload: JSONObject) {
        request("/v1/diagnostics/latency", "POST", payload)
    }

    suspend fun knowledge(modeId: String? = null): List<KnowledgeSource> {
        val suffix = modeId?.let { "?mode_id=$it" }.orEmpty()
        return requestArray("/v1/knowledge$suffix").map(::parseKnowledge)
    }

    suspend fun uploadKnowledge(
        modeId: String,
        processingMode: String,
        title: String,
        filename: String,
        mediaType: String,
        bytes: ByteArray,
        requestId: String,
    ): Job = withContext(Dispatchers.IO) {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("mode_id", modeId)
            .addFormDataPart("processing_mode", processingMode)
            .addFormDataPart("client_request_id", requestId)
            .addFormDataPart("title", title)
            .addFormDataPart("file", filename, bytes.toRequestBody(mediaType.toMediaType()))
            .build()
        val request = authorized(Request.Builder().url("$root/v1/knowledge"))
            .post(body)
            .build()
        execute(request).use { response ->
            val text = response.body?.string().orEmpty()
            ensureSuccess(response, text)
            val json = JSONObject(text)
            Job(json.getString("id"), json.getString("status"))
        }
    }

    fun events(jobId: String, after: Long = 0): Flow<ServerEvent> = callbackFlow {        val request = authorized(Request.Builder().url("$root/v1/jobs/$jobId/events?after=$after"))
            .header("Accept", "text/event-stream")
            .tag(String::class.java, "sse:$jobId")
            .build()
        val source = EventSources.createFactory(client).newEventSource(
            request,
            object : EventSourceListener() {
                override fun onEvent(source: EventSource, id: String?, type: String?, data: String) {
                    trySend(ServerEvent(id?.toLongOrNull() ?: 0, type ?: "message", data))
                }

                override fun onFailure(
                    source: EventSource,
                    throwable: Throwable?,
                    response: Response?,
                ) {
                    close(
                        response?.let { WristMindApiException(it.code, "SSE HTTP ${it.code}") }
                            ?: throwable
                            ?: IOException("SSE connection failed"),
                    )
                }

                override fun onClosed(source: EventSource) {
                    close()
                }
            },
        )
        awaitClose { source.cancel() }
    }

    private suspend fun requestArray(path: String): List<JSONObject> = withContext(Dispatchers.IO) {
        execute(Request.Builder().url(root + path).let(::authorized).build()).use { response ->
            val text = response.body?.string().orEmpty()
            ensureSuccess(response, text)
            val array = JSONArray(text)
            List(array.length()) { array.getJSONObject(it) }
        }
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        customize: Request.Builder.() -> Unit = {},
    ): JSONObject = withContext(Dispatchers.IO) {
        val builder = authorized(Request.Builder().url(root + path)).apply(customize)
        if (method != "GET") {
            builder.method(
                method,
                (body ?: JSONObject()).toString().toRequestBody(JSON_MEDIA_TYPE),
            )
        }
        execute(builder.build()).use { response ->
            val text = response.body?.string().orEmpty()
            ensureSuccess(response, text)
            if (text.isBlank()) JSONObject() else JSONObject(text)
        }
    }

    /**
     * OkHttp's synchronous execute() cannot be interrupted by a coroutine timeout.
     * Keeping this call cancellable lets Wear fall back promptly without leaving a
     * network request running after the user-visible operation has moved on.
     */
    private suspend fun execute(request: Request): Response = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(request)
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: okhttp3.Call, error: IOException) {
                if (continuation.isActive) continuation.resumeFailure(error)
            }

            override fun onResponse(call: okhttp3.Call, response: Response) {
                if (continuation.isActive) {
                    continuation.resumeResponse(response)
                } else {
                    response.close()
                }
            }
        })
    }

    private fun CancellableContinuation<Response>.resumeResponse(response: Response) {
        resume(response, onCancellation = { _, value, _ -> value.close() })
    }

    private fun CancellableContinuation<*>.resumeFailure(error: Throwable) {
        resumeWith(Result.failure(error))
    }

    private fun authorized(builder: Request.Builder): Request.Builder = builder.apply {
        token?.takeIf(String::isNotBlank)?.let { header("Authorization", "Bearer $it") }
    }

    private fun ensureSuccess(response: Response, text: String) {
        if (!response.isSuccessful) {
            throw WristMindApiException(response.code, userFacingHttpError(response.code, text))
        }
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        private val sharedClient: OkHttpClient by lazy(::defaultClient)

        private fun defaultClient() = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.MINUTES)
            .writeTimeout(2, TimeUnit.MINUTES)
            .retryOnConnectionFailure(true)
            .build()

        private fun parseDeviceToken(json: JSONObject) = DeviceToken(
            json.getString("device_id"), json.getString("token"), json.getBoolean("is_admin"),
        )

        private fun parseMode(json: JSONObject) = Mode(
            id = json.getString("id"),
            name = json.getString("name"),
            color = json.getString("color"),
            icon = json.getString("icon"),
            systemPrompt = json.optString("system_prompt"),
            responseModelId = json.getString("response_model_id"),
            hiddenOnWatch = json.optBoolean("hidden_on_watch"),
        )

        private fun parseChat(json: JSONObject) = Chat(
            id = json.getString("id"),
            modeId = json.getString("mode_id"),
            modeName = json.getString("mode_name"),
            modeDeleted = json.optBoolean("mode_deleted"),
            title = json.getString("title"),
        )

        private fun parseMessage(json: JSONObject) = ChatMessage(
            id = json.getString("id"),
            role = json.getString("role"),
            content = json.optString("content"),
            status = json.optString("status"),
        )

        private fun parseChatSourceCandidate(json: JSONObject) = ChatSourceCandidate(
            id = json.getString("id"),
            title = json.getString("title"),
            url = json.getString("url"),
            preview = json.optString("preview"),
            content = json.optString("content"),
            truncated = json.optBoolean("truncated"),
        )

        private fun parseKnowledge(json: JSONObject) = KnowledgeSource(
            id = json.getString("id"),
            modeId = json.getString("mode_id"),
            title = json.getString("title"),
            filename = json.getString("filename"),
            processingMode = json.getString("processing_mode"),
            status = json.getString("status"),
            pageCount = json.optInt("page_count"),
            chunkCount = json.optInt("chunk_count"),
        )
    }
}

class WristMindApiException(val statusCode: Int, message: String) : IOException(message)

internal fun userFacingHttpError(statusCode: Int, responseText: String): String {
    val detail = runCatching { JSONObject(responseText).optString("detail") }
        .getOrNull()
        .orEmpty()
        .trim()
    if (detail.isNotBlank() && !detail.looksLikeHtml()) return detail
    return when (statusCode) {
        408 -> "Сервер не успел ответить. Попробуйте ещё раз"
        429 -> "Слишком много запросов. Попробуйте чуть позже"
        in 500..599 -> "Сервер временно недоступен. Попробуйте ещё раз"
        else -> "Ошибка сервера ($statusCode)"
    }
}

private fun String.looksLikeHtml(): Boolean {
    val normalized = trimStart().lowercase()
    return normalized.startsWith("<") || "<html" in normalized || "<!doctype" in normalized
}
