package dev.wristmind.wear

import android.app.Application
import android.os.SystemClock
import android.util.Log
import android.widget.Toast
import com.google.firebase.messaging.FirebaseMessaging
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import dev.wristmind.core.ChatSourceCandidate
import dev.wristmind.core.DeviceConfig
import dev.wristmind.core.DeviceConfigStore
import dev.wristmind.core.Mode
import dev.wristmind.core.ServerEvent
import dev.wristmind.core.WristMindApiException
import dev.wristmind.core.WristMindApi
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.tasks.await
import kotlin.coroutines.coroutineContext
import org.json.JSONObject

enum class ProcessingStage {
    DISCONNECTED,
    READY,
    SENDING,
    WAITING,
    CONTEXT,
    ROUTING,
    USING_CHAT_SOURCE,
    FRAMING_REQUEST,
    SOURCE_INTENT,
    SEARCH_QUERY,
    SEARCHING,
    REVIEWING_SOURCES,
    OPENING_SOURCE,
    EVALUATING_SOURCE,
    EXTRACTING_SOURCE,
    SAVING_SOURCE,
    SEARCH_NO_RESULTS,
    SEARCH_UNAVAILABLE,
    RESEARCH_DRAFTING,
    RESEARCH_CHECKING,
    RESEARCH_REFINING,
    GENERATING,
    FALLBACK_GENERATING,
    COMPLETE,
    ERROR,
}

/** Keep protocol names out of the chat UI; an unknown future state must not rewind progress. */
internal fun processingStageFromServerState(state: String): ProcessingStage? = when (state) {
    "queued" -> ProcessingStage.WAITING
    "context" -> ProcessingStage.CONTEXT
    "routing" -> ProcessingStage.ROUTING
    "using_chat_source" -> ProcessingStage.USING_CHAT_SOURCE
    "framing_request" -> ProcessingStage.FRAMING_REQUEST
    "source_intent" -> ProcessingStage.SOURCE_INTENT
    "search_query" -> ProcessingStage.SEARCH_QUERY
    "searching" -> ProcessingStage.SEARCHING
    "reviewing_sources" -> ProcessingStage.REVIEWING_SOURCES
    "opening_source" -> ProcessingStage.OPENING_SOURCE
    "evaluating_source" -> ProcessingStage.EVALUATING_SOURCE
    "extracting_source" -> ProcessingStage.EXTRACTING_SOURCE
    "saving_source" -> ProcessingStage.SAVING_SOURCE
    "search_no_results" -> ProcessingStage.SEARCH_NO_RESULTS
    "search_unavailable" -> ProcessingStage.SEARCH_UNAVAILABLE
    "research_drafting" -> ProcessingStage.RESEARCH_DRAFTING
    "research_checking" -> ProcessingStage.RESEARCH_CHECKING
    "research_refining" -> ProcessingStage.RESEARCH_REFINING
    "generating" -> ProcessingStage.GENERATING
    else -> null
}

data class WearState(
    val serverUrl: String = BuildConfig.WRISTMIND_BASE_URL,
    val pairCode: String = "",
    val paired: Boolean = false,
    val stage: ProcessingStage = ProcessingStage.DISCONNECTED,
    val progressOrdinal: Int? = null,
    val vpsConnected: Boolean = false,
    val fallbackActive: Boolean = false,
    val phoneConnected: Boolean = false,
    val usingProxy: Boolean = false,
    val modes: List<Mode> = emptyList(),
    val chats: List<Chat> = emptyList(),
    val activeChatId: String? = null,
    val messages: List<ChatMessage> = emptyList(),
    val messagesChatId: String? = null,
    val contentChatId: String? = null,
    val draft: String = "",
    val answerSearchMode: AnswerSearchMode = AnswerSearchMode.AUTO,
    val pendingQuestion: String = "",
    val pendingBaseMessageId: String? = null,
    val streamingAnswer: String = "",
    val selectedAnswerId: String? = null,
    val selectedAnswerText: String = "",
    val loading: Boolean = false,
    /**
     * A chat creation is in flight. Separate from [loading] on purpose: a
     * background refresh keeps [loading] true for a whole chain of requests, and
     * gating the picker on it made every mode button dead for that time.
     */
    val creatingChat: Boolean = false,
    val error: String? = null,
    val sourceCandidates: List<ChatSourceCandidate> = emptyList(),
    val savingSourceCandidateId: String? = null,
    val sourceSaveError: String? = null,
) {
    val operationActive: Boolean
        get() = stage in setOf(
            ProcessingStage.SENDING,
            ProcessingStage.WAITING,
            ProcessingStage.CONTEXT,
            ProcessingStage.ROUTING,
            ProcessingStage.USING_CHAT_SOURCE,
            ProcessingStage.FRAMING_REQUEST,
            ProcessingStage.SOURCE_INTENT,
            ProcessingStage.SEARCH_QUERY,
            ProcessingStage.SEARCHING,
            ProcessingStage.REVIEWING_SOURCES,
            ProcessingStage.OPENING_SOURCE,
            ProcessingStage.EVALUATING_SOURCE,
            ProcessingStage.EXTRACTING_SOURCE,
            ProcessingStage.SAVING_SOURCE,
            ProcessingStage.SEARCH_NO_RESULTS,
            ProcessingStage.SEARCH_UNAVAILABLE,
            ProcessingStage.RESEARCH_DRAFTING,
            ProcessingStage.RESEARCH_CHECKING,
            ProcessingStage.RESEARCH_REFINING,
            ProcessingStage.GENERATING,
            ProcessingStage.FALLBACK_GENERATING,
        )
}

/** A transient ID lets the full-answer route follow the still-arriving SSE text. */
internal const val STREAMING_ANSWER_ID = "streaming-answer"

internal fun selectedAnswerContent(state: WearState): String = when (state.selectedAnswerId) {
    null -> ""
    // A background refresh can receive the completed server message just as the
    // reader is open. Keep the live text as the primary source, but never leave
    // the reader blank during that hand-off.
    STREAMING_ANSWER_ID -> state.streamingAnswer.ifBlank {
        state.selectedAnswerText.ifBlank {
            state.messages.lastOrNull { it.role == "assistant" && it.content.isNotBlank() }?.content.orEmpty()
        }
    }
    else -> state.messages.firstOrNull { it.id == state.selectedAnswerId }?.content
        ?.takeIf(String::isNotBlank)
        ?: state.selectedAnswerText
}

/**
 * Locally completed transcript for one answer, or `null` when there is nothing
 * safe to persist.
 *
 * A blank [streamedAnswer] means the stream never reached this chat (the answer
 * belongs to another chat, or a replica hand-off raced the reader). Persisting
 * then would write an empty assistant message over a complete answer, so the
 * caller must fall back to the server snapshot instead.
 */
internal fun completedMessagesFor(
    cachedMessages: List<ChatMessage>,
    pendingText: String,
    requestId: String,
    streamedAnswer: String,
): List<ChatMessage>? {
    if (streamedAnswer.isBlank()) return null
    val withUser = if (
        cachedMessages.lastOrNull()?.role == "user" &&
        cachedMessages.last().content == pendingText
    ) {
        cachedMessages
    } else {
        cachedMessages + ChatMessage(
            id = "local-user-$requestId",
            role = "user",
            content = pendingText,
            status = "complete",
        )
    }
    return withUser + ChatMessage(
        id = "local-assistant-$requestId",
        role = "assistant",
        content = streamedAnswer,
        status = "complete",
    )
}

/**
 * State after showing the cached view of [chatId].
 *
 * The full-answer reader is derived state, so it survives when the chat does not
 * actually change: a background refresh for the open chat (an FCM `state_changed`
 * right after the answer completes) must not blank the "Ответ" screen. A real
 * chat switch clears it.
 */
internal fun WearState.showingChat(
    chatId: String,
    cachedMessages: List<ChatMessage>,
    cachedDraft: String,
): WearState {
    val preserveReader = activeChatId == chatId
    return copy(
        activeChatId = chatId,
        messages = cachedMessages,
        messagesChatId = chatId,
        contentChatId = chatId,
        draft = cachedDraft,
        pendingQuestion = if (preserveReader) pendingQuestion else "",
        pendingBaseMessageId = if (preserveReader) pendingBaseMessageId else null,
        streamingAnswer = if (preserveReader) streamingAnswer else "",
        selectedAnswerId = if (preserveReader) selectedAnswerId else null,
        selectedAnswerText = if (preserveReader) selectedAnswerText else "",
        // Never downgrade a running operation to READY: the stage drives both the
        // generation indicator and every "is a refresh safe?" guard.
        stage = if (preserveReader && operationActive) stage else ProcessingStage.READY,
        error = null,
    )
}

class WearViewModel(application: Application) : AndroidViewModel(application) {
    private val configStore = DeviceConfigStore(application, "watch")
    private val localStore = WearLocalStore(application)
    private val saved = configStore.read(BuildConfig.WRISTMIND_BASE_URL)
    private var token = saved.token
    private val configPublisher = WearConfigPublisher(application)
    private val mutableState = MutableStateFlow(
        WearState(
            serverUrl = BuildConfig.WRISTMIND_BASE_URL,
            paired = token.isNotBlank(),
            stage = if (token.isBlank()) ProcessingStage.DISCONNECTED else ProcessingStage.READY,
            answerSearchMode = localStore.answerSearchMode(),
        ),
    )
    private val directGateway = DirectWearGateway(
        baseUrl = { BuildConfig.WRISTMIND_BASE_URL.trimEnd('/') },
        token = { token },
    )
    private val proxyGateway = DataLayerProxyGateway(application)
    private val gateway: WearGateway = FailoverWearGateway(directGateway, proxyGateway) { usingProxy, phoneReachable ->
        mutableState.update { it.copy(usingProxy = usingProxy, phoneConnected = phoneReachable) }
    }
    private val fallbackClient = FallbackWearClient(
        baseUrl = { BuildConfig.WRISTMIND_BASE_URL.trimEnd('/') },
        ticket = { configStore.fallbackTicket() },
    )
    private var chatDeleteSyncRunning = false
    private var refreshListsRunning = false
    private var pushRefreshRunning = false
    private var pushRefreshPending = false
    private var fallbackSyncRunning = false
    // Diagnostic-only latency marks for one send. They never influence routing,
    // retries, rendering or any user-visible behaviour.
    private var latencySendStartElapsedMs: Long? = null
    private var latencySendStartEpochMs: Long? = null
    private var latencyRequestId: String? = null
    private var latencyFirstSseDeltaMs: Long? = null
    private var latencyFirstVisibleTextMs: Long? = null
    private var mainRecoverySuccesses = 0
    private val pushStore = WearPushStore(application)
    private var pushSyncPending = false
    private var firstForeground = true
    private var connectionCheckRunning = false
    private var activeSubmission: PendingSubmission? = null
    private var activeSubmitJob: CoroutineJob? = null
    private var cancelRequestedFor: String? = null
    private var cancellingRequest: String? = null
    val state: StateFlow<WearState> = mutableState

    init {
        WearDiagnosticLog.initialize(application)
        restoreCachedState()
        viewModelScope.launch {
            WearPushEvents.tokenReceived.collect { receivedToken -> registerPushToken(receivedToken) }
        }
        viewModelScope.launch {
            WearPushEvents.syncRequested.collect {
                val operationActive = mutableState.value.operationActive
                WearAnswerTrace.log(
                    "push_sync_requested",
                    "operation_active" to operationActive,
                    "stage" to mutableState.value.stage,
                    "stream_chars" to mutableState.value.streamingAnswer.length,
                    "selected_answer_id_kind" to WearAnswerTrace.idKind(mutableState.value.selectedAnswerId),
                )
                if (operationActive) pushSyncPending = true else refreshFromPush()
            }
        }
        viewModelScope.launch {
            WearConfigEvents.tokenReceived.collect { config ->
                if (token != config.token || mutableState.value.serverUrl != config.serverUrl) {
                    token = config.token
                    configStore.clearFallbackTicket()
                    mutableState.update { it.copy(paired = true, stage = ProcessingStage.READY, error = null) }
                    refreshData()
                }
            }
        }
        if (token.isNotBlank()) {
            syncPendingChatDeletes()
            restorePendingSubmission()
            refresh()
            registerCurrentPushToken()
            if (pushStore.consumeSyncPending()) refreshFromPush()
        }
    }

    fun setPairCode(value: String) {
        mutableState.update { it.copy(pairCode = value.filter(Char::isDigit).take(12), error = null) }
    }

    fun pair() {
        val code = mutableState.value.pairCode
        if (code.length < 6) {
            mutableState.update { it.copy(error = "Введите код из 6 цифр", stage = ProcessingStage.ERROR) }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(loading = true, error = null) }
            runCatching {
                val result = gateway.enroll(code)
                token = result.token
                configStore.save(DeviceConfig(BuildConfig.WRISTMIND_BASE_URL, token))
                configStore.clearFallbackTicket()
                runCatching { configPublisher.publish(BuildConfig.WRISTMIND_BASE_URL, token) }
                mutableState.update { it.copy(paired = true, pairCode = "", stage = ProcessingStage.READY) }
                refreshData()
                registerCurrentPushToken()
            }.onFailure(::handleFailure)
            mutableState.update { it.copy(loading = false) }
        }
    }

    fun refresh() = viewModelScope.launch {
        WearAnswerTrace.log(
            "refresh_triggered",
            "source" to "refresh()",
            "stage" to mutableState.value.stage,
            "stream_chars" to mutableState.value.streamingAnswer.length,
        )
        syncPendingChatDeletes()
        mutableState.update { it.copy(loading = true, error = null) }
        runCatching { refreshData() }.onFailure { error ->
            if (fallbackIsReady()) markFallbackAvailable() else handleFailure(error)
        }
        mutableState.update { it.copy(loading = false) }
    }

    /**
     * Startup already refreshes in init. Later foreground entries are an inexpensive
     * safety net when FCM was delayed by Wear OS or the network was unavailable.
     */
    fun onAppForegrounded() {
        WearAnswerTrace.log(
            "foregrounded",
            "first_foreground" to firstForeground,
            "stage" to mutableState.value.stage,
            "operation_active" to mutableState.value.operationActive,
            "stream_chars" to mutableState.value.streamingAnswer.length,
        )
        if (firstForeground) {
            firstForeground = false
            return
        }
        if (token.isBlank() || mutableState.value.loading || mutableState.value.creatingChat) return
        if (mutableState.value.operationActive) {
            pushSyncPending = true
            return
        }
        refreshFromPush()
    }

    /** Updates only the availability indicator; it never reloads chats or messages. */
    fun refreshServerConnectionStatus() {
        if (token.isBlank() || connectionCheckRunning) return
        connectionCheckRunning = true
        viewModelScope.launch {
            try {
                val mainAvailable = runCatching { gateway.health() }.getOrDefault(false)
                if (mainAvailable) {
                    mainRecoverySuccesses += 1
                    synchronizeFallbackIfNeeded()
                    val fallbackPending = localStore.offlineChats().isNotEmpty() ||
                        localStore.fallbackExchanges().isNotEmpty()
                    mutableState.update {
                        it.copy(
                            vpsConnected = true,
                            fallbackActive = it.fallbackActive && (
                                mainRecoverySuccesses < MAIN_RECOVERY_CONFIRMATIONS || fallbackPending
                            ),
                        )
                    }
                } else {
                    mainRecoverySuccesses = 0
                    val fallbackAvailable = configStore.fallbackTicket().isNotBlank() &&
                        runCatching { fallbackClient.health() }.getOrDefault(false)
                    mutableState.update {
                        it.copy(vpsConnected = fallbackAvailable, fallbackActive = fallbackAvailable)
                    }
                }
            } finally {
                connectionCheckRunning = false
            }
        }
    }

    fun selectChat(chatId: String) = viewModelScope.launch {
        showLocalChat(chatId)
        mutableState.update { it.copy(loading = true, error = null) }
        if (localStore.offlineChats().none { it.chatId == chatId }) {
            runCatching { loadChat(chatId) }.onFailure { error ->
                if (fallbackIsReady()) markFallbackAvailable() else handleFailure(error)
            }
        }
        mutableState.update { it.copy(loading = false) }
    }

    fun dismissSourceCandidate(candidateId: String) {
        val chatId = mutableState.value.activeChatId ?: return
        mutableState.update { it.copy(sourceCandidates = it.sourceCandidates.filterNot { item -> item.id == candidateId }) }
        viewModelScope.launch { runCatching { gateway.dismissChatSourceCandidate(chatId, candidateId) } }
    }

    fun saveSourceCandidate(candidateId: String) {
        val chatId = mutableState.value.activeChatId ?: return
        if (mutableState.value.savingSourceCandidateId != null) return
        viewModelScope.launch {
            mutableState.update { it.copy(savingSourceCandidateId = candidateId, sourceSaveError = null) }
            runCatching {
                val job = gateway.saveChatSourceCandidate(chatId, candidateId, UUID.randomUUID().toString())
                repeat(60) {
                    when (gateway.job(job.id).status) {
                        "complete" -> return@runCatching
                        "failed" -> throw IOException("Не удалось сохранить источник")
                    }
                    delay(1_000)
                }
                throw IOException("Источник ещё обрабатывается. Он останется в этом чате")
            }.onSuccess {
                mutableState.update { state -> state.copy(sourceCandidates = state.sourceCandidates.filterNot { it.id == candidateId }, sourceSaveError = null) }
            }.onFailure { error -> mutableState.update { it.copy(sourceSaveError = error.message ?: "Не удалось сохранить источник") } }
            mutableState.update { it.copy(savingSourceCandidateId = null) }
        }
    }

    fun createChat(modeId: String, onCreated: () -> Unit) {
        if (mutableState.value.creatingChat) return
        viewModelScope.launch {
            mutableState.update { it.copy(creatingChat = true, error = null) }
            val requestId = UUID.randomUUID().toString()
            runCatching {
                val chat = gateway.createChat(modeId, requestId)
                openCreatedChat(chat)
                onCreated()
                finishChatCreation()
            }.onFailure { error ->
                mutableState.update { it.copy(creatingChat = false) }
                if (isRetryableSendFailure(error) && fallbackIsReady()) {
                    createOfflineChat(modeId, requestId, quick = false)?.let { chat ->
                        openCreatedChat(chat)
                        onCreated()
                    } ?: handleFailure(error)
                } else handleFailure(error)
            }
        }
    }

    fun createQuickChat(onCreated: () -> Unit) {
        if (mutableState.value.creatingChat) return
        viewModelScope.launch {
            mutableState.update { it.copy(creatingChat = true, error = null) }
            val requestId = UUID.randomUUID().toString()
            runCatching {
                val chat = gateway.createQuickChat(requestId)
                openCreatedChat(chat)
                onCreated()
                finishChatCreation()
            }.onFailure { error ->
                mutableState.update { it.copy(creatingChat = false) }
                if (isRetryableSendFailure(error) && fallbackIsReady()) {
                    createOfflineChat("", requestId, quick = true)?.let { chat ->
                        openCreatedChat(chat)
                        onCreated()
                    } ?: handleFailure(error)
                } else handleFailure(error)
            }
        }
    }

    /**
     * Releases the create lock as soon as the chat exists and is on screen. The
     * list refresh continues in the background: it used to keep the picker
     * disabled (and drop every tap) while several more requests ran.
     */
    private fun finishChatCreation() {
        mutableState.update { it.copy(creatingChat = false) }
        viewModelScope.launch {
            runCatching { refreshLists() }
                .onFailure { Log.w(TAG, "Background chat list refresh failed", it) }
        }
    }

    fun deleteChat(chatId: String) {
        val current = mutableState.value
        if (current.chats.none { it.id == chatId }) return
        if (localStore.offlineChats().none { it.chatId == chatId }) {
            localStore.enqueueChatDelete(chatId)
        }
        localStore.clearChat(chatId)
        val remainingChats = current.chats.filterNot { it.id == chatId }
        localStore.saveChats(remainingChats)
        val deletedActiveChat = current.activeChatId == chatId
        mutableState.update {
            if (deletedActiveChat) {
                it.copy(
                    chats = remainingChats,
                    activeChatId = null,
                    messages = emptyList(),
                    messagesChatId = null,
                    contentChatId = null,
                    draft = "",
                    pendingQuestion = "",
                    pendingBaseMessageId = null,
                    streamingAnswer = "",
                    selectedAnswerId = null,
                    selectedAnswerText = "",
                    stage = ProcessingStage.READY,
                    error = null,
                )
            } else {
                it.copy(chats = remainingChats, error = null)
            }
        }
        syncPendingChatDeletes()
    }

    fun updateDraft(value: String) {
        val chatId = mutableState.value.activeChatId ?: return
        localStore.saveDraft(chatId, value)
        val pending = localStore.pending(chatId)
        if (pending != null && pending.text != value) localStore.clearPending(chatId)
        mutableState.update { it.copy(draft = value, error = null, stage = stageAfterEditing(it.stage)) }
    }

    fun toggleWebSearch() {
        val next = mutableState.value.answerSearchMode.next()
        localStore.saveAnswerSearchMode(next)
        mutableState.update { it.copy(answerSearchMode = next) }
    }

    fun applyRecognizedSpeech(draftBeforeSpeech: String, transcript: String) {
        if (transcript.isBlank()) return
        updateDraft(VoiceDraftComposer(draftBeforeSpeech).merge(transcript))
    }

    fun sendDraft() {
        val current = mutableState.value
        val chatId = current.activeChatId ?: return
        val text = current.draft.trim()
        if (text.isBlank() || current.operationActive) return
        val tappedAt = SystemClock.elapsedRealtime()        // A timeout can happen after the server has already accepted the POST. Reuse the
        // durable request ID for the same failed text, so the server returns that job
        // instead of treating a second Send tap as a second question.
        val retry = localStore.pending(chatId)?.takeIf { pending ->
            pending.text == text && pending.state in setOf(
                SubmissionState.QUEUED,
                SubmissionState.FAILED,
            )
        }
        val pending = retry?.copy(
            jobId = null,
            cursor = 0,
            state = SubmissionState.QUEUED,
        ) ?: PendingSubmission(
            chatId = chatId,
            requestId = UUID.randomUUID().toString(),
            text = text,
            jobId = null,
            cursor = 0,
            state = SubmissionState.QUEUED,
            baseMessageId = current.messages.takeIf { current.messagesChatId == chatId }?.lastOrNull()?.id,
            webSearch = current.answerSearchMode.webSearch,
            webResearch = current.answerSearchMode.webResearch,
            researchMode = current.answerSearchMode.researchMode,
        )
        activeSubmission = pending
        cancelRequestedFor = null
        logSendTiming("send_timing request_id=${pending.requestId} event=tap elapsed_ms=0")
        mutableState.update {
            current.copy(
                draft = "",
                pendingQuestion = text,
                pendingBaseMessageId = pending.baseMessageId,
                streamingAnswer = "",
                contentChatId = chatId,
                stage = ProcessingStage.SENDING,
                error = null,
            )
        }
        // Diagnostic-only: open a fresh latency trace for this send. The normal
        // outbox write stays on Dispatchers.IO and is not awaited here.
        latencySendStartElapsedMs = tappedAt
        latencySendStartEpochMs = System.currentTimeMillis()
        latencyRequestId = pending.requestId
        latencyFirstSseDeltaMs = null
        latencyFirstVisibleTextMs = null
        // Persisting the outbox must survive process death, but it must not postpone
        // the HTTP POST that follows an explicit Send tap.
        viewModelScope.launch(Dispatchers.IO) {
            localStore.savePending(pending)
            localStore.saveDraft(chatId, "")
        }
        markLatency(
            WearLatencyEvents.SEND_STARTED,
            0L,
            "chat_id" to chatId,
            "question_chars" to text.length,
            "send_started_ms" to latencySendStartEpochMs,
        )
        viewModelScope.launch { submit(chatId, text, pending, tappedAt) }
    }

    fun cancelCurrentAnswer() {
        val state = mutableState.value
        if (!state.operationActive) return
        val pending = activeSubmission?.takeIf { it.chatId == state.activeChatId }
            ?: state.activeChatId?.let(localStore::pending)
            ?: return
        cancelRequestedFor = pending.requestId
        if (pending.jobId != null && cancellingRequest != pending.requestId) {
            viewModelScope.launch { cancelAcceptedSubmission(pending) }
        }
    }

    private suspend fun cancelAcceptedSubmission(pending: PendingSubmission): Boolean {
        val jobId = pending.jobId ?: return false
        if (cancellingRequest == pending.requestId) return false
        cancellingRequest = pending.requestId
        try {
            val result = gateway.cancelJob(jobId)
            if (result.status != "cancelled") return false
            if (activeSubmitJob != coroutineContext[CoroutineJob]) activeSubmitJob?.cancel()
            finalizeCancelledSubmission(pending)
            return true
        } catch (error: Exception) {
            Log.w(TAG, "Unable to cancel answer job", error)
            mutableState.update { it.copy(error = "Не удалось остановить ответ") }
            return false
        } finally {
            if (cancelRequestedFor == pending.requestId) cancelRequestedFor = null
            cancellingRequest = null
        }
    }

    private suspend fun finalizeCancelledSubmission(pending: PendingSubmission) {
        val current = mutableState.value
        val partial = if (current.activeChatId == pending.chatId) current.streamingAnswer else ""
        val serverMessages = runCatching { gateway.messages(pending.chatId) }.getOrNull()
        val savedMessages = if (serverMessages != null) {
            val assistantIndex = serverMessages.indexOfLast { it.role == "assistant" }
            if (assistantIndex >= 0 && partial.length > serverMessages[assistantIndex].content.length) {
                serverMessages.toMutableList().also { messages ->
                    messages[assistantIndex] = messages[assistantIndex].copy(content = partial, status = "cancelled")
                }
            } else serverMessages
        } else completedMessagesFor(
            cachedMessages = if (current.messagesChatId == pending.chatId) current.messages else localStore.messages(pending.chatId),
            pendingText = pending.text,
            requestId = pending.requestId,
            streamedAnswer = partial,
        )
        withContext(Dispatchers.IO) {
            if (savedMessages != null) localStore.saveMessages(pending.chatId, savedMessages)
            localStore.savePending(pending.copy(state = SubmissionState.CANCELLED))
        }
        val savedAnswer = savedMessages?.lastOrNull { it.role == "assistant" && it.content.isNotBlank() }
        mutableState.update {
            if (it.activeChatId != pending.chatId) return@update it
            it.copy(
                messages = savedMessages ?: it.messages,
                messagesChatId = if (savedMessages != null) pending.chatId else it.messagesChatId,
                pendingQuestion = "",
                pendingBaseMessageId = null,
                streamingAnswer = if (savedAnswer != null) "" else partial,
                selectedAnswerId = if (it.selectedAnswerId == STREAMING_ANSWER_ID && savedAnswer != null) savedAnswer.id else it.selectedAnswerId,
                selectedAnswerText = if (it.selectedAnswerId == STREAMING_ANSWER_ID) savedAnswer?.content ?: partial else it.selectedAnswerText,
                stage = ProcessingStage.READY,
                error = null,
            )
        }
        if (activeSubmission?.requestId == pending.requestId) activeSubmission = null
    }

    /** Diagnostic-only latency mark, retained in logcat for local export. */
    private fun markLatency(event: String, elapsedMs: Long?, vararg fields: Pair<String, Any?>) {
        WearLatencyTrace.log(event, *fields, "request_id" to latencyRequestId, "elapsed_ms" to elapsedMs)
    }

    private fun logSendTiming(line: String) {
        Log.i(TAG, line)
        WearDiagnosticLog.record("send", line)
    }

    fun selectAnswer(messageId: String) {
        mutableState.update { state ->
            val text = if (messageId == STREAMING_ANSWER_ID) {
                state.streamingAnswer
            } else {
                state.messages.firstOrNull { it.id == messageId }?.content.orEmpty()
            }
            state.copy(selectedAnswerId = messageId, selectedAnswerText = text)
        }
        val selected = mutableState.value
        WearAnswerTrace.log(
            "reader_opened",
            "requested_id_kind" to WearAnswerTrace.idKind(messageId),
            "selected_answer_id_kind" to WearAnswerTrace.idKind(selected.selectedAnswerId),
            "selected_answer_chars" to selected.selectedAnswerText.length,
            "stream_chars" to selected.streamingAnswer.length,
            "stage" to selected.stage,
        )
    }

    fun selectedAnswer(): String = selectedAnswerContent(mutableState.value)

    private fun registerCurrentPushToken() = viewModelScope.launch {
        val token = pushStore.token().ifBlank { FirebaseMessaging.getInstance().token.await() }
        if (token.isNotBlank()) registerPushToken(token)
    }

    private fun registerPushToken(pushToken: String) = viewModelScope.launch {
        if (token.isBlank()) return@launch
        pushStore.saveToken(pushToken)
        runCatching { gateway.registerPushToken(pushToken) }
            .onFailure { Log.w(TAG, "FCM token registration failed", it) }
    }

    private fun refreshFromPush() = viewModelScope.launch { runPushRefresh() }

    private suspend fun runPushRefresh() {
        if (token.isBlank()) return
        WearAnswerTrace.log(
            "refresh_started",
            "source" to "push",
            "stage" to mutableState.value.stage,
            "stream_chars" to mutableState.value.streamingAnswer.length,
            "selected_answer_id_kind" to WearAnswerTrace.idKind(mutableState.value.selectedAnswerId),
        )
        // The server pushes on every mutation, so bursts arrive together. Only one
        // full refresh may run; the rest collapse into a single follow-up.
        if (pushRefreshRunning) {
            pushRefreshPending = true
            return
        }
        pushRefreshRunning = true
        try {
            runCatching { refreshData() }
                .onFailure { Log.w(TAG, "Push-triggered sync failed", it) }
        } finally {
            pushRefreshRunning = false
        }
        if (pushRefreshPending) {
            pushRefreshPending = false
            runPushRefresh()
        }
    }

    private suspend fun refreshData() {
        check(gateway.health()) { "VPS не отвечает" }
        refreshFallbackTicket()
        synchronizeFallbackIfNeeded()
        refreshLists()
        val current = mutableState.value
        val restored = localStore.activeChatId()?.takeIf { id -> current.chats.any { it.id == id } }
            ?: current.chats.firstOrNull()?.id
        WearAnswerTrace.log(
            "refresh_load_chat",
            "source" to "push_or_init",
            "restored_chat_id" to restored,
            "stage" to current.stage,
            "stream_chars" to current.streamingAnswer.length,
            "selected_answer_id_kind" to WearAnswerTrace.idKind(current.selectedAnswerId),
            "operation_active" to current.operationActive,
        )
        if (restored != null) {
            showLocalChat(restored)
            loadChat(restored)
        }
        else mutableState.update {
            it.copy(
                vpsConnected = true,
                fallbackActive = false,
                activeChatId = null,
                messages = emptyList(),
                messagesChatId = null,
                contentChatId = null,
                draft = "",
                stage = ProcessingStage.READY,
                error = null,
            )
        }
    }

    private suspend fun refreshLists() {
        // A push, a foreground entry and a just-created chat can all ask for the
        // list at once. Overlapping fetches duplicated every modes/chats request
        // and competed for the watch radio, which made the UI feel stuck.
        if (refreshListsRunning) return
        refreshListsRunning = true
        try {
            val modes = gateway.modes()
            val serverChats = withoutPendingDeletes(gateway.chats())
            val offlineIds = localStore.offlineChats().mapTo(mutableSetOf()) { it.chatId }
            val localOfflineChats = localStore.cachedChats().filter { it.id in offlineIds }
            val chats = localOfflineChats + serverChats.filterNot { server -> localOfflineChats.any { it.id == server.id } }
            withContext(Dispatchers.IO) {
                localStore.saveModes(modes)
                localStore.saveChats(chats)
            }
            mutableState.update { it.copy(modes = modes, chats = chats, vpsConnected = true, error = null) }
        } finally {
            refreshListsRunning = false
        }
    }

    private suspend fun loadChat(chatId: String) {
        val messages = gateway.messages(chatId)
        withContext(Dispatchers.IO) { localStore.saveMessages(chatId, messages) }
        if (mutableState.value.activeChatId != chatId) return
        val pending = localStore.pending(chatId)
        val shouldRestoreOutbox = pending?.state in setOf(
            SubmissionState.QUEUED,
            SubmissionState.ACCEPTED,
            SubmissionState.STREAMING,
        )
        val traceBefore = mutableState.value
        val tracePreserveLiveStream = traceBefore.activeChatId == chatId &&
            traceBefore.contentChatId == chatId &&
            (traceBefore.streamingAnswer.isNotBlank() || traceBefore.selectedAnswerId == STREAMING_ANSWER_ID)
        WearAnswerTrace.log(
            "messages_refetch",
            "source" to "server_api",
            "chat_id" to chatId,
            "incoming" to WearAnswerTrace.listShape(messages),
            "pending_state" to pending?.state,
            "should_restore_outbox" to shouldRestoreOutbox,
            "preserve_live_stream" to tracePreserveLiveStream,
            "prev_stream_chars" to traceBefore.streamingAnswer.length,
            "prev_stage" to traceBefore.stage,
            "selected_answer_id_kind" to WearAnswerTrace.idKind(traceBefore.selectedAnswerId),
            "selected_answer_chars" to traceBefore.selectedAnswerText.length,
        )
        mutableState.update { current ->
            // `loadChat` is also called by an FCM-triggered refresh. Its server
            // snapshot may lag behind the live SSE buffer, especially while the
            // full-answer screen is open. Do not replace that buffer with "".
            val preserveLiveStream = current.activeChatId == chatId &&
                current.contentChatId == chatId &&
                (current.streamingAnswer.isNotBlank() || current.selectedAnswerId == STREAMING_ANSWER_ID)
            current.copy(
                messages = messages,
                messagesChatId = chatId,
                contentChatId = chatId,
                draft = localStore.draft(chatId),
                pendingQuestion = if (shouldRestoreOutbox) pending?.text.orEmpty() else "",
                pendingBaseMessageId = if (shouldRestoreOutbox) pending?.baseMessageId else null,
                streamingAnswer = if (shouldRestoreOutbox || preserveLiveStream) current.streamingAnswer else "",
                stage = when {
                    shouldRestoreOutbox -> pendingStage(pending)
                    preserveLiveStream -> current.stage
                    else -> ProcessingStage.READY
                },
                vpsConnected = true,
                error = null,
            )
        }
    }

    private suspend fun submit(
        chatId: String,
        text: String,
        initialPending: PendingSubmission? = null,
        tappedAt: Long = SystemClock.elapsedRealtime(),
    ) {
        val startedAt = tappedAt
        // Diagnostic-only: recovery paths enter submit without sendDraft, so make
        // sure a trace start exists even then.
        if (latencySendStartElapsedMs == null) {
            latencySendStartElapsedMs = tappedAt
            latencySendStartEpochMs = System.currentTimeMillis()
        }
        if (latencyRequestId == null) latencyRequestId = initialPending?.requestId
        var pending = initialPending ?: localStore.pending(chatId)?.takeIf { it.text == text }
            ?: PendingSubmission(
                chatId = chatId,
                requestId = UUID.randomUUID().toString(),
                text = text,
                jobId = null,
                cursor = 0,
                state = SubmissionState.QUEUED,
            )
        activeSubmission = pending
        activeSubmitJob = coroutineContext[CoroutineJob]
        var accepted = pending.state in setOf(SubmissionState.ACCEPTED, SubmissionState.STREAMING)
        var lastPersistedCursorAt = 0L
        latencyRequestId = pending.requestId
        runCatching {
            if (pending.jobId == null) {
                logSendTiming("send_timing request_id=${pending.requestId} event=http_start elapsed_ms=${SystemClock.elapsedRealtime() - startedAt}")
                val job = sendMessageWithRetry(
                    chatId,
                    pending.requestId,
                    text,
                    pending.webSearch,
                    pending.webResearch,
                    pending.researchMode,
                )
                pending = pending.copy(jobId = job.id, state = SubmissionState.ACCEPTED)
                activeSubmission = pending
                accepted = true
                localStore.savePending(pending)
                markLatency(
                    WearLatencyEvents.JOB_ACCEPTED,
                    SystemClock.elapsedRealtime() - startedAt,
                    "job_id" to job.id,
                )
                logSendTiming("send_timing request_id=${pending.requestId} event=job_accepted elapsed_ms=${SystemClock.elapsedRealtime() - startedAt} job_id=${job.id}")
            }
            if (cancelRequestedFor == pending.requestId && cancelAcceptedSubmission(pending)) {
                return@runCatching
            }
            val jobId = checkNotNull(pending.jobId)
            var cursor = pending.cursor
            var terminal = false
            var lastStreamFailure: Throwable? = null
            var receivedStreamEvent = false
            var completedFromJobStatus = false
            var cancelledFromJobStatus = false
            val resume = StreamResumePolicy()
            markLatency(
                WearLatencyEvents.SSE_SUBSCRIBE_START,
                SystemClock.elapsedRealtime() - startedAt,
                "job_id" to jobId,
            )
            while (!terminal) {
                when (
                    val outcome = collectStreamWindow(
                        events = gateway.events(jobId, cursor),
                        idleBudgetMs = resume.idleBudgetMs(receivedStreamEvent),
                    ) { event ->
                        receivedStreamEvent = true
                        if (event.type == "delta" && latencyFirstSseDeltaMs == null) {
                            val elapsed = SystemClock.elapsedRealtime() - startedAt
                            latencyFirstSseDeltaMs = elapsed
                            markLatency(
                                WearLatencyEvents.WATCH_FIRST_DELTA_RECEIVED,
                                elapsed,
                                "job_id" to jobId,
                                "event_id" to event.id,
                                "payload_chars" to event.data.length,
                                "first_sse_delta_received_ms" to elapsed,
                            )
                        }
                        // A delivered event proves the route works: earlier stalls
                        // must not shorten this stream's reconnect budget.
                        resume.onEventReceived()
                        cursor = maxOf(cursor, event.id)
                        pending = pending.copy(
                            cursor = cursor,
                            state = if (event.type == "delta") SubmissionState.STREAMING else pending.state,
                        )
                        val now = SystemClock.elapsedRealtime()
                        if (event.type != "delta" || now - lastPersistedCursorAt >= CURSOR_PERSIST_INTERVAL_MS) {
                            localStore.savePending(pending)
                            lastPersistedCursorAt = now
                        }
                        val terminalEvent = applyEvent(chatId, event)
                        if (event.type == "cancelled") cancelledFromJobStatus = true
                        terminalEvent
                    }
                ) {
                    StreamWindowOutcome.Terminal -> terminal = true
                    is StreamWindowOutcome.Failed -> lastStreamFailure = outcome.error
                    // Idle and Closed resume from the durable cursor below.
                    StreamWindowOutcome.Idle, StreamWindowOutcome.Closed -> Unit
                }
                if (terminal) break
                val jobStatus = runCatching { gateway.job(jobId).status }
                    .onFailure { lastStreamFailure = it }
                    .getOrNull()
                if (!terminal) {
                    WearAnswerTrace.log(
                        "stream_interrupted",
                        "job_id" to jobId,
                        "request_id" to pending.requestId,
                        "cursor" to cursor,
                        "received_event" to receivedStreamEvent,
                        "job_status" to jobStatus,
                        "consecutive_reconnects" to resume.consecutiveReconnects,
                        "total_reconnects" to resume.totalReconnects,
                        "silent_probes" to resume.silentProbes,
                        "stream_chars" to mutableState.value.streamingAnswer.length,
                        "last_failure" to lastStreamFailure?.javaClass?.simpleName,
                    )
                }
                when (jobStatus) {
                    "complete" -> {
                        terminal = true
                        completedFromJobStatus = true
                    }
                    "failed" -> throw IOException("Сервер не смог обработать запрос")
                    "cancelled" -> {
                        terminal = true
                        cancelledFromJobStatus = true
                    }
                    else -> {
                        val reconnectDelayMs = resume.nextAttemptDelayMs(receivedStreamEvent)
                            ?: throw IOException(
                                "Связь прервана. Текст сохранён — отправьте его ещё раз",
                                lastStreamFailure,
                            )
                        delay(reconnectDelayMs)
                    }
                }
            }
            if (!terminal) throw IOException("Ответ не получен. Текст сохранён")
            if (cancelledFromJobStatus) {
                finalizeCancelledSubmission(pending)
                return@runCatching
            }
            pending = pending.copy(state = SubmissionState.COMPLETE)
            WearAnswerTrace.log(
                "finalize_choice",
                "job_id" to pending.jobId,
                "request_id" to pending.requestId,
                "chat_id" to chatId,
                "completed_from_job_status" to completedFromJobStatus,
                "stream_chars" to mutableState.value.streamingAnswer.length,
                "stage" to mutableState.value.stage,
            )
            if (completedFromJobStatus) {
                finalizeSubmissionFromServer(pending)
            } else {
                finalizeSubmissionLocally(pending)
            }
            reconcileChatSummaryInBackground(chatId)
            logSendTiming("answer_total_ms=${SystemClock.elapsedRealtime() - startedAt}")
        }.onFailure { error ->
            if (error is CancellationException) return@onFailure
            // Once the POST is accepted, a stream timeout says nothing about the
            // job itself: the server can still be producing the answer. Keep the
            // durable outbox and the visible partial text, then ask the job API
            // for the authoritative result in the background.
            val retryableBeforeAcceptance = !accepted && isRetryableSendFailure(error)
            WearAnswerTrace.log(
                "submit_failed",
                "request_id" to pending.requestId,
                "job_id" to pending.jobId,
                "chat_id" to chatId,
                "accepted" to accepted,
                "retryable_before_acceptance" to retryableBeforeAcceptance,
                "cursor" to pending.cursor,
                "stream_chars" to mutableState.value.streamingAnswer.length,
                "error" to error.javaClass.simpleName,
            )
            val retainedPending = when {
                accepted -> pending.copy(
                    state = if (pending.cursor > 0) SubmissionState.STREAMING else SubmissionState.ACCEPTED,
                )
                // Keep the stable request ID in the durable outbox. A transient
                // radio failure must be retried, not presented as a terminal
                // error or turned into a duplicate question on the next tap.
                retryableBeforeAcceptance -> pending.copy(state = SubmissionState.QUEUED)
                else -> pending.copy(state = SubmissionState.FAILED)
            }
            if (retryableBeforeAcceptance && tryFallbackAnswer(retainedPending)) {
                return@onFailure
            }
            localStore.savePending(retainedPending)
            if (!accepted && !retryableBeforeAcceptance) {
                localStore.saveDraft(chatId, text)
                if (mutableState.value.activeChatId == chatId) {
                    mutableState.update { it.copy(draft = text) }
                }
            }
            when {
                accepted -> {
                    handleFailure(error, keepPendingQuestion = true)
                    recoverAcceptedSubmission(retainedPending)
                }
                retryableBeforeAcceptance -> recoverQueuedSubmission(retainedPending)
                else -> handleFailure(error)
            }
        }
    }

    private fun applyEvent(chatId: String, event: ServerEvent): Boolean {
        val data = runCatching { JSONObject(event.data) }.getOrElse { JSONObject() }
        if (event.type != "delta" && event.type != "complete") {
            WearAnswerTrace.log(
                "sse_event",
                "event_type" to event.type,
                "event_id" to event.id,
                "chat_id" to chatId,
                "server_state" to if (event.type == "state") data.optString("state") else null,
                "payload_keys" to data.keys().asSequence().joinToString(","),
                "stage_before" to mutableState.value.stage,
                "stream_chars_before" to mutableState.value.streamingAnswer.length,
                "message_id_chars" to data.optString("message_id").length,
                "error_blank" to (event.type == "error" && data.optString("detail").isBlank()),
            )
        }
        return when (event.type) {
            "state" -> {
                val stage = processingStageFromServerState(data.optString("state"))
                val ordinal = listOf("pass", "step", "page")
                    .firstNotNullOfOrNull { key -> data.optInt(key).takeIf { it > 0 } }
                if (stage != null) mutableState.update {
                    if (it.activeChatId == chatId && it.contentChatId == chatId) {
                        it.copy(stage = stage, progressOrdinal = ordinal)
                    } else it
                }
                false
            }
            "delta" -> {
                val delta = data.optString("text")
                var applied = false
                var accumulated = 0
                var stageAfter = ProcessingStage.GENERATING
                mutableState.update {
                    if (it.activeChatId == chatId && it.contentChatId == chatId) {
                        applied = true
                        accumulated = it.streamingAnswer.length + delta.length
                        val next = it.copy(
                            stage = ProcessingStage.GENERATING,
                            streamingAnswer = it.streamingAnswer + delta,
                        )
                        stageAfter = next.stage
                        next
                    } else {
                        stageAfter = it.stage
                        it
                    }
                }
                // Lengths only: the delta text itself is never logged.
                WearAnswerTrace.log(
                    "sse_delta",
                    "chat_id" to chatId,
                    "event_id" to event.id,
                    "applied" to applied,
                    "delta_chars" to delta.length,
                    "stream_chars" to accumulated,
                    "active_chat_id" to mutableState.value.activeChatId,
                    "content_chat_id" to mutableState.value.contentChatId,
                    "stage" to stageAfter,
                )
                // Diagnostic-only: the first non-empty answer text committed to
                // the Compose state that the chat bubble renders. The frame that
                // draws it follows on the next vsync.
                val start = latencySendStartElapsedMs
                if (applied && accumulated > 0 && latencyFirstVisibleTextMs == null && start != null) {
                    val elapsed = SystemClock.elapsedRealtime() - start
                    latencyFirstVisibleTextMs = elapsed
                    markLatency(
                        WearLatencyEvents.WATCH_FIRST_VISIBLE_TEXT,
                        elapsed,
                        "chat_id" to chatId,
                        "stream_chars" to accumulated,
                        "stage" to "compose_state_commit",
                        "first_visible_text_rendered_ms" to elapsed,
                    )
                }
                false
            }
            "complete" -> {
                val state = mutableState.value
                WearAnswerTrace.log(
                    "sse_complete",
                    "chat_id" to chatId,
                    "event_id" to event.id,
                    "stream_chars" to state.streamingAnswer.length,
                    "selected_answer_id_kind" to WearAnswerTrace.idKind(state.selectedAnswerId),
                    "selected_answer_chars" to state.selectedAnswerText.length,
                    "stage" to state.stage,
                )
                true
            }
            "cancelled" -> true
            "source_candidate" -> {
                val candidate = ChatSourceCandidate(
                    data.optString("id"), data.optString("title"), data.optString("url"), data.optString("preview"),
                )
                if (candidate.id.isNotBlank()) mutableState.update {
                    if (it.activeChatId == chatId && it.sourceCandidates.none { item -> item.id == candidate.id }) {
                        it.copy(sourceCandidates = it.sourceCandidates + candidate)
                    } else it
                }
                false
            }
            "error" -> throw IOException(data.optString("detail", "Ошибка сервера"))
            else -> false
        }
    }

    private suspend fun sendMessageWithRetry(
        chatId: String,
        requestId: String,
        text: String,
        webSearch: Boolean,
        webResearch: Boolean,
        researchMode: Boolean,
    ) =
        run {
            var lastFailure: Throwable? = null
            repeat(WearRetryPolicy.MAX_SEND_ATTEMPTS) { attempt ->
                try {
                    // Each route owns a meaningful transport timeout. Do not
                    // impose a shorter global deadline here: the Bluetooth
                    // proxy may still be bringing up the phone's mobile data
                    // connection, and cancelling it loses the request before
                    // it can reach the API.
                    return@run gateway.sendMessage(chatId, requestId, text, webSearch, webResearch, researchMode)
                } catch (error: Throwable) {
                    lastFailure = error
                    if (!isRetryableSendFailure(error) || attempt + 1 == WearRetryPolicy.MAX_SEND_ATTEMPTS) {
                        throw error
                    }
                    // The request ID is deliberately unchanged: an ambiguous first POST
                    // resolves to the already-created job instead of a second message.
                    delay(WearRetryPolicy.SEND_RETRY_DELAY_MS)
                }
            }
            throw checkNotNull(lastFailure)
        }

    private fun isRetryableSendFailure(error: Throwable): Boolean = when (error) {
        is IOException, is TimeoutCancellationException -> true
        is WristMindApiException -> error.statusCode == 408 || error.statusCode == 429 || error.statusCode >= 500
        else -> false
    }

    private suspend fun refreshFallbackTicket() {
        runCatching { gateway.fallbackTicket() }
            .onSuccess { configStore.saveFallbackTicket(it.ticket) }
            .onFailure { Log.w(TAG, "Fallback ticket refresh failed", it) }
    }

    private suspend fun fallbackIsReady(): Boolean =
        configStore.fallbackTicket().isNotBlank() && runCatching { fallbackClient.health() }.getOrDefault(false)

    private fun markFallbackAvailable() {
        mainRecoverySuccesses = 0
        mutableState.update {
            it.copy(vpsConnected = true, fallbackActive = true, stage = ProcessingStage.READY, error = null)
        }
    }

    private fun createOfflineChat(modeId: String, requestId: String, quick: Boolean): Chat? {
        val mode = if (quick) null else mutableState.value.modes.firstOrNull { it.id == modeId } ?: return null
        val chatId = "offline-${UUID.randomUUID()}"
        val modeName = mode?.name ?: "Быстрый чат"
        val chat = Chat(
            id = chatId,
            modeId = mode?.id.orEmpty(),
            modeName = modeName,
            modeDeleted = false,
            title = modeName,
        )
        localStore.saveOfflineChat(
            OfflineChat(chatId, mode?.id.orEmpty(), modeName, requestId, quick),
        )
        mainRecoverySuccesses = 0
        mutableState.update { it.copy(vpsConnected = true, fallbackActive = true, error = null) }
        return chat
    }

    private suspend fun tryFallbackAnswer(pending: PendingSubmission): Boolean {
        if (!fallbackIsReady()) return false
        // Diagnostic-only: this turn left the main pipeline for the VPS fallback.
        markLatency(
            WearLatencyEvents.FALLBACK,
            latencySendStartElapsedMs?.let { SystemClock.elapsedRealtime() - it },
            "chat_id" to pending.chatId,
            "stage" to "vps_fallback",
        )
        val current = mutableState.value
        val chat = current.chats.firstOrNull { it.id == pending.chatId }
            ?: localStore.cachedChats().firstOrNull { it.id == pending.chatId }
            ?: return false
        val mode = current.modes.firstOrNull { it.id == chat.modeId }
            ?: localStore.cachedModes().firstOrNull { it.id == chat.modeId }
        val cachedMessages = if (current.messagesChatId == pending.chatId) current.messages
            else localStore.messages(pending.chatId)
        mainRecoverySuccesses = 0
        mutableState.update {
            it.copy(
                vpsConnected = true,
                fallbackActive = true,
                stage = ProcessingStage.FALLBACK_GENERATING,
                error = null,
            )
        }
        val response = runCatching {
            fallbackClient.respond(
                requestId = pending.requestId,
                chatId = pending.chatId,
                modeName = chat.modeName,
                systemPrompt = mode?.systemPrompt.orEmpty(),
                history = cachedMessages.filter { it.content.isNotBlank() }.takeLast(FALLBACK_HISTORY_MESSAGES),
                text = pending.text,
                requestedWebSearch = pending.webSearch,
            )
        }.onFailure { Log.w(TAG, "Fallback answer failed", it) }.getOrNull() ?: return false
        val answer = response.answer + "\n\n_Резервный режим: сохранённые источники и веб-поиск недоступны._"
        localStore.saveFallbackExchange(
            FallbackExchange(pending.chatId, pending.requestId, pending.text, answer),
        )
        mutableState.update {
            if (it.activeChatId == pending.chatId) it.copy(streamingAnswer = answer) else it
        }
        finalizeSubmissionLocally(pending.copy(state = SubmissionState.COMPLETE))
        localStore.clearPending(pending.chatId)

        if (chat.title == "Новый чат" || chat.title == chat.modeName) {
            val renamed = chat.copy(title = pending.text.take(120))
            val chats = mutableState.value.chats.map { if (it.id == chat.id) renamed else it }
            localStore.saveChats(chats)
            mutableState.update { it.copy(chats = chats) }
        }
        return true
    }

    private suspend fun synchronizeFallbackIfNeeded() {
        if (fallbackSyncRunning) return
        if (localStore.offlineChats().isEmpty() && localStore.fallbackExchanges().isEmpty()) return
        fallbackSyncRunning = true
        try {
            localStore.offlineChats().forEach { offline ->
                val serverChat = if (offline.quick) {
                    gateway.createQuickChat(offline.createRequestId)
                } else {
                    gateway.createChat(offline.modeId, offline.createRequestId)
                }
                localStore.migrateChat(offline.chatId, serverChat)
                mutableState.update { state ->
                    state.copy(
                        chats = state.chats.map { if (it.id == offline.chatId) serverChat else it },
                        activeChatId = if (state.activeChatId == offline.chatId) serverChat.id else state.activeChatId,
                        messagesChatId = if (state.messagesChatId == offline.chatId) serverChat.id else state.messagesChatId,
                        contentChatId = if (state.contentChatId == offline.chatId) serverChat.id else state.contentChatId,
                    )
                }
            }
            localStore.fallbackExchanges().forEach { exchange ->
                gateway.syncFallbackMessage(
                    exchange.chatId,
                    exchange.requestId,
                    exchange.userText,
                    exchange.assistantText,
                )
                localStore.removeFallbackExchange(exchange.requestId)
            }
        } catch (error: Throwable) {
            Log.w(TAG, "Fallback reconciliation failed", error)
        } finally {
            fallbackSyncRunning = false
        }
    }

    private fun handleFailure(error: Throwable, keepPendingQuestion: Boolean = false) {
        WearAnswerTrace.log(
            "failure_handled",
            "error" to error.javaClass.simpleName,
            "keep_pending_question" to keepPendingQuestion,
            "stage" to mutableState.value.stage,
            "stream_chars" to mutableState.value.streamingAnswer.length,
            "stage_will_clear_stream" to (!keepPendingQuestion && mutableState.value.streamingAnswer.isNotEmpty()),
        )
        if (error is WristMindApiException && error.statusCode == 401) {
            token = ""
            configStore.clearToken()
            configStore.clearFallbackTicket()
            mutableState.update {
                WearState(
                    serverUrl = BuildConfig.WRISTMIND_BASE_URL,
                    stage = ProcessingStage.DISCONNECTED,
                    error = "Привязка истекла. Введите новый код",
                )
            }
            return
        }
        mutableState.update {
            if (keepPendingQuestion) {
                // The request was accepted. A temporary SSE interruption must
                // not erase the answer the person is currently reading or turn
                // it into a red terminal error.
                return@update it.copy(
                    stage = if (it.streamingAnswer.isNotBlank()) ProcessingStage.GENERATING else ProcessingStage.WAITING,
                    loading = false,
                    error = null,
                )
            }
            it.copy(
                stage = ProcessingStage.ERROR,
                vpsConnected = false,
                loading = false,
                pendingQuestion = if (keepPendingQuestion) it.pendingQuestion else "",
                pendingBaseMessageId = if (keepPendingQuestion) it.pendingBaseMessageId else null,
                streamingAnswer = "",
                error = error.message?.takeIf(String::isNotBlank) ?: "Ошибка подключения",
            )
        }
    }

    /**
     * SSE is only the fast display channel. If it drops after acceptance, poll
     * the durable job briefly and replace the live buffer once its saved answer
     * is available. This avoids both a false error and a duplicate submission.
     */
    private fun recoverAcceptedSubmission(pending: PendingSubmission) = viewModelScope.launch {
        val jobId = pending.jobId ?: return@launch
        repeat(MAX_ACCEPTED_RECOVERY_PROBES) { attempt ->
            delay(ACCEPTED_RECOVERY_DELAY_MS)
            when (runCatching { gateway.job(jobId).status }.getOrNull()) {
                "complete" -> {
                    finalizeSubmissionFromServer(pending.copy(state = SubmissionState.COMPLETE))
                    reconcileChatSummaryInBackground(pending.chatId)
                    return@launch
                }
                "failed" -> {
                    localStore.savePending(pending.copy(state = SubmissionState.FAILED))
                    if (mutableState.value.activeChatId == pending.chatId) {
                        mutableState.update {
                            it.copy(
                                stage = ProcessingStage.ERROR,
                                error = "Сервер не смог обработать запрос",
                            )
                        }
                    }
                    return@launch
                }
            }
            Log.d(TAG, "Waiting for accepted job recovery attempt=${attempt + 1}")
        }
    }

    /**
     * The server did not confirm the POST, so the message remains in the local
     * outbox and is retried with the same idempotency key. This is deliberately
     * separate from SSE recovery: there is no job ID to poll yet.
     */
    private fun recoverQueuedSubmission(pending: PendingSubmission) = viewModelScope.launch {
        if (mutableState.value.activeChatId == pending.chatId) {
            mutableState.update {
                it.copy(
                    stage = ProcessingStage.SENDING,
                    pendingQuestion = pending.text,
                    pendingBaseMessageId = pending.baseMessageId,
                    error = null,
                )
            }
        }
        repeat(MAX_QUEUED_RECOVERY_PROBES) { attempt ->
            delay(QUEUED_RECOVERY_DELAYS_MS[attempt])
            val job = runCatching {
                sendMessageWithRetry(
                    pending.chatId,
                    pending.requestId,
                    pending.text,
                    pending.webSearch,
                    pending.webResearch,
                    pending.researchMode,
                )
            }.getOrNull() ?: return@repeat
            val accepted = pending.copy(jobId = job.id, state = SubmissionState.ACCEPTED)
            localStore.savePending(accepted)
            submit(pending.chatId, pending.text, accepted)
            return@launch
        }
        // The question stays in the outbox and resumes automatically whenever
        // the app is opened again; only then is a quiet retry affordance shown.
        if (mutableState.value.activeChatId == pending.chatId) {
            mutableState.update {
                it.copy(
                    stage = ProcessingStage.READY,
                    draft = pending.text,
                    pendingQuestion = "",
                    pendingBaseMessageId = null,
                    error = "Связь пока слабая — вопрос сохранён и будет повторён при следующем открытии",
                )
            }
        }
    }

    private fun stageAfterEditing(stage: ProcessingStage) = when (stage) {
        ProcessingStage.ERROR, ProcessingStage.COMPLETE -> ProcessingStage.READY
        else -> stage
    }

    private fun restorePendingSubmission() {
        val activeChatId = mutableState.value.activeChatId
        val submissions = localStore.pendingSubmissions()
        submissions
            .filter { it.state == SubmissionState.COMPLETE }
            .forEach { reconcileChatSummaryInBackground(it.chatId) }
        val pending = submissions
            .firstOrNull { it.chatId == activeChatId && it.state in RESUMABLE_SUBMISSION_STATES }
            ?: submissions.firstOrNull { it.state in RESUMABLE_SUBMISSION_STATES }
            ?: return
        if (mutableState.value.activeChatId != pending.chatId) showLocalChat(pending.chatId)
        mutableState.update {
            it.copy(
                contentChatId = pending.chatId,
                pendingQuestion = pending.text,
                pendingBaseMessageId = pending.baseMessageId,
                streamingAnswer = "",
                stage = pendingStage(pending),
                error = null,
            )
        }
        viewModelScope.launch { submit(pending.chatId, pending.text) }
    }

    private suspend fun finalizeSubmissionLocally(pending: PendingSubmission) {
        val current = mutableState.value
        val isActive = current.activeChatId == pending.chatId && current.contentChatId == pending.chatId
        val streamedAnswer = if (isActive) current.streamingAnswer else ""
        WearAnswerTrace.log(
            "finalize_local_enter",
            "request_id" to pending.requestId,
            "chat_id" to pending.chatId,
            "is_active" to isActive,
            "stream_chars" to current.streamingAnswer.length,
            "used_stream_chars" to streamedAnswer.length,
            "stage" to current.stage,
        )
        val cachedMessages = if (current.messagesChatId == pending.chatId) {
            current.messages
        } else {
            localStore.messages(pending.chatId)
        }
        val completedMessages = completedMessagesFor(
            cachedMessages = cachedMessages,
            pendingText = pending.text,
            requestId = pending.requestId,
            streamedAnswer = streamedAnswer,
        )
        if (completedMessages == null) {
            // No streamed text reached this chat. Never persist an empty assistant
            // reply: it would replace a complete answer with a blank bubble, and
            // never clear what the reader already shows. The server owns the
            // authoritative text, so take its snapshot instead.
            WearAnswerTrace.log(
                "finalize_local_blank_stream",
                "request_id" to pending.requestId,
                "chat_id" to pending.chatId,
                "is_active" to isActive,
                "cached" to WearAnswerTrace.listShape(cachedMessages),
            )
            val recovered = runCatching { finalizeSubmissionFromServer(pending) }.getOrDefault(false)
            if (!recovered) {
                // The snapshot was unavailable too. Close the operation without
                // touching the assistant message or the reader.
                localStore.savePending(pending)
                if (isActive) {
                    mutableState.update {
                        it.copy(
                            stage = ProcessingStage.COMPLETE,
                            pendingQuestion = "",
                            pendingBaseMessageId = null,
                            error = null,
                        )
                    }
                }
            }
            return
        }
        withContext(Dispatchers.IO) {
            localStore.saveMessages(pending.chatId, completedMessages)
            localStore.saveDraft(pending.chatId, "")
            localStore.savePending(pending)
        }
        if (isActive) {
            val completedAnswerId = completedMessages.last().id
            mutableState.update {
                it.copy(
                    messages = completedMessages,
                    messagesChatId = pending.chatId,
                    contentChatId = pending.chatId,
                    draft = "",
                    pendingQuestion = "",
                    pendingBaseMessageId = null,
                    streamingAnswer = "",
                    selectedAnswerId = if (it.selectedAnswerId == STREAMING_ANSWER_ID) completedAnswerId else it.selectedAnswerId,
                    selectedAnswerText = if (it.selectedAnswerId == STREAMING_ANSWER_ID) streamedAnswer else it.selectedAnswerText,
                    stage = ProcessingStage.COMPLETE,
                    error = null,
                    vpsConnected = true,
                )
            }
            val after = mutableState.value
            WearAnswerTrace.log(
                "finalize_local_done",
                "request_id" to pending.requestId,
                "stream_cleared" to (after.streamingAnswer.isEmpty()),
                "messages" to WearAnswerTrace.listShape(after.messages),
                "selected_answer_id_kind" to WearAnswerTrace.idKind(after.selectedAnswerId),
                "selected_answer_chars" to after.selectedAnswerText.length,
                "stage" to after.stage,
            )
        } else {
            // The stream no longer targets the visible chat: only the on-disk cache is
            // rewritten here. This is where an empty assistant bubble can be persisted.
            WearAnswerTrace.log(
                "finalize_local_inactive",
                "request_id" to pending.requestId,
                "chat_id" to pending.chatId,
                "persisted_stream_chars" to streamedAnswer.length,
            )
        }
    }

    /** Returns `true` when the authoritative server snapshot was applied. */
    private suspend fun finalizeSubmissionFromServer(pending: PendingSubmission): Boolean {
        val messages = gateway.messages(pending.chatId)
        // A completed job should have its assistant message persisted. If a
        // replica returns an incomplete snapshot, retain the live reader until
        // the next refresh rather than replacing it with an empty answer.
        val completedAnswer = messages.lastOrNull { it.role == "assistant" && it.content.isNotBlank() }
        WearAnswerTrace.log(
            "finalize_server_enter",
            "request_id" to pending.requestId,
            "chat_id" to pending.chatId,
            "fetched" to WearAnswerTrace.listShape(messages),
            "completed_answer_chars" to (completedAnswer?.content?.length ?: -1),
            "stream_chars" to mutableState.value.streamingAnswer.length,
            "selected_answer_id_kind" to WearAnswerTrace.idKind(mutableState.value.selectedAnswerId),
        )
        if (completedAnswer == null) {
            WearAnswerTrace.log(
                "finalize_server_bailed",
                "reason" to "no_non_blank_assistant",
                "fetched" to WearAnswerTrace.listShape(messages),
                "stream_chars" to mutableState.value.streamingAnswer.length,
            )
            return false
        }
        withContext(Dispatchers.IO) {
            localStore.saveMessages(pending.chatId, messages)
            localStore.saveDraft(pending.chatId, "")
            localStore.savePending(pending)
        }
        if (mutableState.value.activeChatId == pending.chatId) {
            val completedAnswerId = completedAnswer.id
            mutableState.update {
                it.copy(
                    messages = messages,
                    messagesChatId = pending.chatId,
                    contentChatId = pending.chatId,
                    draft = "",
                    pendingQuestion = "",
                    pendingBaseMessageId = null,
                    streamingAnswer = "",
                    selectedAnswerId = if (it.selectedAnswerId == STREAMING_ANSWER_ID) completedAnswerId else it.selectedAnswerId,
                    selectedAnswerText = if (it.selectedAnswerId == STREAMING_ANSWER_ID) completedAnswer.content else it.selectedAnswerText,
                    stage = ProcessingStage.COMPLETE,
                    error = null,
                    vpsConnected = true,
                )
            }
            val after = mutableState.value
            WearAnswerTrace.log(
                "finalize_server_done",
                "request_id" to pending.requestId,
                "stream_cleared" to after.streamingAnswer.isEmpty(),
                "messages" to WearAnswerTrace.listShape(after.messages),
                "selected_answer_id_kind" to WearAnswerTrace.idKind(after.selectedAnswerId),
                "selected_answer_chars" to after.selectedAnswerText.length,
                "stage" to after.stage,
            )
        } else {
            WearAnswerTrace.log(
                "finalize_server_off_chat",
                "request_id" to pending.requestId,
                "chat_id" to pending.chatId,
                "active_chat_id" to mutableState.value.activeChatId,
                "persisted" to WearAnswerTrace.listShape(messages),
            )
        }
        return true
    }

    private fun reconcileChatSummaryInBackground(chatId: String) = viewModelScope.launch {
        runCatching { gateway.chats() }.onSuccess { serverChats ->
            val chats = withoutPendingDeletes(serverChats)
            withContext(Dispatchers.IO) {
                localStore.saveChats(chats)
                localStore.clearPending(chatId)
            }
            mutableState.update {
                if (it.activeChatId == chatId) {
                    it.copy(
                        chats = chats,
                        vpsConnected = true,
                    )
                } else it.copy(chats = chats, vpsConnected = true)
            }
        }.onFailure { error ->
            Log.w(TAG, "Background chat summary reconciliation failed", error)
        }
    }

    private fun pendingStage(pending: PendingSubmission?): ProcessingStage = when (pending?.state) {
        SubmissionState.STREAMING -> ProcessingStage.GENERATING
        SubmissionState.ACCEPTED -> ProcessingStage.WAITING
        SubmissionState.QUEUED -> ProcessingStage.SENDING
        else -> ProcessingStage.READY
    }

    private fun restoreCachedState() {
        val modes = localStore.cachedModes()
        val chats = withoutPendingDeletes(localStore.cachedChats())
        val activeChatId = localStore.activeChatId()?.takeIf { id -> chats.any { it.id == id } }
            ?: chats.firstOrNull()?.id
        val messages = activeChatId?.let(localStore::messages).orEmpty()
        mutableState.update {
            it.copy(
                modes = modes,
                chats = chats,
                activeChatId = activeChatId,
                messages = messages,
                messagesChatId = activeChatId,
                contentChatId = activeChatId,
                draft = activeChatId?.let(localStore::draft).orEmpty(),
            )
        }
    }

    /**
     * Shows the cached view of [chatId].
     *
     * The full-answer reader is derived state, not stored state, so it must only
     * be cleared when the person actually switches chats. A background refresh for
     * the chat that is already open (an FCM `state_changed` right after the answer
     * completes, or a return to the foreground) keeps `selectedAnswerId`,
     * `selectedAnswerText` and `streamingAnswer` intact — otherwise the open
     * "Ответ" screen would re-render as an empty container.
     */
    private fun showLocalChat(chatId: String) {
        val before = mutableState.value
        val sameChat = before.activeChatId == chatId
        WearAnswerTrace.log(
            "reader_state_reset",
            "source" to "showLocalChat",
            "chat_id" to chatId,
            "same_chat" to sameChat,
            "reader_preserved" to sameChat,
            "prev_stage" to before.stage,
            "prev_stream_chars" to before.streamingAnswer.length,
            "prev_selected_answer_id_kind" to WearAnswerTrace.idKind(before.selectedAnswerId),
            "prev_selected_answer_chars" to before.selectedAnswerText.length,
            "cached" to WearAnswerTrace.listShape(localStore.messages(chatId)),
        )
        localStore.setActiveChatId(chatId)
        mutableState.update { current ->
            // `showingChat` keeps the reader for the chat that is already open and
            // clears it only on a real chat switch.
            current.showingChat(
                chatId = chatId,
                cachedMessages = localStore.messages(chatId),
                cachedDraft = localStore.draft(chatId),
            )
        }
    }

    private fun openCreatedChat(chat: Chat) {
        val chats = listOf(chat) + mutableState.value.chats.filterNot { it.id == chat.id }
        localStore.saveChats(chats)
        localStore.saveMessages(chat.id, emptyList())
        localStore.setActiveChatId(chat.id)
        mutableState.update {
            it.copy(
                chats = chats,
                activeChatId = chat.id,
                messages = emptyList(),
                messagesChatId = chat.id,
                contentChatId = chat.id,
                draft = "",
                pendingQuestion = "",
                pendingBaseMessageId = null,
                streamingAnswer = "",
                selectedAnswerId = null,
                selectedAnswerText = "",
                stage = ProcessingStage.READY,
                error = null,
            )
        }
    }

    private fun withoutPendingDeletes(chats: List<Chat>): List<Chat> {
        val pendingDeletes = localStore.pendingChatDeletes()
        return chats.filterNot { it.id in pendingDeletes }
    }

    private fun syncPendingChatDeletes() {
        if (token.isBlank() || chatDeleteSyncRunning || localStore.pendingChatDeletes().isEmpty()) return
        chatDeleteSyncRunning = true
        viewModelScope.launch {
            var retryDelayMs = CHAT_DELETE_INITIAL_RETRY_MS
            while (true) {
                val chatId = localStore.pendingChatDeletes().firstOrNull() ?: break
                val deleted = runCatching {
                    gateway.deleteChat(chatId)
                    true
                }.recover { error ->
                    if (error is WristMindApiException && error.statusCode == 404) true else false
                }.getOrDefault(false)
                if (deleted) {
                    localStore.clearPendingChatDelete(chatId)
                    retryDelayMs = CHAT_DELETE_INITIAL_RETRY_MS
                } else {
                    delay(retryDelayMs)
                    retryDelayMs = (retryDelayMs * 2).coerceAtMost(CHAT_DELETE_MAX_RETRY_MS)
                }
            }
            chatDeleteSyncRunning = false
            // A new optimistic delete can arrive just as this coroutine is finishing.
            if (localStore.pendingChatDeletes().isNotEmpty()) syncPendingChatDeletes()
        }
    }

    private companion object {
        const val TAG = "WristMindWear"
        // Idle-window and reconnect tuning lives in WearStreamResume; only the
        // task-specific budgets below stay next to the flow that uses them.
        const val CURSOR_PERSIST_INTERVAL_MS = 250L
        const val CHAT_DELETE_INITIAL_RETRY_MS = 5_000L
        const val CHAT_DELETE_MAX_RETRY_MS = 60_000L
        const val ACCEPTED_RECOVERY_DELAY_MS = 2_000L
        const val MAX_ACCEPTED_RECOVERY_PROBES = 15
        const val MAX_QUEUED_RECOVERY_PROBES = 5
        const val FALLBACK_HISTORY_MESSAGES = 6
        const val MAIN_RECOVERY_CONFIRMATIONS = 2
        val QUEUED_RECOVERY_DELAYS_MS = longArrayOf(2_000, 4_000, 8_000, 12_000, 18_000)
        val RESUMABLE_SUBMISSION_STATES = setOf(
            SubmissionState.QUEUED,
            SubmissionState.ACCEPTED,
            SubmissionState.STREAMING,
        )
    }
}
