package dev.wristmind.wear

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import dev.wristmind.core.WristMindApiException
import java.io.IOException
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue

class WearRetryPolicyTest {
    @Test
    fun permanentHttpErrorsAreNotTreatedAsNetworkFailures() {
        for (status in listOf(400, 401, 403, 404, 409, 422)) {
            assertFalse("HTTP $status", WearRetryPolicy.isRetryable(WristMindApiException(status, "error")))
        }
        for (status in listOf(408, 429, 500, 502, 503, 504)) {
            assertTrue("HTTP $status", WearRetryPolicy.isRetryable(WristMindApiException(status, "error")))
        }
        assertTrue(WearRetryPolicy.isRetryable(IOException("radio handover")))
    }
    @Test
    fun streamRecoveryIsFiniteAndBackoffMatchesAttemptCount() {
        assertEquals(3, WearRetryPolicy.MAX_SEND_ATTEMPTS)
        assertEquals(1_000L, WearRetryPolicy.SEND_RETRY_DELAY_MS)
        assertEquals(3, WearRetryPolicy.MAX_STREAM_RECONNECTS)
        assertArrayEquals(longArrayOf(500, 1_000, 2_000), WearRetryPolicy.BACKOFF_MS)
        assertEquals(WearRetryPolicy.MAX_STREAM_RECONNECTS, WearRetryPolicy.BACKOFF_MS.size)
    }
}
