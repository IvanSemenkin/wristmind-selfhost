package dev.wristmind.wear

import android.content.Context
import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import dev.wristmind.core.Mode
import org.json.JSONArray
import org.json.JSONObject

data class PendingSubmission(
    val chatId: String,
    val requestId: String,
    val text: String,
    val jobId: String?,
    val cursor: Long,
    val state: SubmissionState,
    val baseMessageId: String? = null,
    val webSearch: Boolean = false,
    val webResearch: Boolean = false,
    val researchMode: Boolean = false,
)

data class FallbackExchange(
    val chatId: String,
    val requestId: String,
    val userText: String,
    val assistantText: String,
)

data class OfflineChat(
    val chatId: String,
    val modeId: String,
    val modeName: String,
    val createRequestId: String,
    val quick: Boolean,
)

enum class AnswerSearchMode(
    val webSearch: Boolean,
    val webResearch: Boolean,
    val researchMode: Boolean,
) {
    AUTO(false, false, false),
    // Research adds drafting/review, while the server's local-first router
    // independently decides whether this turn needs the internet.
    RESEARCH(false, false, true),
    ;

    fun next(): AnswerSearchMode = entries[(ordinal + 1) % entries.size]
}

enum class SubmissionState {
    QUEUED,
    ACCEPTED,
    STREAMING,
    COMPLETE,
    FAILED,
    CANCELLED,
}

class WearLocalStore(context: Context) {
    private val preferences = context.getSharedPreferences("wristmind_wear_state", Context.MODE_PRIVATE)

    fun activeChatId(): String? = preferences.getString(KEY_ACTIVE_CHAT, null)

    fun setActiveChatId(chatId: String?) {
        preferences.edit().apply {
            if (chatId == null) remove(KEY_ACTIVE_CHAT) else putString(KEY_ACTIVE_CHAT, chatId)
        }.apply()
    }

    fun answerSearchMode(): AnswerSearchMode = preferences.getString(KEY_ANSWER_SEARCH_MODE, null)
        ?.let { saved ->
            // The removed blue quick-search position becomes the next useful
            // option instead of silently dropping a previously chosen mode.
            if (saved == "QUICK_SEARCH" || saved == "PRO_SEARCH" || saved == "NORMAL") AnswerSearchMode.AUTO
            else AnswerSearchMode.entries.firstOrNull { it.name == saved }
        }
        ?: AnswerSearchMode.AUTO

    fun saveAnswerSearchMode(mode: AnswerSearchMode) {
        preferences.edit().putString(KEY_ANSWER_SEARCH_MODE, mode.name).apply()
    }

    fun draft(chatId: String): String = drafts().optString(chatId)

    fun saveDraft(chatId: String, text: String) {
        val values = drafts()
        if (text.isBlank()) values.remove(chatId) else values.put(chatId, text)
        preferences.edit().putString(KEY_DRAFTS, values.toString()).apply()
    }

    fun pending(chatId: String): PendingSubmission? {
        val value = runCatching { JSONObject(preferences.getString(KEY_PENDING, "{}") ?: "{}") }.getOrNull()
            ?.optJSONObject(chatId) ?: return null
        val requestId = value.optString("request_id")
        val text = value.optString("text")
        if (requestId.isBlank() || text.isBlank()) return null
        return PendingSubmission(
            chatId = chatId,
            requestId = requestId,
            text = text,
            jobId = value.optString("job_id").ifBlank { null },
            cursor = value.optLong("cursor"),
            state = value.optString("state")
                .let { saved -> SubmissionState.entries.firstOrNull { it.name == saved } }
                ?: if (value.optString("job_id").isBlank()) SubmissionState.QUEUED else SubmissionState.ACCEPTED,
            baseMessageId = value.optString("base_message_id").ifBlank { null },
            webSearch = value.optBoolean("web_search"),
            webResearch = value.optBoolean("web_research"),
            researchMode = value.optBoolean("research_mode"),
        )
    }

    fun pendingSubmissions(): List<PendingSubmission> = runCatching {
        val all = JSONObject(preferences.getString(KEY_PENDING, "{}") ?: "{}")
        all.keys().asSequence().mapNotNull { chatId -> pending(chatId) }.toList()
    }.getOrDefault(emptyList())

    fun savePending(value: PendingSubmission) {
        val all = runCatching { JSONObject(preferences.getString(KEY_PENDING, "{}") ?: "{}") }
            .getOrElse { JSONObject() }
        val existing = all.optJSONObject(value.chatId)
        val existingState = existing?.optString("state")
            ?.let { saved -> SubmissionState.entries.firstOrNull { it.name == saved } }
        val existingCursor = existing?.optLong("cursor") ?: 0L
        // The initial queued write intentionally runs independently from Send. Never let a
        // late disk write overwrite an already accepted job or a newer SSE cursor.
        if (existingState != null && existingState.ordinal > value.state.ordinal) return
        if (existingState == value.state && existingCursor > value.cursor) return
        all.put(
            value.chatId,
            JSONObject()
                .put("request_id", value.requestId)
                .put("text", value.text)
                .put("job_id", value.jobId.orEmpty())
                .put("cursor", value.cursor)
                .put("state", value.state.name)
                .put("base_message_id", value.baseMessageId.orEmpty())
                .put("web_search", value.webSearch)
                .put("web_research", value.webResearch)
                .put("research_mode", value.researchMode),
        )
        preferences.edit().putString(KEY_PENDING, all.toString()).apply()
    }

    fun clearPending(chatId: String) {
        val all = runCatching { JSONObject(preferences.getString(KEY_PENDING, "{}") ?: "{}") }
            .getOrElse { JSONObject() }
        all.remove(chatId)
        preferences.edit().putString(KEY_PENDING, all.toString()).apply()
    }

    fun clearChat(chatId: String) {
        saveDraft(chatId, "")
        clearPending(chatId)
        removeMessages(chatId)
        if (activeChatId() == chatId) setActiveChatId(null)
        removeOfflineChat(chatId)
        saveFallbackExchanges(fallbackExchanges().filterNot { it.chatId == chatId })
    }

    fun pendingChatDeletes(): Set<String> = runCatching {
        val values = JSONArray(preferences.getString(KEY_PENDING_CHAT_DELETES, "[]") ?: "[]")
        buildSet { repeat(values.length()) { add(values.optString(it)) } }
            .filter(String::isNotBlank)
            .toSet()
    }.getOrDefault(emptySet())

    fun enqueueChatDelete(chatId: String) {
        savePendingChatDeletes(pendingChatDeletes() + chatId)
    }

    fun clearPendingChatDelete(chatId: String) {
        savePendingChatDeletes(pendingChatDeletes() - chatId)
    }

    fun cachedModes(): List<Mode> = readArray(KEY_MODES) { value ->
        Mode(
            id = value.optString("id"),
            name = value.optString("name"),
            color = value.optString("color"),
            icon = value.optString("icon"),
            systemPrompt = value.optString("system_prompt"),
            responseModelId = value.optString("response_model_id"),
            hiddenOnWatch = value.optBoolean("hidden_on_watch"),
        )
    }

    fun saveModes(values: List<Mode>) = writeArray(KEY_MODES, values) { value ->
        JSONObject()
            .put("id", value.id)
            .put("name", value.name)
            .put("color", value.color)
            .put("icon", value.icon)
            .put("system_prompt", value.systemPrompt)
            .put("response_model_id", value.responseModelId)
            .put("hidden_on_watch", value.hiddenOnWatch)
    }

    fun cachedChats(): List<Chat> = readArray(KEY_CHATS) { value ->
        Chat(
            id = value.optString("id"),
            modeId = value.optString("mode_id"),
            modeName = value.optString("mode_name"),
            modeDeleted = value.optBoolean("mode_deleted"),
            title = value.optString("title"),
        )
    }

    fun saveChats(values: List<Chat>) = writeArray(KEY_CHATS, values) { value ->
        JSONObject()
            .put("id", value.id)
            .put("mode_id", value.modeId)
            .put("mode_name", value.modeName)
            .put("mode_deleted", value.modeDeleted)
            .put("title", value.title)
    }

    fun messages(chatId: String): List<ChatMessage> = readArray("$KEY_MESSAGES_PREFIX$chatId") { value ->
        ChatMessage(
            id = value.optString("id"),
            role = value.optString("role"),
            content = value.optString("content"),
            status = value.optString("status"),
        )
    }

    fun saveMessages(chatId: String, values: List<ChatMessage>) =
        writeArray("$KEY_MESSAGES_PREFIX$chatId", values) { value ->
            JSONObject()
                .put("id", value.id)
                .put("role", value.role)
                .put("content", value.content)
                .put("status", value.status)
        }

    fun fallbackExchanges(): List<FallbackExchange> = readArray(KEY_FALLBACK_EXCHANGES) { value ->
        FallbackExchange(
            chatId = value.optString("chat_id"),
            requestId = value.optString("request_id"),
            userText = value.optString("user_text"),
            assistantText = value.optString("assistant_text"),
        )
    }.filter { it.chatId.isNotBlank() && it.requestId.isNotBlank() }

    fun saveFallbackExchange(value: FallbackExchange) {
        val updated = fallbackExchanges().filterNot { it.requestId == value.requestId } + value
        saveFallbackExchanges(updated)
    }

    fun removeFallbackExchange(requestId: String) {
        saveFallbackExchanges(fallbackExchanges().filterNot { it.requestId == requestId })
    }

    fun offlineChats(): List<OfflineChat> = readArray(KEY_OFFLINE_CHATS) { value ->
        OfflineChat(
            chatId = value.optString("chat_id"),
            modeId = value.optString("mode_id"),
            modeName = value.optString("mode_name"),
            createRequestId = value.optString("create_request_id"),
            quick = value.optBoolean("quick"),
        )
    }.filter { it.chatId.isNotBlank() && it.createRequestId.isNotBlank() }

    fun saveOfflineChat(value: OfflineChat) {
        val updated = offlineChats().filterNot { it.chatId == value.chatId } + value
        writeArray(KEY_OFFLINE_CHATS, updated, ::offlineChatJson)
    }

    fun removeOfflineChat(chatId: String) {
        writeArray(KEY_OFFLINE_CHATS, offlineChats().filterNot { it.chatId == chatId }, ::offlineChatJson)
    }

    fun migrateChat(oldChatId: String, newChat: Chat) {
        val oldMessages = messages(oldChatId)
        val oldDraft = draft(oldChatId)
        val oldPending = pending(oldChatId)
        val chats = cachedChats().map { if (it.id == oldChatId) newChat else it }
        saveChats(chats)
        saveMessages(newChat.id, oldMessages)
        saveDraft(newChat.id, oldDraft)
        if (oldPending != null) savePending(oldPending.copy(chatId = newChat.id))
        clearPending(oldChatId)
        removeMessages(oldChatId)
        saveDraft(oldChatId, "")
        saveFallbackExchanges(
            fallbackExchanges().map { if (it.chatId == oldChatId) it.copy(chatId = newChat.id) else it },
        )
        removeOfflineChat(oldChatId)
        if (activeChatId() == oldChatId) setActiveChatId(newChat.id)
    }

    private fun saveFallbackExchanges(values: List<FallbackExchange>) =
        writeArray(KEY_FALLBACK_EXCHANGES, values) { value ->
            JSONObject()
                .put("chat_id", value.chatId)
                .put("request_id", value.requestId)
                .put("user_text", value.userText)
                .put("assistant_text", value.assistantText)
        }

    private fun offlineChatJson(value: OfflineChat) = JSONObject()
        .put("chat_id", value.chatId)
        .put("mode_id", value.modeId)
        .put("mode_name", value.modeName)
        .put("create_request_id", value.createRequestId)
        .put("quick", value.quick)

    private fun removeMessages(chatId: String) {
        preferences.edit().remove("$KEY_MESSAGES_PREFIX$chatId").apply()
    }

    private fun <T> readArray(key: String, mapper: (JSONObject) -> T): List<T> = runCatching {
        val values = JSONArray(preferences.getString(key, "[]") ?: "[]")
        List(values.length()) { mapper(values.getJSONObject(it)) }
    }.getOrDefault(emptyList())

    private fun <T> writeArray(key: String, values: List<T>, mapper: (T) -> JSONObject) {
        val array = JSONArray()
        values.forEach { array.put(mapper(it)) }
        preferences.edit().putString(key, array.toString()).apply()
    }

    private fun drafts() = runCatching {
        JSONObject(preferences.getString(KEY_DRAFTS, "{}") ?: "{}")
    }.getOrElse { JSONObject() }

    private fun savePendingChatDeletes(chatIds: Set<String>) {
        val values = JSONArray()
        chatIds.sorted().forEach(values::put)
        preferences.edit().putString(KEY_PENDING_CHAT_DELETES, values.toString()).apply()
    }

    private companion object {
        const val KEY_ACTIVE_CHAT = "active_chat_id"
        const val KEY_DRAFTS = "drafts"
        const val KEY_PENDING = "pending_submissions"
        const val KEY_PENDING_CHAT_DELETES = "pending_chat_deletes"
        const val KEY_ANSWER_SEARCH_MODE = "answer_search_mode"
        const val KEY_MODES = "cached_modes"
        const val KEY_CHATS = "cached_chats"
        const val KEY_MESSAGES_PREFIX = "cached_messages_"
        const val KEY_FALLBACK_EXCHANGES = "fallback_exchanges"
        const val KEY_OFFLINE_CHATS = "offline_chats"
    }
}
