package dev.wristmind.wear

import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceDraftComposerTest {
    @Test
    fun `voice transcript is appended with one space`() {
        val composer = VoiceDraftComposer("Уже набрано")

        assertEquals("Уже набрано продолжение вопроса", composer.merge("продолжение вопроса"))
        assertEquals("Уже набрано финальная версия", composer.merge("финальная версия"))
    }

    @Test
    fun `blank transcript leaves the draft unchanged`() {
        assertEquals("Исправь это ", VoiceDraftComposer("Исправь это ").merge("  "))
    }
}
