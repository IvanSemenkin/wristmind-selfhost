package dev.wristmind.app

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.Shader
import android.util.AttributeSet
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.sin

class AssistantOrbView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }
    private var phase = 0f
    private var mode = "OFFLINE"

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null)
    }

    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 1800
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
            phase = it.animatedValue as Float
            invalidate()
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (!animator.isStarted) animator.start()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    fun setMode(value: String) {
        mode = value
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cx = width / 2f
        val cy = height / 2f
        val radius = minOf(width, height) * 0.31f
        val accent = when (mode) {
            "REC" -> Color.rgb(255, 100, 118)
            "READY" -> Color.rgb(107, 232, 184)
            "ERROR" -> Color.rgb(255, 174, 85)
            "SEND", "PROC", "STOP" -> Color.rgb(137, 169, 255)
            "IDLE" -> Color.rgb(156, 130, 255)
            else -> Color.rgb(101, 111, 142)
        }
        val pulse = (sin(phase * Math.PI * 2).toFloat() + 1f) / 2f

        paint.shader = RadialGradient(
            cx,
            cy,
            radius * (1.45f + pulse * 0.08f),
            intArrayOf(
                withAlpha(accent, 90),
                withAlpha(accent, 28),
                Color.TRANSPARENT,
            ),
            floatArrayOf(0f, 0.58f, 1f),
            Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, radius * 1.65f, paint)
        paint.shader = null

        paint.color = Color.rgb(29, 33, 52)
        paint.setShadowLayer(radius * 0.18f, 0f, radius * 0.08f, withAlpha(accent, 115))
        canvas.drawCircle(cx, cy, radius, paint)
        paint.clearShadowLayer()

        stroke.color = withAlpha(accent, 120)
        stroke.strokeWidth = radius * 0.035f
        canvas.drawCircle(cx, cy, radius * (1.12f + pulse * 0.04f), stroke)

        when (mode) {
            "REC" -> drawWave(canvas, cx, cy, radius, accent)
            "SEND", "PROC", "STOP" -> drawProcessing(canvas, cx, cy, radius, accent)
            "READY" -> drawCheck(canvas, cx, cy, radius, accent)
            "ERROR" -> drawError(canvas, cx, cy, radius, accent)
            else -> drawMicrophone(canvas, cx, cy, radius, accent)
        }
    }

    private fun drawMicrophone(canvas: Canvas, cx: Float, cy: Float, r: Float, color: Int) {
        stroke.color = color
        stroke.strokeWidth = r * 0.12f
        canvas.drawRoundRect(
            cx - r * 0.22f,
            cy - r * 0.38f,
            cx + r * 0.22f,
            cy + r * 0.18f,
            r * 0.22f,
            r * 0.22f,
            stroke,
        )
        val path = Path().apply {
            moveTo(cx - r * 0.43f, cy)
            cubicTo(cx - r * 0.43f, cy + r * 0.38f, cx + r * 0.43f, cy + r * 0.38f, cx + r * 0.43f, cy)
            moveTo(cx, cy + r * 0.31f)
            lineTo(cx, cy + r * 0.54f)
            moveTo(cx - r * 0.24f, cy + r * 0.54f)
            lineTo(cx + r * 0.24f, cy + r * 0.54f)
        }
        canvas.drawPath(path, stroke)
    }

    private fun drawWave(canvas: Canvas, cx: Float, cy: Float, r: Float, color: Int) {
        stroke.color = color
        stroke.strokeWidth = r * 0.1f
        val heights = floatArrayOf(0.28f, 0.56f, 0.88f, 0.56f, 0.28f)
        heights.forEachIndexed { index, base ->
            val animated = base * (0.72f + 0.28f * sin(phase * 6.28f + index).toFloat())
            val x = cx + (index - 2) * r * 0.22f
            canvas.drawLine(x, cy - r * animated / 2f, x, cy + r * animated / 2f, stroke)
        }
    }

    private fun drawProcessing(canvas: Canvas, cx: Float, cy: Float, r: Float, color: Int) {
        paint.color = color
        repeat(3) { index ->
            val local = (phase + index / 3f) % 1f
            val dotRadius = r * (0.09f + 0.055f * (1f - local))
            canvas.drawCircle(cx + (index - 1) * r * 0.36f, cy, dotRadius, paint)
        }
    }

    private fun drawCheck(canvas: Canvas, cx: Float, cy: Float, r: Float, color: Int) {
        stroke.color = color
        stroke.strokeWidth = r * 0.13f
        val path = Path().apply {
            moveTo(cx - r * 0.45f, cy)
            lineTo(cx - r * 0.1f, cy + r * 0.34f)
            lineTo(cx + r * 0.5f, cy - r * 0.34f)
        }
        canvas.drawPath(path, stroke)
    }

    private fun drawError(canvas: Canvas, cx: Float, cy: Float, r: Float, color: Int) {
        stroke.color = color
        stroke.strokeWidth = r * 0.13f
        canvas.drawLine(cx, cy - r * 0.42f, cx, cy + r * 0.12f, stroke)
        paint.color = color
        canvas.drawCircle(cx, cy + r * 0.43f, r * 0.08f, paint)
    }

    private fun withAlpha(color: Int, alpha: Int): Int =
        Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color))
}
