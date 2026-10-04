package dev.wristmind.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ParcelUuid
import org.json.JSONObject
import java.io.DataOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.Executors

class VoiceAssistantService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private val bridgeWorker = Executors.newFixedThreadPool(2)
    private val chatStore by lazy { ChatStore(this) }
    private val subscribers = CopyOnWriteArraySet<BluetoothDevice>()
    private var gattServer: BluetoothGattServer? = null
    private var eventCharacteristic: BluetoothGattCharacteristic? = null
    private var recorder: MediaRecorder? = null
    private var recordingFile: File? = null
    private var lastCommandId: String? = null
    private var currentState = "IDLE"
    private var bridgeActive = false
    private var serverConnected = false
    private var watchConnected = false
    private var lastStatusMessage = "Готов к подключению часов"
    private var lastTranscript: String? = null
    private var lastAnswer: String? = null
    private var lastShortAnswer: String? = null
    private var activeAudioSourceLabel = "микрофон телефона"
    @Volatile private var uploadInProgress = false
    @Volatile private var bridgeRunning = false
    private var bridgeCommandSequence = 0
    private var activeCommandId: String? = null
    private var commandOrigin = ORIGIN_PHONE
    private val audioManager by lazy { getSystemService(AudioManager::class.java) }
    private val audioDeviceCallback = object : android.media.AudioDeviceCallback() {
        override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>) {
            refreshConnectedAudioInput()
        }

        override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>) {
            refreshConnectedAudioInput()
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        audioManager.registerAudioDeviceCallback(
            audioDeviceCallback,
            Handler(Looper.getMainLooper()),
        )
        refreshConnectedAudioInput()
        startPersistentForeground("Готов к подключению часов", recording = false)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_BRIDGE -> startServerBridge()
            ACTION_START_RECORDING -> handlePhoneCommand("START")
            ACTION_STOP_RECORDING -> handlePhoneCommand("STOP")
            ACTION_RETRY -> handlePhoneCommand("RETRY")
            ACTION_RESET -> handlePhoneCommand("RESET")
            ACTION_REQUEST_STATE -> publishUiState(
                currentState,
                lastStatusMessage,
                lastTranscript,
                lastAnswer,
            )
            ACTION_SYNC_CHAT -> publishState(
                currentState,
                "Диалог «${chatStore.activeChatTitle()}» синхронизирован",
            )
            null -> {
                if (bridgeWasEnabled()) startServerBridge()
            }
        }
        return START_STICKY
    }

    private fun handlePhoneCommand(name: String) {
        activeCommandId = null
        commandOrigin = ORIGIN_PHONE
        handleCommand(BleProtocol.Command(System.nanoTime().toString(), name))
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        audioManager.unregisterAudioDeviceCallback(audioDeviceCallback)
        stopRecordingSafely()
        stopBleBridge()
        worker.shutdownNow()
        bridgeWorker.shutdownNow()
        super.onDestroy()
    }

    private fun startServerBridge() {
        getSharedPreferences(PREFERENCES, MODE_PRIVATE)
            .edit()
            .putBoolean(PREF_BRIDGE_ENABLED, true)
            .apply()
        if (bridgeRunning) {
            publishState(
                currentState,
                if (watchConnected) "Канал Zepp через VPS активен" else "Подключение к VPS…",
            )
            return
        }
        bridgeRunning = true
        bridgeActive = true
        serverConnected = false
        watchConnected = false
        publishState("IDLE", "Подключение к каналу Zepp через VPS…")
        updateNotification("Подключение к каналу Zepp")
        bridgeWorker.execute(::bridgeLoop)
    }

    private fun bridgeLoop() {
        var reconnectDelayMs = 2_000L
        try {
            val baseline = pollBridgeCommand(Int.MAX_VALUE)
            bridgeCommandSequence = baseline.optInt("sequence", 0)
        } catch (_: Exception) {
        }
        while (bridgeRunning && !Thread.currentThread().isInterrupted) {
            try {
                val poll = pollBridgeCommand(bridgeCommandSequence)
                val wasServerConnected = serverConnected
                val wasWatchConnected = watchConnected
                serverConnected = true
                reconnectDelayMs = 2_000L
                watchConnected = poll.optBoolean("watch_online", false)
                bridgeActive = true
                if (!wasServerConnected || wasWatchConnected != watchConnected) {
                    val message = if (watchConnected) {
                        "Bip 6 активен — канал через VPS готов"
                    } else {
                        "VPS подключён — откройте WristMind на Bip 6"
                    }
                    publishUiState(currentState, message)
                    postBridgeEvent(
                        currentState,
                        lastStatusMessage,
                        lastTranscript,
                        lastAnswer,
                        lastShortAnswer,
                    )
                    updateNotification(message)
                }
                val command = poll.optJSONObject("command") ?: continue
                bridgeCommandSequence = poll.optInt("sequence", bridgeCommandSequence)
                val commandId = command.getString("command_id")
                val commandName = command.getString("name")
                val chatId = command.optLong("chat_id").takeIf { it > 0 }
                val exchangeId = command.optLong("exchange_id").takeIf { it > 0 }
                activeCommandId = commandId
                commandOrigin = ORIGIN_WATCH
                handleCommand(
                    BleProtocol.Command(commandId, commandName, chatId, exchangeId),
                )
            } catch (error: Exception) {
                if (!bridgeRunning) break
                serverConnected = false
                watchConnected = false
                publishUiState(
                    currentState,
                    "Нет связи с VPS: ${error.message ?: "ошибка сети"}",
                )
                updateNotification("Переподключение к VPS")
                try {
                    Thread.sleep(reconnectDelayMs)
                    reconnectDelayMs = (reconnectDelayMs * 2).coerceAtMost(30_000L)
                } catch (_: InterruptedException) {
                    break
                }
            }
        }
    }

    private fun pollBridgeCommand(after: Int): JSONObject {
        val endpoint = URL(
            BuildConfig.WRISTMIND_BASE_URL.trimEnd('/') +
                "/v1/bridge/command?after=$after&timeout=20",
        )
        val connection = endpoint.openConnection() as HttpURLConnection
        connection.requestMethod = "GET"
        connection.connectTimeout = 15_000
        connection.readTimeout = 30_000
        addApiToken(connection)
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader().use { it.readText() }
        connection.disconnect()
        if (code !in 200..299) error("HTTP $code: $body")
        return JSONObject(body)
    }

    private fun postBridgeEvent(
        state: String,
        message: String,
        transcript: String? = null,
        answer: String? = null,
        shortAnswer: String? = null,
        errorCode: String? = null,
    ) {
        if (!bridgeRunning) return
        val payload = JSONObject()
            .put("command_id", activeCommandId)
            .put("state", state)
            .put("message", message)
            .put("transcript", transcript)
            .put("answer", answer)
            .put("short_answer", shortAnswer)
            .put("error_code", errorCode)
            .put("chat_title", chatStore.activeChatTitle())
            .put("history", chatStore.recentForWatch())
            .put("active_chat_id", chatStore.activeChatId())
            .put("chats", chatStore.chatsForWatch())
        bridgeWorker.execute {
            try {
                val endpoint = URL(
                    BuildConfig.WRISTMIND_BASE_URL.trimEnd('/') + "/v1/bridge/event",
                )
                val connection = endpoint.openConnection() as HttpURLConnection
                connection.requestMethod = "POST"
                connection.connectTimeout = 15_000
                connection.readTimeout = 15_000
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                addApiToken(connection)
                connection.outputStream.use {
                    it.write(payload.toString().toByteArray(Charsets.UTF_8))
                }
                val code = connection.responseCode
                connection.inputStream?.close()
                connection.disconnect()
                if (code !in 200..299) error("Bridge event HTTP $code")
            } catch (_: Exception) {
            }
        }
    }

    private fun addApiToken(connection: HttpURLConnection) {
        if (BuildConfig.WRISTMIND_API_TOKEN.isNotBlank()) {
            connection.setRequestProperty("X-WristMind-Token", BuildConfig.WRISTMIND_API_TOKEN)
        }
    }

    @SuppressLint("MissingPermission")
    private fun startBleBridge() {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            (
                checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) !=
                    PackageManager.PERMISSION_GRANTED ||
                    checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) !=
                    PackageManager.PERMISSION_GRANTED
                )
        ) {
            bridgeActive = false
            publishError(
                "BT_PERMISSION",
                "Разрешите WristMind доступ к устройствам поблизости",
            )
            return
        }

        val manager = getSystemService(BluetoothManager::class.java)
        val adapter = manager?.adapter
        if (adapter == null || !adapter.isEnabled) {
            publishError("BT_OFF", "Bluetooth выключен")
            return
        }
        if (!adapter.isMultipleAdvertisementSupported) {
            publishError("NO_ADV", "Телефон не поддерживает BLE advertising")
            return
        }
        if (gattServer != null && bridgeActive) {
            publishState(
                currentState,
                if (watchConnected) "Bip 6 подключён" else "Ожидание Bip 6",
            )
            return
        }
        if (gattServer != null) {
            gattServer?.close()
            gattServer = null
        }

        val command = BluetoothGattCharacteristic(
            BleProtocol.COMMAND_UUID,
            BluetoothGattCharacteristic.PROPERTY_WRITE,
            BluetoothGattCharacteristic.PERMISSION_WRITE,
        )
        eventCharacteristic = BluetoothGattCharacteristic(
            BleProtocol.EVENT_UUID,
            BluetoothGattCharacteristic.PROPERTY_READ or BluetoothGattCharacteristic.PROPERTY_NOTIFY,
            BluetoothGattCharacteristic.PERMISSION_READ,
        ).apply {
            addDescriptor(
                BluetoothGattDescriptor(
                    BleProtocol.CCCD_UUID,
                    BluetoothGattDescriptor.PERMISSION_READ or BluetoothGattDescriptor.PERMISSION_WRITE,
                ),
            )
        }
        val service = BluetoothGattService(
            BleProtocol.SERVICE_UUID,
            BluetoothGattService.SERVICE_TYPE_PRIMARY,
        ).apply {
            addCharacteristic(command)
            addCharacteristic(eventCharacteristic)
        }

        val server = try {
            manager.openGattServer(this, gattCallback)
        } catch (error: Exception) {
            null
        }
        if (server == null) {
            bridgeActive = false
            publishError("GATT_SERVER", "Не удалось открыть BLE-сервис на телефоне")
            return
        }
        gattServer = server
        if (!server.addService(service)) {
            server.close()
            gattServer = null
            bridgeActive = false
            publishError("GATT_SERVICE", "Не удалось добавить BLE-сервис")
            return
        }
        bridgeActive = false
        publishState("IDLE", "Подготовка BLE-связи…")
        updateNotification("Подготовка связи с Bip 6")
    }

    @SuppressLint("MissingPermission")
    private fun advertise(adapter: BluetoothAdapter) {
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setConnectable(true)
            .setTimeout(0)
            .build()
        val data = AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .addServiceData(
                ParcelUuid(BleProtocol.ADVERTISING_UUID),
                byteArrayOf(0x57, 0x4d),
            )
            .build()
        val advertiser = adapter.bluetoothLeAdvertiser
        if (advertiser == null) {
            bridgeActive = false
            publishError("NO_ADVERTISER", "BLE-реклама недоступна на телефоне")
            return
        }
        try {
            advertiser.startAdvertising(settings, data, advertiseCallback)
        } catch (error: Exception) {
            bridgeActive = false
            publishError(
                "ADV_EXCEPTION",
                error.message ?: "Не удалось запустить BLE-рекламу",
            )
        }
    }

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings?) {
            bridgeActive = true
            publishState("IDLE", "BLE-реклама запущена — откройте WristMind на часах")
            updateNotification("Ожидание Bip 6")
        }

        override fun onStartFailure(errorCode: Int) {
            bridgeActive = false
            val reason = when (errorCode) {
                ADVERTISE_FAILED_DATA_TOO_LARGE -> "слишком большой пакет"
                ADVERTISE_FAILED_TOO_MANY_ADVERTISERS -> "нет свободного BLE-рекламодателя"
                ADVERTISE_FAILED_ALREADY_STARTED -> "реклама уже запущена"
                ADVERTISE_FAILED_INTERNAL_ERROR -> "внутренняя ошибка Bluetooth"
                ADVERTISE_FAILED_FEATURE_UNSUPPORTED -> "функция не поддерживается"
                else -> "неизвестная ошибка"
            }
            publishError(
                "ADV_$errorCode",
                "BLE-реклама не запустилась: $reason (код $errorCode)",
            )
        }
    }

    private val gattCallback = object : BluetoothGattServerCallback() {
        @SuppressLint("MissingPermission")
        override fun onServiceAdded(status: Int, service: BluetoothGattService?) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                val adapter = getSystemService(BluetoothManager::class.java)?.adapter
                if (adapter == null) {
                    bridgeActive = false
                    publishError("BT_ADAPTER", "Bluetooth-адаптер недоступен")
                } else {
                    advertise(adapter)
                }
            } else {
                bridgeActive = false
                publishError("GATT_SERVICE", "Не удалось создать BLE-сервис")
            }
        }

        override fun onConnectionStateChange(device: BluetoothDevice?, status: Int, newState: Int) {
            val connected = newState == BluetoothGatt.STATE_CONNECTED
            if (connected) {
                watchConnected = false
                lastCommandId = null
                publishState(currentState, "BLE-устройство подключилось · проверка WristMind")
                updateNotification("Проверка подключения WristMind")
            } else {
                watchConnected = false
                publishState(currentState, "Bip 6 отключён")
                updateNotification("Ожидание Bip 6")
                if (device != null) subscribers.remove(device)
            }
        }

        @SuppressLint("MissingPermission")
        override fun onCharacteristicWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            characteristic: BluetoothGattCharacteristic,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray,
        ) {
            val command = if (characteristic.uuid == BleProtocol.COMMAND_UUID && offset == 0) {
                BleProtocol.parseCommand(value)
            } else null
            if (command != null && !watchConnected) {
                watchConnected = true
                publishState(currentState, "Bip 6 подключён к WristMind")
                updateNotification("Bip 6 подключён к WristMind")
            }
            if (responseNeeded) {
                gattServer?.sendResponse(
                    device,
                    requestId,
                    if (command == null) BluetoothGatt.GATT_FAILURE else BluetoothGatt.GATT_SUCCESS,
                    0,
                    null,
                )
            }
            command?.let {
                commandOrigin = ORIGIN_WATCH
                handleCommand(it)
            }
        }

        @SuppressLint("MissingPermission")
        override fun onCharacteristicReadRequest(
            device: BluetoothDevice,
            requestId: Int,
            offset: Int,
            characteristic: BluetoothGattCharacteristic,
        ) {
            val value = BleProtocol.status(currentState)
            val result = if (offset <= value.size) value.copyOfRange(offset, value.size) else byteArrayOf()
            gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, result)
        }

        @SuppressLint("MissingPermission")
        override fun onDescriptorWriteRequest(
            device: BluetoothDevice,
            requestId: Int,
            descriptor: BluetoothGattDescriptor,
            preparedWrite: Boolean,
            responseNeeded: Boolean,
            offset: Int,
            value: ByteArray,
        ) {
            if (descriptor.uuid == BleProtocol.CCCD_UUID) {
                if (value.contentEquals(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)) {
                    subscribers += device
                    watchConnected = true
                    publishState(currentState, "Bip 6 подключён к WristMind")
                    updateNotification("Bip 6 подключён к WristMind")
                } else {
                    subscribers -= device
                    watchConnected = subscribers.isNotEmpty()
                }
            }
            if (responseNeeded) {
                gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, value)
            }
        }
    }

    private fun handleCommand(command: BleProtocol.Command) {
        if (command.id == lastCommandId) {
            notifyWatch(BleProtocol.status(currentState))
            return
        }
        lastCommandId = command.id
        when (command.name) {
            "START" -> startRecording()
            "STOP" -> stopAndUpload()
            "PING" -> {
                publishState(currentState, "Диагностика завершена — канал отвечает")
                updateNotification("Канал WristMind восстановлен")
            }
            "CHAT_CREATE" -> {
                chatStore.createChat()
                publishState("IDLE", "Новый диалог создан с Bip 6")
            }
            "CHAT_SELECT" -> {
                command.chatId?.let(chatStore::setActiveChat)
                publishState("IDLE", "Диалог «${chatStore.activeChatTitle()}» выбран")
            }
            "CHAT_DETAIL" -> {
                val exchange = command.exchangeId?.let(chatStore::exchange)
                if (exchange == null) {
                    publishError("CHAT_NOT_FOUND", "Сообщение не найдено")
                } else {
                    postBridgeEvent(
                        currentState,
                        "Полный ответ загружен",
                        transcript = exchange.userText,
                        answer = exchange.assistantText,
                        shortAnswer = sentencePreview(exchange.assistantText, 260),
                    )
                    publishUiState(currentState, "Полный ответ отправлен на Bip 6")
                }
            }
            "RETRY" -> recordingFile?.let(::upload) ?: publishError("NO_AUDIO", "Нет записи для повтора")
            "RESET" -> resetFailedRequest()
            else -> publishError("BAD_CMD", "Неизвестная команда")
        }
    }

    private fun resetFailedRequest() {
        stopRecordingSafely()
        recordingFile?.delete()
        recordingFile = null
        lastTranscript = null
        lastAnswer = null
        lastShortAnswer = null
        publishState("IDLE", "Ошибка сброшена — можно записать новый вопрос")
        updateNotification("Готов к новой записи")
    }

    private fun startRecording() {
        if (uploadInProgress) {
            publishState("SEND", "Предыдущая запись ожидает восстановления связи")
            return
        }
        if (recorder != null) {
            publishState("REC", "Запись уже идёт")
            return
        }
        try {
            val target = File(cacheDir, "recording-${System.currentTimeMillis()}.m4a")
            val mediaRecorder = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(this) else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }
            mediaRecorder.apply {
                setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioChannels(1)
                setAudioSamplingRate(48_000)
                setAudioEncodingBitRate(128_000)
                setOutputFile(target.absolutePath)
                activeAudioSourceLabel = selectPreferredAudioInput(this)
                prepare()
                start()
                routedDevice?.let { routed ->
                    if (isExternalAudioInput(routed)) {
                        activeAudioSourceLabel = describeAudioInput(routed)
                    }
                }
            }
            recordingFile = target
            recorder = mediaRecorder
            startPersistentForeground("Запись: $activeAudioSourceLabel", recording = true)
            publishState("REC", "Запись идёт · $activeAudioSourceLabel")
            updateNotification("Запись: $activeAudioSourceLabel")
        } catch (error: Exception) {
            recorder?.release()
            recorder = null
            publishError("MIC", error.message ?: "Ошибка микрофона")
        }
    }

    private fun selectPreferredAudioInput(mediaRecorder: MediaRecorder): String {
        val external = findExternalAudioInput()
        if (external != null) {
            val selected = mediaRecorder.setPreferredDevice(external)
            val label = describeAudioInput(external)
            return if (selected) label else "$label · автовыбор Android"
        }
        mediaRecorder.setPreferredDevice(null)
        return "микрофон телефона"
    }

    private fun refreshConnectedAudioInput() {
        if (recorder != null) return
        activeAudioSourceLabel = findExternalAudioInput()
            ?.let(::describeAudioInput)
            ?: "микрофон телефона"
        publishUiState(
            currentState,
            lastStatusMessage,
            lastTranscript,
            lastAnswer,
        )
    }

    private fun findExternalAudioInput(): AudioDeviceInfo? =
        audioManager
            .getDevices(AudioManager.GET_DEVICES_INPUTS)
            .filter(::isExternalAudioInput)
            .minByOrNull { device ->
                when (device.type) {
                    AudioDeviceInfo.TYPE_USB_HEADSET -> 0
                    AudioDeviceInfo.TYPE_USB_DEVICE -> 1
                    AudioDeviceInfo.TYPE_USB_ACCESSORY -> 2
                    AudioDeviceInfo.TYPE_WIRED_HEADSET -> 3
                    else -> 4
                }
            }

    private fun isExternalAudioInput(device: AudioDeviceInfo): Boolean =
        device.type == AudioDeviceInfo.TYPE_USB_DEVICE ||
            device.type == AudioDeviceInfo.TYPE_USB_HEADSET ||
            device.type == AudioDeviceInfo.TYPE_USB_ACCESSORY ||
            device.type == AudioDeviceInfo.TYPE_WIRED_HEADSET ||
            device.type == AudioDeviceInfo.TYPE_LINE_ANALOG

    private fun describeAudioInput(device: AudioDeviceInfo): String {
        val product = device.productName?.toString()?.trim().orEmpty()
        return if (product.isBlank()) "внешний микрофон" else "внешний: $product"
    }

    private fun stopAndUpload() {
        val target = recordingFile
        if (recorder == null || target == null) {
            publishError("NOT_REC", "Запись не запущена")
            return
        }
        try {
            recorder?.stop()
            recorder?.release()
            recorder = null
            startPersistentForeground("Отправка аудио", recording = false)
            publishState("STOP", "Запись остановлена")
            upload(target)
        } catch (error: Exception) {
            recorder?.release()
            recorder = null
            target.delete()
            publishError("REC_STOP", error.message ?: "Не удалось завершить запись")
        }
    }

    private fun upload(target: File) {
        if (uploadInProgress) return
        uploadInProgress = true
        publishState("SEND", "Отправка")
        updateNotification("Отправка аудио")
        worker.execute {
            var retryDelayMs = 2_000L
            var aiAttempts = 0
            while (!Thread.currentThread().isInterrupted) {
                try {
                    val response = postAudio(target) {
                        publishState("PROC", "Распознавание и формирование ответа")
                    }
                    val transcript = response.getString("transcript")
                    val answer = response.getString("answer")
                    val shortAnswer = response.getString("short_answer")
                    chatStore.addExchange(transcript, answer)
                    publishState("READY", "Готово", transcript, answer, shortAnswer)
                    BleProtocol.transcriptFrames(transcript).forEach(::notifyWatch)
                    BleProtocol.answerFrames(shortAnswer).forEach(::notifyWatch)
                    updateNotification("Ответ получен")
                    uploadInProgress = false
                    return@execute
                } catch (error: Exception) {
                    val failure = describeUploadError(error)
                    if (failure.code == "AI_SERVER") aiAttempts += 1
                    val canRetry = failure.retryable &&
                        (failure.code != "AI_SERVER" || aiAttempts < 3)
                    if (!canRetry) {
                        publishError(failure.code, failure.message)
                        updateNotification("Ошибка отправки")
                        uploadInProgress = false
                        return@execute
                    }
                    val seconds = retryDelayMs / 1_000
                    publishState(
                        "SEND",
                        "${failure.message}. Повтор автоматически через $seconds сек.",
                    )
                    updateNotification("Ожидание сети · повтор через $seconds сек.")
                    try {
                        Thread.sleep(retryDelayMs)
                    } catch (_: InterruptedException) {
                        uploadInProgress = false
                        return@execute
                    }
                    retryDelayMs = (retryDelayMs * 2).coerceAtMost(30_000L)
                }
            }
        }
    }

    private data class UploadFailure(
        val code: String,
        val message: String,
        val retryable: Boolean,
    )

    private fun describeUploadError(error: Exception): UploadFailure {
        val raw = error.message?.trim().orEmpty()
        val httpCode = Regex("""^HTTP\s+(\d{3})""").find(raw)
            ?.groupValues
            ?.getOrNull(1)
            ?.toIntOrNull()
        val detail = runCatching {
            JSONObject(raw.substringAfter(": ", "{}")).optString("detail")
        }.getOrNull().orEmpty()
        return when {
            httpCode == 502 -> UploadFailure("AI_SERVER", (
                detail.takeIf { it.isNotBlank() }
                    ?.let { "Ошибка сервиса распознавания или OpenRouter: $it" }
                    ?: "Сервис распознавания или OpenRouter временно недоступен"
                ), true)
            httpCode == 401 || httpCode == 403 ->
                UploadFailure(
                    "SERVER_AUTH",
                    "VPS отклонил ключ приложения. Нужна новая сборка",
                    false,
                )
            httpCode != null ->
                UploadFailure(
                    "VPS_HTTP",
                    "VPS ответил с ошибкой HTTP $httpCode",
                    httpCode >= 500,
                )
            else ->
                UploadFailure(
                    "NETWORK",
                    "Нет связи с VPS: ${raw.ifBlank { "проверьте интернет" }}",
                    true,
                )
        }
    }

    private fun sentencePreview(value: String, limit: Int): String {
        val clean = value.replace(Regex("""\s+"""), " ").trim()
        if (clean.length <= limit) return clean
        val prefix = clean.take(limit)
        val sentenceEnd = Regex("""[.!?](?:\s|$)""")
            .findAll(prefix)
            .lastOrNull()
            ?.range
            ?.first
        val complete = sentenceEnd?.let { prefix.take(it + 1).trim() }.orEmpty()
        if (complete.length >= limit / 3) return complete
        return "${clean.take(limit - 1).substringBeforeLast(' ').trim()}…"
    }

    private fun postAudio(target: File, onUploaded: () -> Unit): JSONObject {
        val boundary = "WristMind-${System.currentTimeMillis()}"
        val endpoint = URL(BuildConfig.WRISTMIND_BASE_URL.trimEnd('/') + "/v1/audio/query")
        val connection = endpoint.openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        if (BuildConfig.WRISTMIND_API_TOKEN.isNotBlank()) {
            connection.setRequestProperty("X-WristMind-Token", BuildConfig.WRISTMIND_API_TOKEN)
        }
        DataOutputStream(connection.outputStream).use { output ->
            output.writeBytes("--$boundary\r\n")
            output.writeBytes("Content-Disposition: form-data; name=\"rag_mode\"\r\n\r\n")
            output.writeBytes("AUTO\r\n")
            output.writeBytes("--$boundary\r\n")
            output.writeBytes("Content-Disposition: form-data; name=\"conversation_context\"\r\n")
            output.writeBytes("Content-Type: text/plain; charset=utf-8\r\n\r\n")
            output.write(chatStore.contextForModel().toString().toByteArray(Charsets.UTF_8))
            output.writeBytes("\r\n")
            output.writeBytes("--$boundary\r\n")
            output.writeBytes("Content-Disposition: form-data; name=\"audio\"; filename=\"voice.m4a\"\r\n")
            output.writeBytes("Content-Type: audio/mp4\r\n\r\n")
            target.inputStream().use { it.copyTo(output) }
            output.writeBytes("\r\n--$boundary--\r\n")
        }
        onUploaded()
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader().use { it.readText() }
        connection.disconnect()
        if (code !in 200..299) error("HTTP $code: $body")
        return JSONObject(body)
    }

    private fun publishState(
        state: String,
        message: String,
        transcript: String? = null,
        answer: String? = null,
        shortAnswer: String? = null,
    ) {
        currentState = state
        lastStatusMessage = message
        if (transcript != null) lastTranscript = transcript
        if (answer != null) lastAnswer = answer
        if (shortAnswer != null) lastShortAnswer = shortAnswer
        notifyWatch(BleProtocol.status(state))
        postBridgeEvent(state, message, transcript, answer, shortAnswer)
        publishUiState(state, message, transcript, answer)
    }

    private fun publishUiState(
        state: String,
        message: String,
        transcript: String? = null,
        answer: String? = null,
    ) {
        sendBroadcast(
            Intent(ACTION_UI_STATE)
                .setPackage(packageName)
                .putExtra(EXTRA_STATUS, message)
                .putExtra(EXTRA_STATE, state)
                .putExtra(EXTRA_BRIDGE_ACTIVE, bridgeActive)
                .putExtra(EXTRA_SERVER_CONNECTED, serverConnected)
                .putExtra(EXTRA_BRIDGE_CONNECTED, watchConnected)
                .putExtra(EXTRA_SOURCE, activeAudioSourceLabel)
                .putExtra(EXTRA_COMMAND_ORIGIN, commandOrigin)
                .putExtra(EXTRA_TRANSCRIPT, transcript)
                .putExtra(EXTRA_ANSWER, answer),
        )
    }

    private fun publishError(code: String, message: String) {
        currentState = "ERROR"
        lastStatusMessage = message
        notifyWatch(BleProtocol.error(code))
        postBridgeEvent("ERROR", message, errorCode = code)
        sendBroadcast(
            Intent(ACTION_UI_STATE)
                .setPackage(packageName)
                .putExtra(EXTRA_STATUS, message)
                .putExtra(EXTRA_STATE, "ERROR")
                .putExtra(EXTRA_BRIDGE_ACTIVE, bridgeActive)
                .putExtra(EXTRA_SERVER_CONNECTED, serverConnected)
                .putExtra(EXTRA_BRIDGE_CONNECTED, watchConnected)
                .putExtra(EXTRA_SOURCE, "микрофон телефона")
                .putExtra(EXTRA_COMMAND_ORIGIN, commandOrigin),
        )
    }

    @SuppressLint("MissingPermission")
    private fun notifyWatch(value: ByteArray) {
        val characteristic = eventCharacteristic ?: return
        characteristic.value = value
        subscribers.forEach { device ->
            if (Build.VERSION.SDK_INT >= 33) {
                gattServer?.notifyCharacteristicChanged(device, characteristic, false, value)
            } else {
                @Suppress("DEPRECATION")
                gattServer?.notifyCharacteristicChanged(device, characteristic, false)
            }
        }
    }

    private fun stopRecordingSafely() {
        try {
            recorder?.stop()
        } catch (_: Exception) {
        }
        recorder?.release()
        recorder = null
    }

    @SuppressLint("MissingPermission")
    private fun stopBleBridge() {
        bridgeRunning = false
        val adapter = getSystemService(BluetoothManager::class.java)?.adapter
        adapter?.bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback)
        gattServer?.close()
        gattServer = null
        bridgeActive = false
        serverConnected = false
        watchConnected = false
        subscribers.clear()
    }

    private fun bridgeWasEnabled(): Boolean =
        getSharedPreferences(PREFERENCES, MODE_PRIVATE)
            .getBoolean(PREF_BRIDGE_ENABLED, false)

    private fun startPersistentForeground(text: String, recording: Boolean) {
        val currentNotification = notification(text)
        if (Build.VERSION.SDK_INT >= 29) {
            var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            if (recording) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            startForeground(NOTIFICATION_ID, currentNotification, type)
        } else {
            startForeground(NOTIFICATION_ID, currentNotification)
        }
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "WristMind background service",
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun notification(text: String): Notification =
        Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("WristMind")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .build()

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }

    companion object {
        const val ACTION_START_BRIDGE = "dev.wristmind.START_BRIDGE"
        const val ACTION_START_RECORDING = "dev.wristmind.START_RECORDING"
        const val ACTION_STOP_RECORDING = "dev.wristmind.STOP_RECORDING"
        const val ACTION_RETRY = "dev.wristmind.RETRY"
        const val ACTION_RESET = "dev.wristmind.RESET"
        const val ACTION_REQUEST_STATE = "dev.wristmind.REQUEST_STATE"
        const val ACTION_SYNC_CHAT = "dev.wristmind.SYNC_CHAT"
        const val ACTION_UI_STATE = "dev.wristmind.UI_STATE"
        const val EXTRA_STATUS = "status"
        const val EXTRA_STATE = "state"
        const val EXTRA_BRIDGE_ACTIVE = "bridge_active"
        const val EXTRA_SERVER_CONNECTED = "server_connected"
        const val EXTRA_BRIDGE_CONNECTED = "bridge_connected"
        const val EXTRA_SOURCE = "source"
        const val EXTRA_COMMAND_ORIGIN = "command_origin"
        const val EXTRA_TRANSCRIPT = "transcript"
        const val EXTRA_ANSWER = "answer"
        const val ORIGIN_PHONE = "PHONE"
        const val ORIGIN_WATCH = "WATCH"
        private const val CHANNEL_ID = "wristmind_service"
        private const val NOTIFICATION_ID = 710
        private const val PREFERENCES = "wristmind_service"
        private const val PREF_BRIDGE_ENABLED = "bridge_enabled"
    }
}
