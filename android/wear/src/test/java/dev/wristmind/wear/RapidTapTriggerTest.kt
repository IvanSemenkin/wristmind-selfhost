package dev.wristmind.wear

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RapidTapTriggerTest {
    @Test
    fun `exactly seven quick taps trigger once`() {
        val trigger = RapidTapTrigger()
        repeat(6) { index -> assertFalse(trigger.onTap(1_000L + index * 300L)) }
        assertTrue(trigger.onTap(2_800L))
        assertFalse(trigger.onTap(3_100L))
    }

    @Test
    fun `a pause restarts the count`() {
        val trigger = RapidTapTrigger()
        repeat(6) { index -> assertFalse(trigger.onTap(1_000L + index * 300L)) }
        assertFalse(trigger.onTap(3_500L))
        repeat(5) { index -> assertFalse(trigger.onTap(3_800L + index * 300L)) }
        assertTrue(trigger.onTap(5_300L))
    }
}
