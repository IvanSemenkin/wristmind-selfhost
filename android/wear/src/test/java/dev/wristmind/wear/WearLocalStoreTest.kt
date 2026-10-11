package dev.wristmind.wear

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class WearLocalStoreTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @Before
    fun clearState() {
        context.getSharedPreferences("wristmind_wear_state", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun draftPendingRequestAndCursorSurviveStoreRecreation() {
        val original = WearLocalStore(context)
        original.setActiveChatId("chat-7")
        original.saveDraft("chat-7", "Сохранённый вопрос")
        original.savePending(
            PendingSubmission(
                "chat-7",
                "request-9",
                "Сохранённый вопрос",
                "job-2",
                41,
                SubmissionState.STREAMING,
                "previous-answer",
                true,
            ),
        )

        val restored = WearLocalStore(context)

        assertEquals("chat-7", restored.activeChatId())
        assertEquals("Сохранённый вопрос", restored.draft("chat-7"))
        assertEquals(
            PendingSubmission(
                "chat-7",
                "request-9",
                "Сохранённый вопрос",
                "job-2",
                41,
                SubmissionState.STREAMING,
                "previous-answer",
                true,
            ),
            restored.pending("chat-7"),
        )
    }

    @Test
    fun pendingChatDeleteSurvivesStoreRecreation() {
        WearLocalStore(context).enqueueChatDelete("chat-8")

        val restored = WearLocalStore(context)

        assertEquals(setOf("chat-8"), restored.pendingChatDeletes())
        restored.clearPendingChatDelete("chat-8")
        assertEquals(emptySet<String>(), restored.pendingChatDeletes())
    }

    @Test
    fun answerSearchModeSurvivesStoreRecreation() {
        WearLocalStore(context).saveAnswerSearchMode(AnswerSearchMode.RESEARCH)

        assertEquals(AnswerSearchMode.RESEARCH, WearLocalStore(context).answerSearchMode())
    }

    @Test
    fun researchModeLeavesInternetChoiceToTheServerRouter() {
        assertEquals(false, AnswerSearchMode.RESEARCH.webSearch)
        assertEquals(false, AnswerSearchMode.RESEARCH.webResearch)
        assertEquals(true, AnswerSearchMode.RESEARCH.researchMode)
    }

    @Test
    fun offlineChatAndFallbackExchangeMigrateToServerChat() {
        val store = WearLocalStore(context)
        val offline = Chat("offline-1", "mode-1", "История", false, "Реформы")
        store.saveChats(listOf(offline))
        store.saveMessages(
            offline.id,
            listOf(ChatMessage("local-user", "user", "Вопрос", "complete")),
        )
        store.setActiveChatId(offline.id)
        store.saveOfflineChat(OfflineChat(offline.id, offline.modeId, offline.modeName, "create-1", false))
        store.saveFallbackExchange(FallbackExchange(offline.id, "request-1", "Вопрос", "Ответ"))
        store.saveDraft(offline.id, "Новый вопрос")
        store.savePending(PendingSubmission(offline.id, "pending-stable", "Новый вопрос", null, 0, SubmissionState.QUEUED))

        val serverChat = offline.copy(id = "server-1")
        store.migrateChat(offline.id, serverChat)

        assertEquals("server-1", store.activeChatId())
        assertEquals(listOf(serverChat), store.cachedChats())
        assertEquals("Вопрос", store.messages("server-1").single().content)
        assertEquals("server-1", store.fallbackExchanges().single().chatId)
        assertEquals(emptyList<OfflineChat>(), store.offlineChats())
        assertEquals("Новый вопрос", store.draft(serverChat.id))
        assertEquals("pending-stable", store.pending(serverChat.id)?.requestId)
        assertEquals(serverChat.id, store.pending(serverChat.id)?.chatId)
        assertEquals(null, store.pending(offline.id))
    }
}
