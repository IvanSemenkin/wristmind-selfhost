package dev.wristmind.wear

/** Recognizes an intentional burst of taps without changing the history screen. */
internal class RapidTapTrigger(
    private val requiredTaps: Int = 7,
    private val maxGapMs: Long = 650L,
) {
    private var count = 0
    private var lastTapMs = 0L

    fun onTap(nowMs: Long): Boolean {
        count = if (count > 0 && nowMs - lastTapMs in 0..maxGapMs) count + 1 else 1
        lastTapMs = nowMs
        if (count < requiredTaps) return false
        count = 0
        return true
    }
}
