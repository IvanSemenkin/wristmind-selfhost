package dev.wristmind.phone.install

import android.content.Context
import android.content.pm.PackageManager
import io.github.muntashirakon.adb.AbsAdbConnectionManager
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runInterruptible
import java.io.File

internal class WatchInstaller(private val context: Context) : AutoCloseable {
    @Volatile private var tunnel: AdbTunnel? = null
    @Volatile private var manager: AbsAdbConnectionManager? = null
    private fun connection(): AbsAdbConnectionManager = manager ?: run {
        val identity = AdbIdentity(context)
        object : AbsAdbConnectionManager() {
            override fun getPrivateKey() = identity.privateKey
            override fun getCertificate() = identity.certificate
            override fun getDeviceName() = "WristMind Companion"
        }.apply { setApi(30); setTimeout(15, TimeUnit.SECONDS); manager = this }
    }

    suspend fun pair(host: String, port: Int, code: String) = runInterruptible(Dispatchers.IO) {
        require(code.matches(Regex("[0-9]{6}"))) { "Введите код сопряжения из 6 цифр с часов" }
        val relay = AdbTunnel(host, port).also { tunnel = it }
        require(connection().pair("127.0.0.1", relay.localPort, code)) { "Сопряжение отклонено. Откройте на часах новый код и проверьте порт сопряжения." }
    }

    suspend fun check(host: String, port: Int): WatchDetails = runInterruptible(Dispatchers.IO) {
        close()
        val relay = AdbTunnel(host, port).also { tunnel = it }
        require(connection().connect("127.0.0.1", relay.localPort)) { "Часы не ответили. Проверьте общую Wi-Fi сеть, включение отладки и порт подключения." }
        val sdk = shell("getprop ro.build.version.sdk").trim().toIntOrNull() ?: error("Не удалось определить версию Wear OS")
        val apk = bundledApk()
        val info = context.packageManager.getPackageArchiveInfo(apk.path, PackageManager.GET_SIGNING_CERTIFICATES)
            ?: error("Встроенный APK повреждён")
        require(info.packageName == PACKAGE) { "APK не принадлежит WristMind" }
        val phone = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
        val signatures = info.signingInfo?.apkContentsSigners?.toSet().orEmpty()
        require(signatures.isNotEmpty() && signatures == phone.signingInfo?.apkContentsSigners?.toSet()) {
            "Подписи компаньона и часов должны совпадать для защищённой передачи настроек"
        }
        InstallValidation.compatible(sdk, shell("pm list features"), info.applicationInfo?.minSdkVersion ?: 30)
        val installed = shell("dumpsys package $PACKAGE")
        val code = Regex("versionCode=(\\d+)").find(installed)?.groupValues?.get(1)?.toLongOrNull()
        require(code == null || code <= info.longVersionCode) { "На часах более новая версия. Обновите компаньон." }
        WatchDetails(shell("getprop ro.product.model").trim(), sdk, info.versionName.orEmpty(), code, info.longVersionCode)
    }

    suspend fun install(onProgress: (Float) -> Unit) = runInterruptible(Dispatchers.IO) {
        tunnel?.extend(175)
        val apk = bundledApk()
        connection().openStream("shell,v2,raw:cmd package install -r -S ${apk.length()}").use { stream ->
            val output = stream.openOutputStream()
            apk.inputStream().use { input ->
                val buffer = ByteArray(4000)
                var sent = 0L
                while (true) {
                    val size = input.read(buffer)
                    if (size < 0) break
                    output.write(ShellProtocol.stdin(buffer, size)); output.flush()
                    sent += size
                    onProgress(sent.toFloat() / apk.length())
                }
            }
            // PackageManager reads exactly -S bytes; closing the stream here would discard its result.
            output.write(ShellProtocol.closeInput()); output.flush()
            val result = ShellProtocol.readReply(stream.openInputStream())
            InstallValidation.installationResult(result.text)
        }
    }

    suspend fun activate(nonce: String) = runInterruptible(Dispatchers.IO) {
        require(nonce.matches(Regex("[a-f0-9-]{36}")))
        val reply = shell("am start -n $PACKAGE/dev.wristmind.wear.MainActivity --es wristmind_install_nonce $nonce")
        require("Error" !in reply) { "Откройте WristMind на часах и повторите передачу настроек." }
    }

    private fun shell(command: String): String = connection().openStream("shell,v2,raw:$command").use {
        val result = ShellProtocol.readReply(it.openInputStream())
        require(result.exitCode == 0) { "Часы не выполнили проверку. Убедитесь, что отладка разрешена, и повторите." }
        result.text
    }
    private fun bundledApk(): File = context.cacheDir.resolve("wristmind-wear.apk").also { file ->
        context.assets.open("wristmind-wear.apk").use { input -> file.outputStream().use(input::copyTo) }
    }
    override fun close() { tunnel?.close(); tunnel = null; manager?.let { runCatching { it.close() } }; manager = null }
    companion object { const val PACKAGE = "dev.wristmind.app" }
}

data class WatchDetails(val name: String, val sdk: Int, val version: String, val installedCode: Long?, val bundledCode: Long)
