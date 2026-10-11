package dev.wristmind.phone

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.wristmind.core.DeviceConfig
import dev.wristmind.core.DeviceConfigStore
import dev.wristmind.core.WristMindApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class CompanionStatus { SIGN_IN, READY, SYNCING, PAUSED, OFFLINE, ERROR }

data class PhoneState(
    val serverUrl: String = BuildConfig.WRISTMIND_BASE_URL,
    val pairingCode: String = "",
    val enrolled: Boolean = false,
    val paused: Boolean = false,
    val serverReachable: Boolean? = null,
    val watchReachable: Boolean = false,
    val watchName: String = "Часы Wear OS",
    val status: CompanionStatus = CompanionStatus.SIGN_IN,
    val statusText: String = "Введите код с сайта WristMind",
    val busy: Boolean = false,
)

class PhoneViewModel(application: Application) : AndroidViewModel(application) {
    private val store = DeviceConfigStore(application, "phone")
    private val prefs = application.getSharedPreferences("wristmind_companion", 0)
    private val saved = store.read(BuildConfig.WRISTMIND_BASE_URL)
    private var token = saved.token
    private val watchLink = WatchLink(application)
    private val mutableState = MutableStateFlow(
        PhoneState(
            serverUrl = saved.serverUrl,
            enrolled = token.isNotBlank(),
            paused = prefs.getBoolean(KEY_PAUSED, false),
            status = if (token.isBlank()) CompanionStatus.SIGN_IN else CompanionStatus.SYNCING,
            statusText = if (token.isBlank()) "Введите код с сайта WristMind" else "Проверяю подключение…",
        ),
    )
    val state: StateFlow<PhoneState> = mutableState

    init {
        viewModelScope.launch {
            PhoneConfigEvents.tokenReceived.collect { config ->
                if (token != config.token || mutableState.value.serverUrl != config.serverUrl) {
                    token = config.token
                    mutableState.update {
                        it.copy(
                            serverUrl = config.serverUrl,
                            enrolled = true,
                            paused = false,
                            pairingCode = "",
                            status = CompanionStatus.SYNCING,
                            statusText = "Код принят на часах. Синхронизация…",
                        )
                    }
                    runCatching { refreshInternal() }
                }
            }
        }
        if (token.isNotBlank() && !mutableState.value.paused) refresh()
    }

    fun setServerUrl(value: String) = mutableState.update { it.copy(serverUrl = value) }

    fun setPairingCode(value: String) = mutableState.update {
        it.copy(pairingCode = value.filter(Char::isDigit).take(6))
    }

    fun pair() {
        val code = mutableState.value.pairingCode.trim()
        if (code.length != 6) {
            mutableState.update { it.copy(status = CompanionStatus.ERROR, statusText = "Введите код из 6 цифр") }
            return
        }
        launchAction {
            val current = mutableState.value
            val url = dev.wristmind.phone.install.InstallValidation.server(current.serverUrl)
            val result = WristMindApi(url).enrollWatch("Часы WristMind", code)
            token = result.token
            store.save(DeviceConfig(url, token))
            prefs.edit().putBoolean(KEY_PAUSED, false).apply()
            mutableState.update {
                it.copy(enrolled = true, paused = false, pairingCode = "", statusText = "Сервер подключён. Теперь установите приложение на часы")
            }
            // Configuration is sent to the selected watch only after installation.
            refreshInternal()
        }
    }

    fun setPaused(value: Boolean) {
        if (!mutableState.value.enrolled) return
        prefs.edit().putBoolean(KEY_PAUSED, value).apply()
        mutableState.update {
            it.copy(
                paused = value,
                status = if (value) CompanionStatus.PAUSED else CompanionStatus.SYNCING,
                statusText = if (value) "Приложение приостановлено" else "Возобновляю синхронизацию…",
            )
        }
        viewModelScope.launch {
            runCatching { watchLink.publishConfig(state.value.serverUrl, token, value) }
            if (!value) runCatching { refreshInternal() }
        }
    }

    fun forgetWatch() {
        if (token.isBlank()) return
        launchAction {
            WristMindApi(mutableState.value.serverUrl, token).revokeSelf()
            clearLocal("Часы удалены из WristMind")
        }
    }

    fun logout() {
        clearLocal("Вы вышли из WristMind")
    }

    fun refresh() {
        if (token.isBlank()) return
        launchAction { refreshInternal() }
    }

    private suspend fun refreshInternal() {
        val current = mutableState.value
        val serverReachable = runCatching {
            WristMindApi(current.serverUrl, token).health()
        }.getOrDefault(false)
        val link = runCatching { watchLink.inspect() }.getOrNull()
        val watchReachable = link?.reachable == true
        mutableState.update {
            it.copy(
                enrolled = true,
                serverReachable = serverReachable,
                watchReachable = watchReachable,
                watchName = link?.nodeName ?: it.watchName,
                status = if (serverReachable && watchReachable) CompanionStatus.READY else CompanionStatus.OFFLINE,
                statusText = when {
                    !serverReachable -> "Нет доступа к WristMind. Проверьте интернет телефона."
                    watchReachable -> "Часы готовы · ${link?.nodeName ?: it.watchName}"
                    else -> "Часы не обнаружены. Проверьте Bluetooth и Mi Fitness."
                },
                busy = false,
            )
        }
    }

    private fun launchAction(block: suspend () -> Unit) {
        if (mutableState.value.busy) return
        viewModelScope.launch {
            mutableState.update { it.copy(busy = true, status = CompanionStatus.SYNCING, statusText = "Синхронизация…") }
            runCatching { block() }.onFailure { error ->
                mutableState.update {
                    it.copy(
                        busy = false,
                        serverReachable = false,
                        status = CompanionStatus.ERROR,
                        statusText = error.message ?: "Ошибка подключения",
                    )
                }
            }
        }
    }

    private fun clearLocal(message: String) {
        token = ""
        store.clearToken()
        prefs.edit().clear().apply()
        mutableState.update { PhoneState(serverUrl = it.serverUrl, statusText = message) }
    }

    private companion object { const val KEY_PAUSED = WearProxyService.KEY_PAUSED }
}
