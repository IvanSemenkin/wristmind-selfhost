package dev.wristmind.wear

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import kotlin.math.abs

/** Claim only deliberate leftward drags; leave vertical scroll and swipe-back alone. */
internal fun Modifier.chatHistorySwipe(onHistory: () -> Unit): Modifier = pointerInput(Unit) {
    val minimumDistance = maxOf(36.dp.toPx(), size.width * .18f)
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false)
        val origin = down.position
        var claimed = false
        while (true) {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            if (event.changes.count { it.pressed } > 1) break
            val change = event.changes.firstOrNull { it.id == down.id } ?: break
            val dx = change.position.x - origin.x
            val dy = change.position.y - origin.y
            if (change.isConsumed) break
            if (!claimed) {
                // Allow natural diagonals; reject only clearly vertical or rightward movement.
                if (dx > viewConfiguration.touchSlop) break
                if (abs(dy) > viewConfiguration.touchSlop && abs(dy) > abs(dx) * 1.3f) break
                if (-dx > viewConfiguration.touchSlop && -dx >= abs(dy)) claimed = true
            }
            if (claimed) change.consume()
            if (!change.pressed) {
                if (claimed && -dx >= minimumDistance) onHistory()
                break
            }
        }
    }
}
