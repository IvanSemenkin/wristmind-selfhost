package dev.wristmind.wear

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import java.time.Instant
import kotlinx.coroutines.delay

@Composable
internal fun WearServiceMenuScreen(onPairingCode: () -> Unit, onDiagnosticExport: () -> Unit) {
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    ScreenScaffold(scrollState = listState, scrollIndicator = wearScrollIndicator(listState)) { padding ->
        TransformingLazyColumn(state = listState, contentPadding = padding) {
            item {
                ListHeader(
                    modifier = Modifier.fillMaxWidth()
                        .minimumVerticalContentPadding(
                            ListHeaderDefaults.minimumTopListContentPadding,
                            ListHeaderDefaults.minimumBottomListContentPadding,
                        )
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                ) {
                    Text("Устройство")
                }
            }
            item {
                Button(
                    onClick = onPairingCode,
                    label = { Text("Код подключения") },
                    modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                    colors = ButtonDefaults.filledTonalButtonColors(),
                )
            }
            item {
                Button(
                    onClick = onDiagnosticExport,
                    label = { Text("Отправить логи") },
                    modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                    colors = ButtonDefaults.filledTonalButtonColors(),
                )
            }
        }
    }
}

@Composable
internal fun WearDevicePairingCodeScreen(state: WearState, onNewCode: () -> Unit) {
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    val code = state.generatedPairingCode
    val expiry = remember(code) { code?.let { runCatching { Instant.parse(it.expiresAt).toEpochMilli() }.getOrNull() } }
    var now by remember(code) { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(code) {
        while (expiry != null && now < expiry) {
            delay(1_000L)
            now = System.currentTimeMillis()
        }
    }
    val remainingSeconds = ((expiry ?: now) - now).coerceAtLeast(0L) / 1_000L
    ScreenScaffold(scrollState = listState, scrollIndicator = wearScrollIndicator(listState)) { padding ->
        TransformingLazyColumn(state = listState, contentPadding = padding) {
            item {
                ListHeader(
                    modifier = Modifier.fillMaxWidth()
                        .minimumVerticalContentPadding(
                            ListHeaderDefaults.minimumTopListContentPadding,
                            ListHeaderDefaults.minimumBottomListContentPadding,
                        )
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                ) {
                    Text("Подключение")
                }
            }
            if (state.pairingCodeLoading) {
                item {
                    CircularProgressIndicator(modifier = Modifier.size(28.dp).transformedHeight(this, transformationSpec))
                }
                item {
                    Text("Получаем код…", textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                }
            } else if (code != null && remainingSeconds > 0L) {
                item {
                    Text(
                        code.code,
                        style = MaterialTheme.typography.displayMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                item {
                    Text(
                        "Одноразовый код\nОсталось ${remainingSeconds / 60}:${(remainingSeconds % 60).toString().padStart(2, '0')}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                item {
                    Text(
                        "Введите на новом устройстве",
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            } else {
                item {
                    Text(
                        state.pairingCodeError ?: "Срок кода истёк",
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                item {
                    Button(
                        onClick = onNewCode,
                        label = { Text("Получить код") },
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec),
                        colors = ButtonDefaults.filledTonalButtonColors(),
                    )
                }
            }
        }
    }
}
