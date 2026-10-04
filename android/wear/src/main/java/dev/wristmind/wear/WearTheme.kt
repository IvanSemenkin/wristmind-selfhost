package dev.wristmind.wear

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material3.ColorScheme
import androidx.wear.compose.material3.MaterialTheme

internal val SignalBlue = Color(0xFF69AEFF)
internal val Ink = Color(0xFF070B12)
internal val Panel = Color(0xFF161E2A)
internal val PanelRaised = Color(0xFF1F2A38)
internal val SoftText = Color(0xFFB2BDCA)
internal val Danger = Color(0xFFFFB4AB)

private val WristMindColors = ColorScheme(
    primary = SignalBlue,
    primaryDim = Color(0xFF438DE3),
    primaryContainer = Color(0xFF1B4F86),
    onPrimary = Ink,
    onPrimaryContainer = Color(0xFFF2F7FF),
    secondary = Color(0xFFABC2DD),
    secondaryDim = Color(0xFF8DA5BF),
    secondaryContainer = Color(0xFF1F2A38),
    onSecondary = Ink,
    onSecondaryContainer = Color(0xFFE5EFFA),
    tertiary = Color(0xFFAFC8FF),
    tertiaryContainer = Color(0xFF263957),
    onTertiary = Color(0xFF0A1D38),
    onTertiaryContainer = Color(0xFFE0EBFF),
    surfaceContainerLow = Color(0xFF0F151F),
    surfaceContainer = Panel,
    surfaceContainerHigh = PanelRaised,
    onSurface = Color(0xFFF5F7FA),
    onSurfaceVariant = SoftText,
    outline = Color(0xFF6F7D8F),
    outlineVariant = Color(0xFF2D3948),
    background = Ink,
    onBackground = Color(0xFFF5F7FA),
    error = Danger,
    errorContainer = Color(0xFF5D201D),
    onError = Color(0xFF3A0907),
    onErrorContainer = Color(0xFFFFDAD6),
)

@Composable
internal fun WristMindWearTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = WristMindColors, content = content)
}
