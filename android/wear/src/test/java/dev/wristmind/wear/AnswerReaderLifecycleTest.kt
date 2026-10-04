package dev.wristmind.wear

import dev.wristmind.core.ChatMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Lifecycle of the full-answer reader ("Ответ" screen).
 *
 * These tests model the exact `WearState` transitions performed by
 * `WearViewModel` (delta append, `finalizeSubmissionLocally`,
 * `finalizeSubmissionFromServer`, `loadChat`, `showingChat`/`showLocalChat`) and
 * assert what `selectedAnswerContent` — the only input of `FullAnswerScreen` —
 * returns. The reader must survive a background refresh for the same chat and be
 * cleared only by a real chat switch.
 */
class AnswerReaderLifecycleTest {

    private val question = "Объясни второй закон Ньютона"
    private val firstChunk = "F = m·a. "
    private val secondChunk = "Ускорение пропорционально силе."
    private val fullAnswer = firstChunk + secondChunk

    private val serverTail = listOf(
        ChatMessage(id = "user-1", role = "user", content = question, status = "complete"),
        // The server creates this placeholder before generation starts.
        ChatMessage(id = "assistant-1", role = "assistant", content = "", status = "streaming"),
    )

    private val completedMessages = listOf(
        ChatMessage(id = "user-1", role = "user", content = question, status = "complete"),
        ChatMessage(id = "assistant-1", role = "assistant", content = fullAnswer, status = "complete"),
    )

    /** `applyEvent("delta")` only appends while the stream still targets the visible chat. */
    private fun WearState.appendStream(delta: String) =
        copy(stage = ProcessingStage.GENERATING, streamingAnswer = streamingAnswer + delta)

    private fun readerOpenAfterComplete() = WearState(
        activeChatId = "chat-1",
        contentChatId = "chat-1",
        messages = completedMessages,
        messagesChatId = "chat-1",
        streamingAnswer = "",
        selectedAnswerId = "assistant-1",
        selectedAnswerText = fullAnswer,
        stage = ProcessingStage.COMPLETE,
    )

    @Test
    fun `reader follows the live stream while deltas arrive`() {
        var state = WearState(
            activeChatId = "chat-1",
            contentChatId = "chat-1",
            streamingAnswer = "",
            selectedAnswerId = STREAMING_ANSWER_ID,
            selectedAnswerText = "",
        )

        state = state.appendStream(firstChunk)
        assertEquals(firstChunk, selectedAnswerContent(state))

        state = state.appendStream(secondChunk)
        assertEquals(fullAnswer, selectedAnswerContent(state))
    }

    @Test
    fun `reader keeps the streamed text across a history refetch during streaming`() {
        var state = WearState(
            activeChatId = "chat-1",
            contentChatId = "chat-1",
            stage = ProcessingStage.GENERATING,
            streamingAnswer = fullAnswer,
            selectedAnswerId = STREAMING_ANSWER_ID,
            selectedAnswerText = firstChunk,
        )

        // `loadChat` keeps the live buffer and only swaps the message list for the
        // server snapshot (user + empty assistant placeholder).
        val preserveLiveStream = state.streamingAnswer.isNotBlank() ||
            state.selectedAnswerId == STREAMING_ANSWER_ID
        assertTrue(preserveLiveStream)
        state = state.copy(messages = serverTail, messagesChatId = "chat-1")

        assertEquals(fullAnswer, selectedAnswerContent(state))
    }

    @Test
    fun `reader keeps the answer after a local complete`() {
        val state = readerOpenAfterComplete().copy(
            messages = completedMessages,
            selectedAnswerId = "local-assistant-request-1",
            selectedAnswerText = fullAnswer,
        )

        assertEquals(fullAnswer, selectedAnswerContent(state))
    }

    @Test
    fun `reader keeps the answer after a server complete`() {
        assertEquals(fullAnswer, selectedAnswerContent(readerOpenAfterComplete()))
    }

    /**
     * The reported defect: `complete` -> FCM `state_changed` -> `refreshData()` ->
     * `showLocalChat()`. The reader is derived state, so a refresh for the chat
     * that is already open must leave it untouched.
     */
    @Test
    fun `background refresh after complete keeps the reader`() {
        val afterComplete = readerOpenAfterComplete()
        assertEquals(fullAnswer, selectedAnswerContent(afterComplete))

        val afterRefresh = afterComplete.showingChat(
            chatId = "chat-1",
            cachedMessages = completedMessages,
            cachedDraft = "",
        )

        assertEquals(fullAnswer, selectedAnswerContent(afterRefresh))
        assertEquals(fullAnswer, afterRefresh.selectedAnswerText)
        assertEquals(fullAnswer, selectedAnswerContent(
            afterRefresh.copy(messages = completedMessages, messagesChatId = "chat-1"),
        ))
    }

    @Test
    fun `background refresh during streaming keeps the live buffer and the stage`() {
        val streaming = WearState(
            activeChatId = "chat-1",
            contentChatId = "chat-1",
            stage = ProcessingStage.GENERATING,
            streamingAnswer = fullAnswer,
            selectedAnswerId = STREAMING_ANSWER_ID,
            selectedAnswerText = firstChunk,
        )
        assertEquals(fullAnswer, selectedAnswerContent(streaming))

        // showLocalChat() runs before loadChat() inside refreshData().
        val refreshed = streaming.showingChat("chat-1", serverTail, cachedDraft = "")
        assertEquals(fullAnswer, selectedAnswerContent(refreshed))
        assertEquals(fullAnswer, refreshed.streamingAnswer)
        assertEquals(ProcessingStage.GENERATING, refreshed.stage)
        assertTrue(refreshed.operationActive)

        // The server snapshot then replaces the message list only.
        val afterLoad = refreshed.copy(messages = serverTail, messagesChatId = "chat-1")
        assertEquals(fullAnswer, selectedAnswerContent(afterLoad))
    }

    @Test
    fun `switching chats still clears the reader`() {
        val open = WearState(
            activeChatId = "chat-1",
            contentChatId = "chat-1",
            stage = ProcessingStage.GENERATING,
            streamingAnswer = fullAnswer,
            selectedAnswerId = STREAMING_ANSWER_ID,
            selectedAnswerText = fullAnswer,
        )

        val switched = open.showingChat("chat-2", cachedMessages = emptyList(), cachedDraft = "")

        assertEquals("", selectedAnswerContent(switched))
        assertNull(switched.selectedAnswerId)
        assertEquals("", switched.selectedAnswerText)
        assertEquals("", switched.streamingAnswer)
        assertEquals(ProcessingStage.READY, switched.stage)
    }

    /**
     * A blank stream buffer must never reach `localStore`: writing an empty
     * assistant message would replace a complete answer with a blank bubble.
     */
    @Test
    fun `blank stream does not overwrite a complete answer`() {
        assertNull(
            completedMessagesFor(
                cachedMessages = completedMessages,
                pendingText = question,
                requestId = "request-1",
                streamedAnswer = "",
            ),
        )

        val persisted = completedMessagesFor(
            cachedMessages = completedMessages,
            pendingText = question,
            requestId = "request-1",
            streamedAnswer = fullAnswer,
        )
        assertNotNull(persisted)
        assertEquals(fullAnswer, persisted!!.last().content)
        assertEquals("assistant", persisted.last().role)
    }

    @Test
    fun `completed transcript appends the local user turn when the server has not stored it yet`() {
        val persisted = completedMessagesFor(
            cachedMessages = emptyList(),
            pendingText = question,
            requestId = "request-2",
            streamedAnswer = fullAnswer,
        )
        assertNotNull(persisted)
        assertEquals(listOf("user", "assistant"), persisted!!.map { it.role })
        assertEquals(question, persisted.first().content)
        assertEquals(fullAnswer, persisted.last().content)
    }
}
