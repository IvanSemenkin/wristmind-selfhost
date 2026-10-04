package dev.wristmind.wear

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class WearRetryPolicyTest {
    @Test
    fun streamRecoveryIsFiniteAndBackoffMatchesAttemptCount() {
        assertEquals(3, WearRetryPolicy.MAX_SEND_ATTEMPTS)
        assertEquals(1_000L, WearRetryPolicy.SEND_RETRY_DELAY_MS)
        assertEquals(3, WearRetryPolicy.MAX_STREAM_RECONNECTS)
        assertArrayEquals(longArrayOf(500, 1_000, 2_000), WearRetryPolicy.BACKOFF_MS)
        assertEquals(WearRetryPolicy.MAX_STREAM_RECONNECTS, WearRetryPolicy.BACKOFF_MS.size)
    }
}
