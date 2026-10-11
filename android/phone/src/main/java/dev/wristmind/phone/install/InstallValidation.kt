package dev.wristmind.phone.install

import java.net.URI

object InstallValidation {
    fun server(value: String): String {
        val uri = runCatching { URI(value.trim()) }.getOrNull()
        require(uri != null && uri.scheme == "https" && !uri.host.isNullOrBlank() &&
            (uri.port == -1 || uri.port in 1..65535) && uri.userInfo == null && uri.query == null && uri.fragment == null &&
            uri.path.orEmpty().trim('/') == "") {
            "Введите HTTPS-адрес панели, например https://ai.example.com — без /v1 и пароля"
        }
        return value.trim().trimEnd('/')
    }

    fun host(value: String): String {
        val parts = value.trim().split('.')
        require(parts.size == 4 && parts.all { it.matches(Regex("[0-9]{1,3}")) && it.toInt() in 0..255 } &&
            parts[0].toInt() in 1..223 && parts[0].toInt() != 127) {
            "Введите IPv4-адрес, который показан на часах"
        }
        return parts.joinToString(".") { it.toInt().toString() }
    }

    fun port(value: String): Int = value.toIntOrNull()?.takeIf { it in 1..65535 }
        ?: throw IllegalArgumentException("Порт должен быть числом от 1 до 65535")

    fun compatible(sdk: Int, features: String, minSdk: Int) {
        require(sdk >= minSdk) { "Нужен Wear OS на Android API $minSdk или новее. У часов API $sdk." }
        require(features.lineSequence().any { it.trim() == "feature:android.hardware.type.watch" }) {
            "По этому адресу подключено устройство без Wear OS. Установка остановлена."
        }
    }

    fun installationResult(output: String) {
        require(output.lineSequence().any { it.trim() == "Success" }) {
            when {
                "UPDATE_INCOMPATIBLE" in output -> "Подпись приложения отличается. Данные сохранены. Нужен APK с прежним ключом подписи."
                "VERSION_DOWNGRADE" in output -> "На часах уже более новая версия. Понижение версии запрещено."
                "INSUFFICIENT_STORAGE" in output -> "На часах недостаточно свободного места."
                else -> "Часы не завершили установку. Проверьте подтверждение на часах и повторите попытку."
            }
        }
    }
}
