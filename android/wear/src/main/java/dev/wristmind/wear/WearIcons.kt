package dev.wristmind.wear

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

object WearIcons {
    val Keyboard by lazy {
        icon("Keyboard") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.7f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(4f, 5.5f); horizontalLineTo(20f)
                curveTo(21.1f, 5.5f, 22f, 6.4f, 22f, 7.5f)
                verticalLineTo(16.5f)
                curveTo(22f, 17.6f, 21.1f, 18.5f, 20f, 18.5f)
                horizontalLineTo(4f)
                curveTo(2.9f, 18.5f, 2f, 17.6f, 2f, 16.5f)
                verticalLineTo(7.5f)
                curveTo(2f, 6.4f, 2.9f, 5.5f, 4f, 5.5f)
                moveTo(5.5f, 9f); horizontalLineTo(6f)
                moveTo(9f, 9f); horizontalLineTo(9.5f)
                moveTo(12.5f, 9f); horizontalLineTo(13f)
                moveTo(16f, 9f); horizontalLineTo(16.5f)
                moveTo(19f, 9f); horizontalLineTo(19.5f)
                moveTo(5.5f, 12.5f); horizontalLineTo(6f)
                moveTo(9f, 12.5f); horizontalLineTo(9.5f)
                moveTo(12.5f, 12.5f); horizontalLineTo(13f)
                moveTo(16f, 12.5f); horizontalLineTo(16.5f)
                moveTo(7f, 15.5f); horizontalLineTo(17f)
            }
        }
    }

    val Close by lazy {
        icon("Close") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(5.4f, 4f); lineTo(12f, 10.6f); lineTo(18.6f, 4f); lineTo(20f, 5.4f)
                lineTo(13.4f, 12f); lineTo(20f, 18.6f); lineTo(18.6f, 20f); lineTo(12f, 13.4f)
                lineTo(5.4f, 20f); lineTo(4f, 18.6f); lineTo(10.6f, 12f); lineTo(4f, 5.4f); close()
            }
        }
    }

    val Menu by lazy {
        icon("Menu") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(5f, 6f); horizontalLineTo(19f); verticalLineTo(8f); horizontalLineTo(5f); close()
                moveTo(5f, 11f); horizontalLineTo(19f); verticalLineTo(13f); horizontalLineTo(5f); close()
                moveTo(5f, 16f); horizontalLineTo(19f); verticalLineTo(18f); horizontalLineTo(5f); close()
            }
        }
    }

    val History by lazy {
        icon("History") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.8f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(12f, 4f)
                arcTo(8f, 8f, 0f, true, true, 4f, 12f)
                arcTo(8f, 8f, 0f, true, true, 12f, 20f)
                arcTo(8f, 8f, 0f, true, true, 20f, 12f)
                arcTo(8f, 8f, 0f, true, true, 12f, 4f)
                moveTo(4f, 12f); lineTo(4f, 7.5f); lineTo(8.5f, 7.5f)
                moveTo(12f, 7.5f); verticalLineTo(12f); lineTo(15.5f, 14f)
            }
        }
    }

    val Add by lazy {
        icon("Add") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(11f, 4f); horizontalLineTo(13f); verticalLineTo(11f); horizontalLineTo(20f)
                verticalLineTo(13f); horizontalLineTo(13f); verticalLineTo(20f); horizontalLineTo(11f)
                verticalLineTo(13f); horizontalLineTo(4f); verticalLineTo(11f); horizontalLineTo(11f); close()
            }
        }
    }

    val Check by lazy {
        icon("Check") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 2.2f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(5f, 12.5f); lineTo(10f, 17.5f); lineTo(19.5f, 7f)
            }
        }
    }

    val Delete by lazy {
        icon("Delete") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.8f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(5f, 7f); horizontalLineTo(19f)
                moveTo(9f, 7f); verticalLineTo(4.5f)
                curveTo(9f, 3.7f, 9.7f, 3f, 10.5f, 3f)
                horizontalLineTo(13.5f)
                curveTo(14.3f, 3f, 15f, 3.7f, 15f, 4.5f)
                verticalLineTo(7f)
                moveTo(7f, 7f); lineTo(8f, 20f)
                horizontalLineTo(16f); lineTo(17f, 7f)
                moveTo(10f, 10f); verticalLineTo(17f)
                moveTo(14f, 10f); verticalLineTo(17f)
            }
        }
    }

    val Mic by lazy {
        icon("Microphone") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(9f, 5f); curveTo(9f, 2.8f, 10.4f, 2f, 12f, 2f)
                curveTo(13.6f, 2f, 15f, 2.8f, 15f, 5f); verticalLineTo(11f)
                curveTo(15f, 13.2f, 13.6f, 14f, 12f, 14f)
                curveTo(10.4f, 14f, 9f, 13.2f, 9f, 11f); close()
                moveTo(6f, 10f); horizontalLineTo(8f); verticalLineTo(11f)
                curveTo(8f, 13.8f, 9.7f, 16f, 12f, 16f)
                curveTo(14.3f, 16f, 16f, 13.8f, 16f, 11f); verticalLineTo(10f); horizontalLineTo(18f)
                verticalLineTo(11f); curveTo(18f, 14.5f, 15.9f, 17.4f, 13f, 17.9f)
                verticalLineTo(20f); horizontalLineTo(17f); verticalLineTo(22f); horizontalLineTo(7f)
                verticalLineTo(20f); horizontalLineTo(11f); verticalLineTo(17.9f)
                curveTo(8.1f, 17.4f, 6f, 14.5f, 6f, 11f); close()
            }
        }
    }

    val Search by lazy {
        icon("Search") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.9f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(10.5f, 4.5f)
                arcTo(6f, 6f, 0f, true, true, 10.5f, 16.5f)
                arcTo(6f, 6f, 0f, true, true, 10.5f, 4.5f)
                moveTo(15f, 15f); lineTo(20f, 20f)
            }
        }
    }

    val Research by lazy {
        icon("Research") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.9f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(9.5f, 4.5f)
                arcTo(5.5f, 5.5f, 0f, true, true, 9.5f, 15.5f)
                arcTo(5.5f, 5.5f, 0f, true, true, 9.5f, 4.5f)
                moveTo(13.5f, 13.5f); lineTo(20f, 20f)
                moveTo(16f, 6f); lineTo(17.2f, 8.2f); lineTo(20f, 4.5f)
            }
        }
    }

    val Send by lazy {
        icon("Send") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(3f, 3f); lineTo(22f, 12f); lineTo(3f, 21f); lineTo(6f, 13.5f)
                lineTo(14f, 12f); lineTo(6f, 10.5f); close()
            }
        }
    }

    val Cloud by lazy {
        icon("VPS") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(7f, 19f); curveTo(4.2f, 19f, 2f, 16.8f, 2f, 14f)
                curveTo(2f, 11.6f, 3.7f, 9.5f, 6f, 9f)
                curveTo(6.8f, 5.6f, 9.7f, 3f, 13.3f, 3f)
                curveTo(17.5f, 3f, 21f, 6.5f, 21f, 10.8f)
                curveTo(22.8f, 11.8f, 23.5f, 14.1f, 22.6f, 16f)
                curveTo(21.8f, 17.8f, 20.2f, 19f, 18f, 19f); close()
            }
        }
    }

    val Stop by lazy {
        icon("Stop") {
            path(fill = SolidColor(Color.Black)) {
                moveTo(6f, 6f); horizontalLineTo(18f); verticalLineTo(18f); horizontalLineTo(6f); close()
            }
        }
    }

    val Chat by lazy {
        icon("Chat") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.8f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(5f, 4f); horizontalLineTo(19f)
                curveTo(20.1f, 4f, 21f, 4.9f, 21f, 6f)
                verticalLineTo(15f); curveTo(21f, 16.1f, 20.1f, 17f, 19f, 17f)
                horizontalLineTo(10f); lineTo(6f, 20f); verticalLineTo(17f); horizontalLineTo(5f)
                curveTo(3.9f, 17f, 3f, 16.1f, 3f, 15f); verticalLineTo(6f)
                curveTo(3f, 4.9f, 3.9f, 4f, 5f, 4f)
            }
        }
    }

    val QuickChat by lazy {
        icon("QuickChat") {
            path(
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.8f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            ) {
                moveTo(5f, 4f); horizontalLineTo(19f)
                curveTo(20.1f, 4f, 21f, 4.9f, 21f, 6f)
                verticalLineTo(15f); curveTo(21f, 16.1f, 20.1f, 17f, 19f, 17f)
                horizontalLineTo(10f); lineTo(6f, 20f); verticalLineTo(17f); horizontalLineTo(5f)
                curveTo(3.9f, 17f, 3f, 16.1f, 3f, 15f); verticalLineTo(6f)
                curveTo(3f, 4.9f, 3.9f, 4f, 5f, 4f)
                // Center the lightning inside the bubble body instead of the tail-inclusive shape.
                moveTo(12.8f, 6.4f); lineTo(9.8f, 11f); horizontalLineTo(12.5f)
                lineTo(11.2f, 14.6f); lineTo(14.2f, 10f); horizontalLineTo(11.5f); close()
            }
        }
    }

    private fun icon(name: String, content: ImageVector.Builder.() -> Unit): ImageVector =
        ImageVector.Builder(
            name = name,
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 24f,
            viewportHeight = 24f,
        ).apply(content).build()
}
