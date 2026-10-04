package dev.wristmind.wear

import dev.wristmind.core.ServerEvent
import java.io.IOException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Cursor-based SSE resume policy.
 *
 * The budget must bound **idle** time, never the lifetime of a subscription: a
 * healthy long answer keeps streaming on one connection, while a stalled one is
 * abandoned so the caller can resume from the durable cursor.
 */
class WearStreamResumeTest {

    @Test
    fun `a long answer is not interrupted just because it is long`() = runTest {
        // 30 deltas 10 s apart = 300 s of virtual time, far beyond the old 70 s
        // subscription lifetime, and shorter than the idle budget per gap.
        val events = flow {
            repeat(30) { index ->
                emit(ServerEvent(index + 1L, "delta", """{"text":"x"}"""))
                delay(10_000)
            }
            emit(ServerEvent(31L, "complete", "{}"))
        }

        var applied = 0
        val outcome = collectStreamWindow(events, WearStreamResume.STREAM_IDLE_TIMEOUT_MS) { event ->
            applied += 1
            event.type == "complete"
        }

        assertEquals(StreamWindowOutcome.Terminal, outcome)
        assertEquals(31, applied)
    }

    @Test
    fun `an idle subscription is abandoned after the idle budget`() = runTest {
        val events = flow {
            emit(ServerEvent(1L, "delta", """{"text":"x"}"""))
            awaitCancellation()
        }

        assertEquals(
            StreamWindowOutcome.Idle,
            collectStreamWindow(events, WearStreamResume.STREAM_IDLE_TIMEOUT_MS) { false },
        )
    }

    @Test
    fun `complete immediately after the last delta is terminal`() = runTest {
        val events = flow {
            emit(ServerEvent(1L, "delta", """{"text":"a"}"""))
            emit(ServerEvent(2L, "complete", "{}"))
        }

        assertEquals(
            StreamWindowOutcome.Terminal,
            collectStreamWindow(events, WearStreamResume.STREAM_IDLE_TIMEOUT_MS) { it.type == "complete" },
        )
    }

    @Test
    fun `a subscription that ends without a terminal event is closed`() = runTest {
        assertEquals(
            StreamWindowOutcome.Closed,
            collectStreamWindow(flow { emit(ServerEvent(1L, "delta", "{}")) }, 1_000L) { false },
        )
    }

    @Test
    fun `a failing subscription is reported as failed`() = runTest {
        val boom = IOException("sse dropped")
        val events = flow<ServerEvent> { throw boom }

        assertEquals(
            StreamWindowOutcome.Failed(boom),
            collectStreamWindow(events, WearStreamResume.STREAM_IDLE_TIMEOUT_MS) { false },
        )
    }

    @Test
    fun `idle budget is generous once the stream has produced data`() {
        val policy = StreamResumePolicy()

        assertEquals(
            WearStreamResume.FIRST_STREAM_EVENT_TIMEOUT_MS,
            policy.idleBudgetMs(receivedAnyEvent = false),
        )
        assertEquals(
            WearStreamResume.STREAM_IDLE_TIMEOUT_MS,
            policy.idleBudgetMs(receivedAnyEvent = true),
        )
        // The old fixed subscription lifetime must no longer bound an active stream.
        assertTrue(WearStreamResume.STREAM_IDLE_TIMEOUT_MS > 70_000L)
    }

    @Test
    fun `reconnect counter is cleared by a delivered event`() {
        val policy = StreamResumePolicy()

        assertEquals(500L, policy.nextAttemptDelayMs(receivedAnyEvent = true))
        assertEquals(1_000L, policy.nextAttemptDelayMs(receivedAnyEvent = true))
        assertEquals(2_000L, policy.nextAttemptDelayMs(receivedAnyEvent = true))
        assertNull(policy.nextAttemptDelayMs(receivedAnyEvent = true))

        // An event proves the route works again: the budget restarts.
        policy.onEventReceived()
        assertEquals(0, policy.consecutiveReconnects)
        assertEquals(500L, policy.nextAttemptDelayMs(receivedAnyEvent = true))
    }

    @Test
    fun `total reconnect budget bounds a stream that never makes progress`() {
        val policy = StreamResumePolicy(maxTotalReconnects = 2)

        assertEquals(500L, policy.nextAttemptDelayMs(receivedAnyEvent = true))
        assertEquals(1_000L, policy.nextAttemptDelayMs(receivedAnyEvent = true))

        // A delivered event resets only the consecutive counter, not the total.
        policy.onEventReceived()
        assertNull(policy.nextAttemptDelayMs(receivedAnyEvent = true))
        assertEquals(2, policy.totalReconnects)
    }

    @Test
    fun `silent probes are bounded before the first event`() {
        val policy = StreamResumePolicy(maxSilentProbes = 3)

        assertEquals(100L, policy.nextAttemptDelayMs(receivedAnyEvent = false))
        assertEquals(100L, policy.nextAttemptDelayMs(receivedAnyEvent = false))
        assertEquals(100L, policy.nextAttemptDelayMs(receivedAnyEvent = false))
        assertNull(policy.nextAttemptDelayMs(receivedAnyEvent = false))

        policy.onEventReceived()
        assertEquals(100L, policy.nextAttemptDelayMs(receivedAnyEvent = false))
    }
}
