package dev.wristmind.phone

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel

private val Mint = Color(0xFF65F5C2)
private val Ink = Color(0xFF07110F)
private val Panel = Color(0xFF10231E)
private val DangerContainer = Color(0xFF4C171A)
private val OnDangerContainer = Color(0xFFFFDAD8)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { CompanionApp() }
    }
}

@Composable
private fun CompanionApp(vm: PhoneViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Mint,
            onPrimary = Ink,
            background = Ink,
            surface = Panel,
            onSurface = Color(0xFFE6FFF5),
        ),
    ) {
        Surface(Modifier.fillMaxSize()) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Brush.verticalGradient(listOf(Color(0xFF0B1A17), Ink, Color(0xFF050A09)))),
            ) {
                if (state.enrolled) CompanionHome(state, vm) else PairScreen(state, vm)
            }
        }
    }
}

@Composable
private fun PairScreen(state: PhoneState, vm: PhoneViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(32.dp))
        Text("WRISTMIND", color = Mint, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        Text("Подключение часов", fontSize = 30.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
        Text(
            "Откройте на сайте Настройки → Подключить устройство и введите одноразовый код ниже.",
            color = Color(0xFFA9C8BD),
            textAlign = TextAlign.Center,
        )
        OutlinedTextField(
            value = state.pairingCode,
            onValueChange = vm::setPairingCode,
            label = { Text("Код с сайта") },
            placeholder = { Text("000000") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            supportingText = { Text("${state.pairingCode.length}/6") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { if (state.pairingCode.length == 6) vm.pair() }),
        )
        PrimaryButton("Подключить часы", !state.busy && state.pairingCode.length == 6, vm::pair)
        StatusLine(state)
    }
}

@Composable
private fun CompanionHome(state: PhoneState, vm: PhoneViewModel) {
    var dialog by remember { mutableStateOf<DialogAction?>(null) }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(20.dp))
        Text("WRISTMIND", color = Mint, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        Text("Companion", fontSize = 32.sp, fontWeight = FontWeight.SemiBold)
        StatusCard(state)
        ConnectionCard(state)
        SecondaryButton("Проверить соединение", !state.busy, vm::refresh)
        PrimaryButton(
            if (state.paused) "Возобновить приложение" else "Приостановить приложение",
            !state.busy,
            { vm.setPaused(!state.paused) },
        )
        Text(
            if (state.paused) "Прокси и фоновая синхронизация остановлены. Авторизация и сопряжение сохранены."
            else "Прокси через Wearable Data Layer работает автоматически в фоне.",
            color = Color(0xFFA9C8BD),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
        DestructiveButton("Отключить часы", !state.busy) { dialog = DialogAction.FORGET }
        DestructiveButton("Удалить данные с телефона", !state.busy) { dialog = DialogAction.LOGOUT }
    }
    dialog?.let { action ->
        AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text(if (action == DialogAction.FORGET) "Отключить часы?" else "Удалить данные с телефона?") },
            text = {
                Text(
                    if (action == DialogAction.FORGET) {
                        "Приложение на часах потеряет доступ к WristMind. Сопряжение в Mi Fitness не изменится."
                    } else {
                        "Локальная авторизация и настройки companion будут удалены. Сопряжение в Mi Fitness не изменится."
                    },
                )
            },
            confirmButton = {
                Button(
                    onClick = { dialog = null; if (action == DialogAction.FORGET) vm.forgetWatch() else vm.logout() },
                    colors = ButtonDefaults.buttonColors(containerColor = DangerContainer, contentColor = OnDangerContainer),
                ) {
                    Text(if (action == DialogAction.FORGET) "Отключить" else "Удалить")
                }
            },
            dismissButton = { Button(onClick = { dialog = null }) { Text("Отмена") } },
        )
    }
}

@Composable
private fun ConnectionCard(state: PhoneState) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Xiaomi Watch 2", fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text(
                "Прокси через Wearable Data Layer. Канал Bluetooth или Wi‑Fi выбирает система.",
                color = Color(0xFFA9C8BD),
            )
            ConnectionRow("Доступ к WristMind", state.serverReachable, "доступен", "нет доступа")
            ConnectionRow("Часы", if (state.busy) null else state.watchReachable, "обнаружены", "не обнаружены")
        }
    }
}

@Composable
private fun ConnectionRow(label: String, connected: Boolean?, connectedText: String, disconnectedText: String) {
    val (value, color) = when (connected) {
        true -> connectedText to Mint
        false -> disconnectedText to Color(0xFFFFC27D)
        null -> "проверяется" to Color(0xFFA9C8BD)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = Color(0xFFA9C8BD))
        Text(value, color = color, fontWeight = FontWeight.Medium)
    }
}

private enum class DialogAction { FORGET, LOGOUT }

@Composable
private fun StatusCard(state: PhoneState) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(20.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (state.busy) CircularProgressIndicator(Modifier.height(22.dp), strokeWidth = 2.dp)
            else Box(Modifier.height(10.dp).fillMaxWidth(.03f).background(statusColor(state.status), RoundedCornerShape(10.dp)))
            Column(Modifier.weight(1f)) {
                Text(statusTitle(state.status), fontWeight = FontWeight.Bold)
                Text(state.statusText, color = Color(0xFFA9C8BD), fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun StatusLine(state: PhoneState) {
    Text(
        state.statusText,
        color = if (state.status == CompanionStatus.ERROR) Color(0xFFFF9B93) else Color(0xFFA9C8BD),
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth(),
    )
}

private fun statusTitle(status: CompanionStatus) = when (status) {
    CompanionStatus.SIGN_IN -> "Нужен код"
    CompanionStatus.READY -> "Готово"
    CompanionStatus.SYNCING -> "Синхронизация"
    CompanionStatus.PAUSED -> "Приостановлено"
    CompanionStatus.OFFLINE -> "Нет связи"
    CompanionStatus.ERROR -> "Ошибка"
}

private fun statusColor(status: CompanionStatus) = when (status) {
    CompanionStatus.READY -> Mint
    CompanionStatus.PAUSED -> Color(0xFFFFC27D)
    CompanionStatus.ERROR, CompanionStatus.OFFLINE -> Color(0xFFFF9B93)
    else -> Mint
}

@Composable
private fun PrimaryButton(text: String, enabled: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().height(54.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Mint, contentColor = Ink),
        shape = RoundedCornerShape(18.dp),
    ) { Text(text, fontWeight = FontWeight.Bold) }
}

@Composable
private fun SecondaryButton(text: String, enabled: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().height(50.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Panel, contentColor = Color.White),
        shape = RoundedCornerShape(18.dp),
    ) { Text(text) }
}

@Composable
private fun DestructiveButton(text: String, enabled: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().height(50.dp),
        colors = ButtonDefaults.buttonColors(containerColor = DangerContainer, contentColor = OnDangerContainer),
        shape = RoundedCornerShape(18.dp),
    ) { Text(text) }
}
