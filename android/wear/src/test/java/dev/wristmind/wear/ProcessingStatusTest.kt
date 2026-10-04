package dev.wristmind.wear

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProcessingStatusTest {
    @Test
    fun `every answer progress event has a visible and active watch stage`() {
        val states = listOf(
            "queued", "context", "routing", "using_chat_source", "framing_request",
            "source_intent", "search_query", "searching", "reviewing_sources",
            "opening_source", "evaluating_source", "extracting_source", "saving_source",
            "search_no_results", "search_unavailable", "research_drafting",
            "research_checking", "research_refining", "generating",
        )

        states.forEach { serverState ->
            val stage = processingStageFromServerState(serverState)
            assertTrue("No stage for $serverState", stage != null)
            assertTrue("Not active: $serverState", WearState(stage = stage!!).operationActive)
            assertTrue("No label for $serverState", processingLabel(stage).isNotBlank())
        }
    }

    @Test
    fun `unknown event does not map back to sending`() {
        assertNull(processingStageFromServerState("future_server_stage"))
    }

    @Test
    fun `source review and research answer check are distinct`() {
        assertEquals("Сверяю найденное…", processingLabel(ProcessingStage.REVIEWING_SOURCES))
        assertEquals("Ищу источники · 2…", processingLabel(ProcessingStage.SEARCHING, 2))
        assertEquals("Проверяю ответ…", processingLabel(ProcessingStage.RESEARCH_CHECKING))
        assertEquals("Поиск недоступен…", processingLabel(ProcessingStage.SEARCH_UNAVAILABLE))
    }

    @Test
    fun `fallback status does not claim web search`() {
        val stage = ProcessingStage.FALLBACK_GENERATING
        assertTrue(WearState(stage = stage).operationActive)
        assertEquals("Резервный сервер отвечает…", processingLabel(stage))
    }
}
