package dev.wristmind.phone.install

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.wristmind.core.DeviceConfigStore
import dev.wristmind.phone.WatchLink
import dev.wristmind.phone.configure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

// Credentials remain in DeviceConfigStore, never in screen state or saved-state bundles.
enum class SetupStep { INSTRUCTIONS, PAIR, ADDRESS, CHECKED, INSTALL, CONFIGURE, DONE }
data class WatchSetupState(
    val step: SetupStep = SetupStep.INSTRUCTIONS,
    val host: String = "", val pairPort: String = "", val code: String = "", val connectPort: String = "",
    val busy: Boolean = false, val error: String? = null, val progress: Float = 0f,
    val details: WatchDetails? = null,
)

class WatchSetupViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("wristmind_watch_install", 0)
    private val installer = WatchInstaller(application)
    private val mutable = MutableStateFlow(WatchSetupState(host = prefs.getString("host", "").orEmpty(),
        connectPort = prefs.getString("port", "").orEmpty()))
    val state = mutable.asStateFlow()

    fun begin() { if (!state.value.busy) mutable.update { it.copy(step = SetupStep.INSTRUCTIONS, error = null) } }
    fun next(step: SetupStep) { if (!state.value.busy) mutable.update { it.copy(step = step, error = null) } }
    fun host(value: String) { if (!state.value.busy) mutable.update { it.copy(host = value.take(64), details = null) } }
    fun pairPort(value: String) { if (!state.value.busy) mutable.update { it.copy(pairPort = value.filter(Char::isDigit).take(5)) } }
    fun code(value: String) { if (!state.value.busy) mutable.update { it.copy(code = value.filter(Char::isDigit).take(6)) } }
    fun connectPort(value: String) { if (!state.value.busy) mutable.update { it.copy(connectPort = value.filter(Char::isDigit).take(5), details = null) } }
    fun pair() = action {
        val current = state.value
        installer.pair(InstallValidation.host(current.host), InstallValidation.port(current.pairPort), current.code)
        mutable.update { it.copy(step = SetupStep.ADDRESS, code = "") }
    }
    fun check() = action {
        val current = state.value
        val details = installer.check(InstallValidation.host(current.host), InstallValidation.port(current.connectPort))
        mutable.update { it.copy(step = SetupStep.CHECKED, details = details) }
    }
    fun install() = action(timeout = 180000) {
        // Recheck the actual target even after rotation or a changed debug port.
        val current = state.value
        installer.check(InstallValidation.host(current.host), InstallValidation.port(current.connectPort))
        mutable.update { it.copy(step = SetupStep.INSTALL, progress = 0f) }
        installer.install { progress -> mutable.update { it.copy(progress = progress) } }
        installer.close()
        mutable.update { it.copy(step = SetupStep.CONFIGURE) }
    }
    fun configure() = action {
        val config = DeviceConfigStore(getApplication(), "phone").read("")
        require(config.token.isNotBlank()) { "Сначала подключите компаньон к серверу с кодом из панели" }
        installer.check(InstallValidation.host(state.value.host), InstallValidation.port(state.value.connectPort))
        val nonce = java.util.UUID.randomUUID().toString()
        installer.activate(nonce)
        installer.close()
        WatchLink(getApplication()).configure(getApplication(), InstallValidation.server(config.serverUrl), config.token, nonce)
        prefs.edit().putString("host", state.value.host).putString("port", state.value.connectPort)
            .putString("version", state.value.details?.version).apply()
        mutable.update { it.copy(step = SetupStep.DONE) }
    }
    private fun action(timeout: Long = 55000, block: suspend () -> Unit) {
        if (state.value.busy) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try { withTimeout(timeout) { block() } }
            catch (error: kotlinx.coroutines.TimeoutCancellationException) {
                mutable.update { it.copy(error = "Время ожидания истекло. Проверьте часы и повторите текущий шаг.") }
            }
            catch (error: CancellationException) { throw error }
            catch (error: Exception) {
                if (dev.wristmind.phone.BuildConfig.DEBUG) {
                    // Log locations only; exception messages may contain private inputs.
                    generateSequence<Throwable>(error) { it.cause }.take(4).forEach {
                        android.util.Log.w("WatchSetup", "${it.javaClass.name}: ${it.stackTrace.take(4).joinToString()}")
                    }
                }
                mutable.update { it.copy(error = if (error is java.io.IOException) "Соединение с часами прервалось. Проверьте Wi-Fi и текущий порт, затем повторите шаг." else error.message ?: "Не удалось выполнить шаг. Проверьте подключение и повторите.") }
            }
            finally { installer.close(); mutable.update { it.copy(busy = false, code = "") } }
        }
    }
    override fun onCleared() { installer.close(); super.onCleared() }
}
