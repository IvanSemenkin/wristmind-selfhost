package dev.wristmind.phone.install

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics

@Composable
fun WatchSetupScreen(
    state: WatchSetupState, onClose: () -> Unit,
    onStep: (SetupStep) -> Unit, onHost: (String) -> Unit, onPairPort: (String) -> Unit,
    onCode: (String) -> Unit, onConnectPort: (String) -> Unit,
    onPair: () -> Unit, onCheck: () -> Unit, onInstall: () -> Unit, onConfigure: () -> Unit,
) {
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding()
        .verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        TextButton(onClick = onClose, enabled = !state.busy) { Text("← Компаньон") }
        Text("Подключение часов", style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.semantics { heading() })
        Text(when(state.step) {
            SetupStep.INSTRUCTIONS -> "1 · Подготовка"
            SetupStep.PAIR -> "2 · Сопряжение отладки"
            SetupStep.ADDRESS, SetupStep.CHECKED -> "3 · Проверка часов"
            SetupStep.INSTALL -> "4 · Установка приложения"
            SetupStep.CONFIGURE -> "5 · Передача настроек"
            SetupStep.DONE -> "6 · Всё готово"
        }, color = MaterialTheme.colorScheme.onSurfaceVariant)
        when (state.step) {
            SetupStep.INSTRUCTIONS -> {
                Text("Телефон и часы должны быть в одной Wi-Fi сети. Часы также должны быть сопряжены с телефоном в приложении производителя.")
                Text("1. На часах: Настройки → О часах → Версия ПО. Нажмите на номер сборки 7 раз.")
                Text("2. Откройте Для разработчиков → Отладка по ADB и Беспроводная отладка.")
                Text("3. Выберите «Сопряжение с кодом». Адрес, порт и код понадобятся на следующем шаге.")
                OutlinedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Зачем нужна отладка", fontWeight = FontWeight.SemiBold)
                        Text("WristMind использует ADB для проверки часов, установки своего приложения и его запуска. Мастер не удаляет ваши приложения и данные и не меняет системные настройки.")
                        Text("ADB даёт широкий доступ к устройству. Подключайтесь только в доверенной сети и выключите отладку после установки. Код сопряжения не отправляется на сервер; ключ ADB хранится зашифрованным на телефоне.")
                    }
                }
                Action("Продолжить", !state.busy) { onStep(SetupStep.PAIR) }
            }
            SetupStep.PAIR -> {
                Text("Оставьте экран кода сопряжения открытым на часах. Это код часов, а не код с сайта.")
                Field("IP-адрес часов", state.host, onHost, state.busy)
                Field("Порт сопряжения", state.pairPort, onPairPort, state.busy, true)
                Field("Код сопряжения", state.code, onCode, state.busy, true)
                Action("Сопрячь отладку", !state.busy && state.code.length == 6, onPair)
                TextButton(onClick = { onStep(SetupStep.ADDRESS) }, enabled = !state.busy) { Text("Этот телефон уже сопряжён") }
            }
            SetupStep.ADDRESS -> {
                Text("Вернитесь на основной экран «Беспроводная отладка» часов. Введите порт подключения: он отличается от порта сопряжения и может меняться.")
                Field("IP-адрес часов", state.host, onHost, state.busy)
                Field("Порт подключения", state.connectPort, onConnectPort, state.busy, true)
                Action("Проверить связь", !state.busy, onCheck)
                TextButton(onClick = { onStep(SetupStep.PAIR) }, enabled = !state.busy) { Text("Сопрячь заново") }
            }
            SetupStep.CHECKED -> {
                val details = state.details
                Text("${details?.name.orEmpty()} · Android API ${details?.sdk}")
                Text("Совместимость подтверждена. Версия в компаньоне: ${details?.version}.")
                Text(when {
                    details?.installedCode == null -> "WristMind ещё не установлен."
                    details.installedCode == details.bundledCode -> "Эта версия уже установлена. Можно передать настройки или переустановить поверх неё."
                    else -> "Доступно обновление. Настройки и данные приложения сохранятся."
                })
                Text("На часах может появиться запрос подтверждения. Не выключайте Wi-Fi до завершения.")
                Action(if (details?.installedCode == null) "Установить WristMind" else "Установить поверх текущей версии", !state.busy, onInstall)
                if (details != null && details.installedCode == details.bundledCode) TextButton(onClick = { onStep(SetupStep.CONFIGURE) }) { Text("Только передать настройки") }
                TextButton(onClick = { onStep(SetupStep.ADDRESS) }) { Text("Изменить адрес или порт") }
            }
            SetupStep.INSTALL -> {
                Text(if (state.progress < 1f) "Передаю приложение · ${(state.progress * 100).toInt()}%" else "Часы устанавливают приложение…")
                LinearProgressIndicator(progress = { state.progress }, modifier = Modifier.fillMaxWidth())
                if (!state.busy) Action("Повторить установку", true, onInstall)
                if (!state.busy) TextButton(onClick = { onStep(SetupStep.ADDRESS) }) { Text("Проверить адрес и порт") }
            }
            SetupStep.CONFIGURE -> {
                Text("Откройте WristMind на часах. Передадим адрес вашего сервера и ключ устройства по защищённому каналу Wearable Data Layer. Вводить их на часах не нужно.")
                Text("Готовность подтвердим только после ответа часов и проверки их доступа к серверу.")
                Action("Передать настройки", !state.busy, onConfigure)
                Text("Если передача недоступна, на часах можно ввести адрес сервера и новый одноразовый код из панели вручную.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            SetupStep.DONE -> {
                Text("Часы подключены", style = MaterialTheme.typography.titleLarge)
                Text("Версия ${state.details?.version.orEmpty()}. Часы подтвердили настройки и доступ к серверу. Устройство появится в разделе «Устройства» вашей панели.")
                Text("Теперь выключите беспроводную отладку на часах. Для будущего обновления включите её снова: компаньон сохранит адрес, а новый порт можно будет заменить.")
                Action("Готово", true, onClose)
            }
        }
        if (state.busy && state.step != SetupStep.INSTALL) Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            Text("Выполняю шаг…")
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit, busy: Boolean, numeric: Boolean = false) {
    OutlinedTextField(value, onChange, modifier = Modifier.fillMaxWidth(), label = { Text(label) },
        singleLine = true, enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = if(numeric) KeyboardType.Number else KeyboardType.Uri, autoCorrectEnabled = false))
}
@Composable
private fun Action(label: String, enabled: Boolean, onClick: () -> Unit) {
    val keyboard = androidx.compose.ui.platform.LocalSoftwareKeyboardController.current
    Button({ keyboard?.hide(); onClick() }, Modifier.fillMaxWidth().heightIn(min = 48.dp), enabled = enabled) { Text(label) }
}
