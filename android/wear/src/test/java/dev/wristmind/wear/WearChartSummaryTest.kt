package dev.wristmind.wear

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class WearChartSummaryTest {
    private val data = """{"title":"Парабола","summary":"Минимум при x=0.","points":[[-1,1],[0,0],[1,1]]}"""
    @Test fun chartDisplaysCompactTextInAnswerAndPreview() {
        val content = "```chart\n$data\n```"
        assertEquals(listOf(MarkdownBlock.Paragraph("График: Парабола. Минимум при x=0.")), parseMarkdown(content))
        assertEquals("График: Парабола. Минимум при x=0.", previewPlainText(content))
    }
    @Test fun partialChartDoesNotExposeDataDuringStreaming() {
        assertEquals("График формируется…", previewPlainText("```chart\n{"))
    }
    @Test fun invalidChartRemainsOrdinaryCode() {
        assertNull(chartSummary("{"))
        assertTrue(parseMarkdown("```chart\n{\n```").single() is MarkdownBlock.Code)
    }
}
