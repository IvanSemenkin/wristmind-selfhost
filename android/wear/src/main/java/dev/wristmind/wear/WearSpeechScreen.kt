package dev.wristmind.wear

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.material3.*
import org.json.JSONObject
import kotlin.math.sqrt

@Composable
internal fun WearSpeechScreen(
    request: suspend (JSONObject) -> JSONObject,
    onText: (String) -> Unit,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    val recorder = remember { WearSpeechRecorder(request) }
    val state by recorder.state.collectAsStateWithLifecycle()
    val currentOnClose by rememberUpdatedState(onClose)
    val currentOnText by rememberUpdatedState(onText)
    var denied by remember { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (it) recorder.start() else denied = true
    }
    LaunchedEffect(recorder) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) recorder.start()
        else permission.launch(Manifest.permission.RECORD_AUDIO)
    }
    LaunchedEffect(state.phase) {
        if (state.phase == "done" || state.phase == "cancelled") {
            if (state.text.isNotBlank()) currentOnText(state.text)
            currentOnClose()
        }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(recorder, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) {
                recorder.cancel()
            }
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); recorder.cancel() }
    }
    val accent = MaterialTheme.colorScheme.primary
    ScreenScaffold { scaffoldPadding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(scaffoldPadding).padding(horizontal = 28.dp, vertical = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = when {
                    denied -> "Разрешите микрофон"
                    state.phase == "error" -> "Не удалось записать"
                    state.phase == "recognizing" -> "Распознаём…"
                    state.phase == "ready" -> "Микрофон…"
                    else -> "Говорите"
                },
                textAlign = TextAlign.Center,
                fontSize = 16.sp,
            )
            Spacer(Modifier.height(12.dp))
            if (state.phase == "recording") {
                Canvas(Modifier.fillMaxWidth().height(36.dp)) {
                    state.levels.asReversed().forEachIndexed { index, level ->
                        val x = size.width - 3.dp.toPx() - index * 5.dp.toPx()
                        if (x >= 0) {
                            val half = (1 + sqrt(level) * 15).dp.toPx()
                            drawLine(accent, Offset(x, size.height / 2 - half), Offset(x, size.height / 2 + half),
                                strokeWidth = 3.dp.toPx(), cap = StrokeCap.Round)
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text("0:${state.seconds.toString().padStart(2, '0')} / 0:30", fontSize = 12.sp)
            } else if (state.phase == "recognizing") {
                CircularProgressIndicator(Modifier.size(28.dp))
            } else if (state.phase == "error") {
                Text("Проверьте соединение и попробуйте снова", textAlign = TextAlign.Center, fontSize = 12.sp)
            }
            Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                FilledTonalIconButton(onClick = { recorder.cancel(); currentOnClose() }, modifier = Modifier.requiredSize(48.dp), shapes = IconButtonDefaults.shapes(CircleShape)) {
                    Icon(WearIcons.Close, contentDescription = "Отменить запись")
                }
                if (state.phase == "recording") {
                    FilledTonalIconButton(
                        onClick = recorder::finish,
                        modifier = Modifier.requiredSize(48.dp),
                        shapes = IconButtonDefaults.shapes(CircleShape),
                        colors = IconButtonDefaults.filledTonalIconButtonColors(
                            containerColor = accent,
                            contentColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    ) {
                        Icon(WearIcons.Check, contentDescription = "Распознать запись")
                    }
                }
            }
        }
    }
}
