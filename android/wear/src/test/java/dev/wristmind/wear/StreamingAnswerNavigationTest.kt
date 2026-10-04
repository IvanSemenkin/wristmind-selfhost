package dev.wristmind.wear

import org.junit.Assert.assertEquals
import dev.wristmind.core.ChatMessage
import org.junit.Test

class StreamingAnswerNavigationTest {
    @Test
    fun `selected full answer follows the live stream`() {
        val state = WearState(
            selectedAnswerId = STREAMING_ANSWER_ID,
            streamingAnswer = "Первая часть ответа",
        )

        assertEquals("Первая часть ответа", selectedAnswerContent(state))
        assertEquals(
            "Первая часть ответа. Вторая часть.",
            selectedAnswerContent(state.copy(streamingAnswer = "Первая часть ответа. Вторая часть.")),
        )
    }

    @Test
    fun `selected full answer keeps server text during live stream hand-off`() {
        val state = WearState(
            selectedAnswerId = STREAMING_ANSWER_ID,
            streamingAnswer = "",
            messages = listOf(
                ChatMessage(id = "assistant-1", role = "assistant", content = "Ответ уже сохранён", status = "complete"),
            ),
        )

        assertEquals("Ответ уже сохранён", selectedAnswerContent(state))
    }

    @Test
    fun `selected full answer survives replacement of local message by server snapshot`() {
        val state = WearState(
            selectedAnswerId = "local-assistant-request-1",
            selectedAnswerText = "Полный ответ, который уже читает пользователь",
            messages = listOf(
                ChatMessage(id = "server-assistant-1", role = "assistant", content = "", status = "complete"),
            ),
        )

        assertEquals(
            "Полный ответ, который уже читает пользователь",
            selectedAnswerContent(state),
        )
    }
}
