package dev.wristmind.wear

import dev.wristmind.core.ServerEvent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Why a single SSE subscription ended.
 *
 * Every outcome except [Terminal] is resumable: the durable cursor is never lost,
 * so the next attempt re-subscribes with `after=cursor` and the server replays
 * only what the watch has not applied yet.
 */
internal sealed interface StreamWindowOutcome {
    /** The terminal event was applied. */
    data object Terminal : StreamWindowOutcome

    /** No event arrived for the idle budget: the route looks stalled. */
    data object Idle : StreamWindowOutcome

    /** The server ended the subscription without a terminal event. */
    data object Closed : StreamWindowOutcome

    /** The subscription failed. */
    data class Failed(val error: Throwable) : StreamWindowOutcome
}

/** Tuning for [collectStreamWindow] and [StreamResumePolicy]. */
internal object WearStreamResume {
    /**
     * Maximum silence *between* events before a subscription is considered dead.
     *
     * This is deliberately not the lifetime of the subscription: an answer that
     * keeps producing tokens stays on one connection no matter how long it takes.
     * The value is larger than the longest legitimate silent gap — the server can
     * be quiet while a research draft/review round runs (research_max_seconds is
     * 75 s) — while still detecting a silently dropped SSE route.
     */
    const val STREAM_IDLE_TIMEOUT_MS = 90_000L

    /**
     * Budget for the very first event. A mobile network can accept HTTPS and then
     * buffer the stream forever, so before the first event the durable job state
     * is checked frequently instead of waiting for a full idle window.
     */
    const val FIRST_STREAM_EVENT_TIMEOUT_MS = 1_200L
    const val FIRST_EVENT_PROBE_DELAY_MS = 100L
    const val MAX_SILENT_PROBES = 60

    /**
     * Hard stop for a pathological "one event, then stall" loop. The consecutive
     * reconnect budget is cleared by every delivered event, so this only bounds
     * streams that never make progress.
     */
    const val MAX_TOTAL_RECONNECTS = 60
}

/**
 * Collects exactly one subscription of [events].
 *
 * [idleBudgetMs] bounds the time between events, never the lifetime of the
 * subscription. A healthy long answer therefore keeps its connection, while a
 * stalled one is abandoned so the caller can resume from the durable cursor.
 *
 * [onEvent] returns `true` once the terminal event has been applied.
 */
internal suspend fun collectStreamWindow(
    events: Flow<ServerEvent>,
    idleBudgetMs: Long,
    onEvent: suspend (ServerEvent) -> Boolean,
): StreamWindowOutcome = coroutineScope {
    val heartbeats = Channel<Unit>(Channel.CONFLATED)
    var terminal = false
    var idle = false
    var failure: Throwable? = null

    val collector = launch {
        try {
            events.collect { event ->
                // Every delivered event re-arms the idle watchdog.
                heartbeats.trySend(Unit)
                terminal = onEvent(event) || terminal
            }
        } catch (cancellation: CancellationException) {
            throw cancellation
        } catch (error: Throwable) {
            failure = error
        }
    }
    val watchdog = launch {
        while (true) {
            if (withTimeoutOrNull(idleBudgetMs) { heartbeats.receive() } == null) {
                idle = true
                collector.cancel()
                return@launch
            }
        }
    }

    collector.join()
    watchdog.cancel()
    heartbeats.close()
    when {
        terminal -> StreamWindowOutcome.Terminal
        failure != null -> StreamWindowOutcome.Failed(checkNotNull(failure))
        idle -> StreamWindowOutcome.Idle
        else -> StreamWindowOutcome.Closed
    }
}

/**
 * Attempt budget for one answer stream.
 *
 * A delivered event is proof that the route works, so it clears both the silent
 * probe counter and the consecutive reconnect counter. The cursor itself lives in
 * the durable outbox and is never reset here.
 */
internal class StreamResumePolicy(
    private val backoffMs: LongArray = WearRetryPolicy.BACKOFF_MS,
    private val firstEventProbeDelayMs: Long = WearStreamResume.FIRST_EVENT_PROBE_DELAY_MS,
    private val maxSilentProbes: Int = WearStreamResume.MAX_SILENT_PROBES,
    private val maxConsecutiveReconnects: Int = WearRetryPolicy.MAX_STREAM_RECONNECTS,
    private val maxTotalReconnects: Int = WearStreamResume.MAX_TOTAL_RECONNECTS,
) {
    var silentProbes: Int = 0
        private set
    var consecutiveReconnects: Int = 0
        private set
    var totalReconnects: Int = 0
        private set

    /** Idle budget for the next attempt: generous once the stream has produced data. */
    fun idleBudgetMs(receivedAnyEvent: Boolean): Long = if (receivedAnyEvent) {
        WearStreamResume.STREAM_IDLE_TIMEOUT_MS
    } else {
        WearStreamResume.FIRST_STREAM_EVENT_TIMEOUT_MS
    }

    fun onEventReceived() {
        silentProbes = 0
        consecutiveReconnects = 0
    }

    /** Delay before the next subscribe attempt, or `null` when the budget is spent. */
    fun nextAttemptDelayMs(receivedAnyEvent: Boolean): Long? {
        if (!receivedAnyEvent) {
            if (silentProbes >= maxSilentProbes) return null
            silentProbes += 1
            return firstEventProbeDelayMs
        }
        if (consecutiveReconnects >= maxConsecutiveReconnects) return null
        if (totalReconnects >= maxTotalReconnects) return null
        val delayMs = backoffMs[consecutiveReconnects.coerceAtMost(backoffMs.lastIndex)]
        consecutiveReconnects += 1
        totalReconnects += 1
        return delayMs
    }
}
