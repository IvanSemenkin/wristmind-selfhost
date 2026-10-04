package dev.wristmind.wear

import dev.wristmind.core.ChatMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PendingQuestionVisibilityTest {
    private fun message(id: String, role: String, content: String) =
        ChatMessage(id = id, role = role, content = content, status = "complete")

    @Test
    fun serverUserCopyIsFoundBeforeAssistantPlaceholder() {
        val messages = listOf(
            message("old-answer", "assistant", "Привет"),
            message("new-question", "user", "Вопрос"),
            message("new-answer", "assistant", ""),
        )

        assertEquals(1, pendingServerUserIndex(messages, "Вопрос", "old-answer"))
    }

    @Test
    fun earlierIdenticalQuestionDoesNotHideNewPendingQuestion() {
        val messages = listOf(
            message("old-question", "user", "Вопрос"),
            message("old-answer", "assistant", "Ответ"),
        )

        assertNull(pendingServerUserIndex(messages, "Вопрос", "old-answer"))
    }

    @Test
    fun trailingStreamingServerTurnReplacesOptimisticQuestionAfterFallbackCacheMigration() {
        val messages = listOf(
            message("synced-fallback-question", "user", "Предыдущий вопрос"),
            message("synced-fallback-answer", "assistant", "Предыдущий ответ"),
            message("new-question", "user", "Текст с сервера"),
            ChatMessage(
                id = "new-answer",
                role = "assistant",
                content = "",
                status = "streaming",
            ),
        )

        assertEquals(
            2,
            pendingServerUserIndex(
                messages = messages,
                pendingQuestion = "Локальная оптимистичная копия",
                baseMessageId = "local-assistant-id-before-sync",
            ),
        )
    }

    @Test
    fun completedServerTurnDoesNotHideAGenuinelyNewPendingQuestion() {
        val messages = listOf(
            message("old-question", "user", "Предыдущий вопрос"),
            message("old-answer", "assistant", "Предыдущий ответ"),
        )

        assertNull(
            pendingServerUserIndex(
                messages = messages,
                pendingQuestion = "Новый вопрос",
                baseMessageId = "old-answer",
            ),
        )
    }
}
