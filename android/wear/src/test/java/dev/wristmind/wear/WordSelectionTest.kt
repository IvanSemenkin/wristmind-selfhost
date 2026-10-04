package dev.wristmind.wear

import androidx.compose.ui.text.TextRange
import org.junit.Assert.assertEquals
import org.junit.Test

class WordSelectionTest {
    @Test
    fun `tap inside Russian word selects the whole word`() {
        assertEquals(TextRange(8, 14), wordSelectionAt("Исправь погода завтра", 11))
    }

    @Test
    fun `hyphenated word stays one correction target`() {
        assertEquals(TextRange(0, 5), wordSelectionAt("из-за дождя", 2))
    }

    @Test
    fun `tap on punctuation keeps a precise cursor`() {
        assertEquals(TextRange(6), wordSelectionAt("Привет, мир", 6))
    }

    @Test
    fun `tap at text end selects the preceding word`() {
        assertEquals(TextRange(7, 10), wordSelectionAt("Привет мир", 10))
    }
}
