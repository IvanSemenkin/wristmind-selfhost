package dev.wristmind.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Dialog
import android.content.ComponentName
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Space
import android.widget.TextView
import io.noties.markwon.Markwon
import io.noties.markwon.ext.latex.JLatexMathPlugin
import io.noties.markwon.inlineparser.MarkwonInlineParserPlugin

class MainActivity : Activity() {
    private lateinit var connectionBadge: TextView
    private lateinit var headline: TextView
    private lateinit var status: TextView
    private lateinit var source: TextView
    private lateinit var actionButton: Button
    private lateinit var bridgeButton: Button
    private lateinit var chatTitleButton: Button
    private lateinit var messagesContainer: LinearLayout
    private lateinit var orb: AssistantOrbView
    private val chatStore by lazy { ChatStore(this) }
    private val markdownRenderer by lazy {
        val formulaTextSize = 19f * resources.displayMetrics.scaledDensity
        Markwon.builder(this)
            .usePlugin(MarkwonInlineParserPlugin.create())
            .usePlugin(
                JLatexMathPlugin.create(formulaTextSize) { builder ->
                    builder.inlinesEnabled(true)
                },
            )
            .build()
    }
    private var uiState = "OFFLINE"
    private var bridgeActive = false
    private var serverConnected = false
    private var watchConnected = false
    private var commandOrigin = VoiceAssistantService.ORIGIN_PHONE
    private var lastRenderedState = ""

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val newState = intent?.getStringExtra(VoiceAssistantService.EXTRA_STATE)
            val message = intent?.getStringExtra(VoiceAssistantService.EXTRA_STATUS)
            if (newState != null) uiState = newState
            if (intent?.hasExtra(VoiceAssistantService.EXTRA_BRIDGE_ACTIVE) == true) {
                bridgeActive = intent.getBooleanExtra(
                    VoiceAssistantService.EXTRA_BRIDGE_ACTIVE,
                    false,
                )
            }
            if (intent?.hasExtra(VoiceAssistantService.EXTRA_BRIDGE_CONNECTED) == true) {
                watchConnected = intent.getBooleanExtra(
                    VoiceAssistantService.EXTRA_BRIDGE_CONNECTED,
                    false,
                )
            }
            if (intent?.hasExtra(VoiceAssistantService.EXTRA_SERVER_CONNECTED) == true) {
                serverConnected = intent.getBooleanExtra(
                    VoiceAssistantService.EXTRA_SERVER_CONNECTED,
                    false,
                )
            }
            intent?.getStringExtra(VoiceAssistantService.EXTRA_COMMAND_ORIGIN)?.let {
                commandOrigin = it
            }
            renderState(uiState, message)
            val microphone = intent?.getStringExtra(VoiceAssistantService.EXTRA_SOURCE)
                ?: "микрофон телефона"
            source.text = when {
                commandOrigin == VoiceAssistantService.ORIGIN_WATCH && uiState == "REC" ->
                    "Команда с Bip 6  ·  $microphone"
                commandOrigin == VoiceAssistantService.ORIGIN_WATCH ->
                    "Запрос с Bip 6  ·  $microphone"
                else -> "Запрос с телефона  ·  $microphone"
            }
            if (
                intent?.hasExtra(VoiceAssistantService.EXTRA_TRANSCRIPT) == true ||
                intent?.hasExtra(VoiceAssistantService.EXTRA_ANSWER) == true
            ) renderChat()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = COLOR_BACKGROUND
        window.navigationBarColor = COLOR_BACKGROUND
        window.decorView.systemUiVisibility = 0
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
        }
        setContentView(buildUi())
        renderState("OFFLINE", null)
        renderChat()
    }

    @SuppressLint("UnspecifiedRegisterReceiverFlag")
    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(VoiceAssistantService.ACTION_UI_STATE)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(receiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(receiver, filter)
        }
        val bridgeEnabled = getSharedPreferences("wristmind_service", MODE_PRIVATE)
            .getBoolean("bridge_enabled", false)
        if (bridgeEnabled) {
            sendServiceAction(VoiceAssistantService.ACTION_REQUEST_STATE)
        }
    }

    override fun onStop() {
        unregisterReceiver(receiver)
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        val bridgeEnabled = getSharedPreferences("wristmind_service", MODE_PRIVATE)
            .getBoolean("bridge_enabled", false)
        if (bridgeEnabled) {
            requestBatteryExemptionOnce()
            requestPocoAutostartOnce()
        }
        if (::messagesContainer.isInitialized) renderChat()
    }

    private fun buildUi(): View {
        val background = FrameLayout(this).apply {
            setBackgroundColor(COLOR_BACKGROUND)
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(COLOR_BACKGROUND, Color.rgb(20, 22, 39), Color.rgb(12, 15, 28)),
            )
        }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            overScrollMode = View.OVER_SCROLL_NEVER
            clipToPadding = false
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(28), dp(22), dp(32))
        }

        content.addView(buildHeader())
        orb = AssistantOrbView(this)
        content.addView(
            orb,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(245)).apply {
                topMargin = dp(6)
            },
        )

        headline = textView("", 27f, Color.WHITE, Typeface.BOLD, Gravity.CENTER)
        content.addView(headline, matchWidth())
        status = textView("", 15f, COLOR_SECONDARY, Typeface.NORMAL, Gravity.CENTER).apply {
            setLineSpacing(0f, 1.15f)
        }
        content.addView(
            status,
            matchWidth().apply {
                topMargin = dp(7)
                leftMargin = dp(18)
                rightMargin = dp(18)
            },
        )

        source = textView(
            "Встроенный микрофон Poco F6",
            14f,
            Color.rgb(205, 211, 232),
            Typeface.NORMAL,
            Gravity.CENTER,
        ).apply {
            setCompoundDrawablesWithIntrinsicBounds(android.R.drawable.presence_audio_online, 0, 0, 0)
            compoundDrawablePadding = dp(9)
            setPadding(dp(16), dp(11), dp(16), dp(11))
            this.background = rounded(Color.rgb(31, 35, 55), dp(18), Color.rgb(51, 57, 82))
        }
        content.addView(
            source,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(20)
                leftMargin = dp(18)
                rightMargin = dp(18)
            },
        )

        actionButton = button("Начать запись", COLOR_ACCENT, Color.WHITE).apply {
            setOnClickListener { onPrimaryAction() }
        }
        content.addView(actionButton, matchWidth(dp(58)).apply { topMargin = dp(18) })

        bridgeButton = button("Включить связь с Bip 6", Color.TRANSPARENT, Color.rgb(197, 187, 255)).apply {
            this.background = rounded(Color.TRANSPARENT, dp(22), Color.rgb(75, 67, 117))
            gravity = Gravity.CENTER
            textSize = 14f
            maxLines = 3
            minHeight = dp(76)
            setPadding(dp(18), dp(14), dp(18), dp(14))
            setOnClickListener { requestPermissionsAndStart() }
        }
        content.addView(bridgeButton, matchWidth().apply { topMargin = dp(10) })

        content.addView(sectionLabel("ДИАЛОГИ"), matchWidth().apply { topMargin = dp(31) })
        val chatActions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        chatTitleButton = button("Текущий диалог", Color.rgb(27, 32, 52), Color.rgb(224, 226, 244)).apply {
            textSize = 14f
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
            maxLines = 2
            setPadding(dp(17), dp(8), dp(14), dp(8))
            this.background = rounded(Color.rgb(27, 32, 52), dp(19), Color.rgb(65, 70, 99))
            setOnClickListener { showChatPicker() }
        }
        chatActions.addView(chatTitleButton, LinearLayout.LayoutParams(0, dp(58), 1f))
        val newChatButton = button("+", COLOR_ACCENT, Color.WHITE).apply {
            textSize = 25f
            contentDescription = "Новый диалог"
            setOnClickListener {
                chatStore.createChat()
                renderChat()
                syncChatToWatch()
            }
        }
        chatActions.addView(
            newChatButton,
            LinearLayout.LayoutParams(dp(58), dp(58)).apply { leftMargin = dp(10) },
        )
        content.addView(chatActions, matchWidth().apply { topMargin = dp(10) })

        messagesContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        content.addView(messagesContainer, matchWidth().apply { topMargin = dp(4) })

        scroll.addView(content)
        background.addView(scroll)
        if (Build.VERSION.SDK_INT >= 30) {
            background.setOnApplyWindowInsetsListener { _, insets ->
                val systemBars = insets.getInsets(
                    WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout(),
                )
                scroll.setPadding(0, systemBars.top, 0, systemBars.bottom)
                insets
            }
            background.requestApplyInsets()
        }
        return background
    }

    private fun buildHeader(): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val titleBlock = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titleBlock.addView(textView("WRISTMIND", 12f, Color.rgb(167, 139, 250), Typeface.BOLD, Gravity.START).apply {
            letterSpacing = 0.18f
        })
        titleBlock.addView(
            textView(
                "Голос рядом  ·  ${BuildConfig.VERSION_NAME}",
                21f,
                Color.WHITE,
                Typeface.BOLD,
                Gravity.START,
            ),
        )
        row.addView(titleBlock)
        row.addView(Space(this), LinearLayout.LayoutParams(0, 1, 1f))
        connectionBadge = textView("●  НЕ В СЕТИ", 11f, COLOR_SECONDARY, Typeface.BOLD, Gravity.CENTER).apply {
            letterSpacing = 0.08f
            setPadding(dp(12), dp(8), dp(12), dp(8))
            background = rounded(Color.rgb(30, 34, 51), dp(16), Color.rgb(50, 55, 78))
        }
        row.addView(connectionBadge)
        return row
    }

    private fun dialogCard(
        sender: String,
        role: String,
        value: TextView,
        accent: Int,
        isUser: Boolean,
    ): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(17), dp(14), dp(17), dp(18))
            background = rounded(
                if (isUser) Color.rgb(25, 38, 65) else Color.rgb(34, 28, 56),
                dp(22),
                if (isUser) Color.rgb(63, 91, 139) else Color.rgb(81, 65, 121),
            )
        }
        val identity = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val avatar = textView(
            if (isUser) "В" else "W",
            11f,
            Color.WHITE,
            Typeface.BOLD,
            Gravity.CENTER,
        ).apply {
            background = rounded(accent, dp(14))
        }
        identity.addView(avatar, LinearLayout.LayoutParams(dp(28), dp(28)))
        val labels = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), 0, 0, 0)
        }
        labels.addView(textView(sender, 12f, accent, Typeface.BOLD, Gravity.START).apply {
            letterSpacing = 0.1f
        })
        labels.addView(
            textView(
                role,
                11f,
                Color.rgb(151, 159, 187),
                Typeface.NORMAL,
                Gravity.START,
            ),
        )
        identity.addView(labels)
        card.addView(identity)
        card.addView(
            View(this).apply { setBackgroundColor(accent) },
            matchWidth(dp(2)).apply { topMargin = dp(12) },
        )
        card.addView(value, matchWidth().apply {
            topMargin = dp(12)
        }
        )
        return card
    }

    private fun renderChat() {
        if (!::messagesContainer.isInitialized) return
        chatTitleButton.text = "${chatStore.activeChatTitle()}\nНажмите, чтобы выбрать другой"
        messagesContainer.removeAllViews()
        val exchanges = chatStore.listExchanges(limit = 12)
        if (exchanges.isEmpty()) {
            val empty = textView(
                "В этом диалоге пока нет сообщений.\nНачните запись на телефоне или Bip 6.",
                15f,
                Color.rgb(168, 176, 204),
                Typeface.NORMAL,
                Gravity.CENTER,
            ).apply {
                setPadding(dp(18), dp(24), dp(18), dp(24))
                background = rounded(Color.rgb(20, 24, 40), dp(20), Color.rgb(48, 54, 79))
            }
            messagesContainer.addView(empty, matchWidth().apply { topMargin = dp(12) })
            return
        }
        exchanges.forEach { exchange ->
            val userText = textView(
                exchange.userText,
                16f,
                Color.rgb(232, 236, 249),
                Typeface.NORMAL,
                Gravity.START,
            ).apply { setTextIsSelectable(true) }
            messagesContainer.addView(
                dialogCard(
                    sender = "ВЫ",
                    role = "ваш вопрос",
                    value = userText,
                    accent = Color.rgb(120, 170, 255),
                    isUser = true,
                ),
                matchWidth().apply { topMargin = dp(12) },
            )
            val assistantText = textView(
                "",
                19f,
                Color.rgb(244, 242, 255),
                Typeface.NORMAL,
                Gravity.START,
            ).apply {
                setLineSpacing(dp(4).toFloat(), 1.18f)
                setTextIsSelectable(true)
                setPadding(0, dp(3), 0, dp(6))
            }
            markdownRenderer.setMarkdown(
                assistantText,
                prepareMarkdown(formatAnswer(exchange.assistantText)),
            )
            messagesContainer.addView(
                dialogCard(
                    sender = "WRISTMIND",
                    role = "ответ помощника",
                    value = assistantText,
                    accent = Color.rgb(174, 139, 255),
                    isUser = false,
                ),
                matchWidth().apply { topMargin = dp(10) },
            )
        }
    }

    private fun showChatPicker() {
        val chats = chatStore.listChats()
        val dialog = Dialog(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(18))
            background = rounded(Color.rgb(18, 21, 36), dp(26), Color.rgb(75, 67, 117))
        }
        root.addView(
            textView(
                "Ваши диалоги",
                23f,
                Color.WHITE,
                Typeface.BOLD,
                Gravity.START,
            ),
            matchWidth(),
        )
        root.addView(
            textView(
                "Нажмите, чтобы открыть. Удерживайте диалог, чтобы удалить",
                13f,
                Color.rgb(154, 162, 190),
                Typeface.NORMAL,
                Gravity.START,
            ),
            matchWidth().apply { topMargin = dp(5) },
        )
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        chats.forEach { chat ->
            val selected = chat.id == chatStore.activeChatId()
            val item = button(
                if (chat.preview.isBlank()) chat.title else "${chat.title}\n${chat.preview.take(90)}",
                if (selected) Color.rgb(52, 43, 86) else Color.rgb(28, 32, 50),
                if (selected) Color.rgb(221, 210, 255) else Color.rgb(222, 226, 242),
            ).apply {
                textSize = 14f
                gravity = Gravity.START or Gravity.CENTER_VERTICAL
                maxLines = 3
                minHeight = dp(68)
                setPadding(dp(17), dp(10), dp(17), dp(10))
                this.background = rounded(
                    if (selected) Color.rgb(52, 43, 86) else Color.rgb(28, 32, 50),
                    dp(19),
                    if (selected) Color.rgb(143, 111, 231) else Color.rgb(52, 58, 81),
                )
                setOnClickListener {
                    chatStore.setActiveChat(chat.id)
                    renderChat()
                    syncChatToWatch()
                    dialog.dismiss()
                }
                setOnLongClickListener {
                    showDeleteChatDialog(chat.id, chat.title, dialog)
                    true
                }
            }
            list.addView(item, matchWidth().apply { topMargin = dp(9) })
        }
        val listScroll = ScrollView(this).apply {
            isFillViewport = false
            addView(list)
        }
        root.addView(
            listScroll,
            matchWidth(dp(360)).apply { topMargin = dp(12) },
        )
        val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.addView(
            button("Закрыть", Color.rgb(31, 35, 53), Color.rgb(190, 196, 218)).apply {
                setOnClickListener { dialog.dismiss() }
            },
            LinearLayout.LayoutParams(0, dp(54), 1f),
        )
        actions.addView(
            button("+ Новый чат", COLOR_ACCENT, Color.WHITE).apply {
                setOnClickListener {
                    chatStore.createChat()
                    renderChat()
                    syncChatToWatch()
                    dialog.dismiss()
                }
            },
            LinearLayout.LayoutParams(0, dp(54), 1.35f).apply { leftMargin = dp(9) },
        )
        root.addView(actions, matchWidth().apply { topMargin = dp(14) })
        dialog.setContentView(root)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
        dialog.window?.attributes = dialog.window?.attributes?.apply { dimAmount = 0.72f }
        dialog.show()
        dialog.window?.setLayout(
            (resources.displayMetrics.widthPixels * 0.92f).toInt(),
            ViewGroup.LayoutParams.WRAP_CONTENT,
        )
    }

    private fun showDeleteChatDialog(chatId: Long, chatTitle: String, picker: Dialog) {
        val dialog = Dialog(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(20), dp(22), dp(20))
            background = rounded(Color.rgb(22, 23, 38), dp(24), Color.rgb(112, 61, 77))
        }
        root.addView(
            textView(
                "Удалить диалог?",
                22f,
                Color.WHITE,
                Typeface.BOLD,
                Gravity.START,
            ),
            matchWidth(),
        )
        root.addView(
            textView(
                "\"${chatTitle.take(80)}\"\nВся история этого диалога будет удалена.",
                15f,
                Color.rgb(203, 207, 225),
                Typeface.NORMAL,
                Gravity.START,
            ),
            matchWidth().apply { topMargin = dp(10) },
        )
        val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.addView(
            button("Отмена", Color.rgb(38, 41, 59), Color.rgb(211, 216, 234)).apply {
                setOnClickListener { dialog.dismiss() }
            },
            LinearLayout.LayoutParams(0, dp(54), 1f),
        )
        actions.addView(
            button("Удалить", Color.rgb(172, 57, 79), Color.WHITE).apply {
                setOnClickListener {
                    if (chatStore.deleteChat(chatId)) {
                        renderChat()
                        syncChatToWatch()
                    }
                    dialog.dismiss()
                    picker.dismiss()
                }
            },
            LinearLayout.LayoutParams(0, dp(54), 1f).apply { leftMargin = dp(9) },
        )
        root.addView(actions, matchWidth().apply { topMargin = dp(18) })
        dialog.setContentView(root)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        dialog.window?.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
        dialog.window?.attributes = dialog.window?.attributes?.apply { dimAmount = 0.8f }
        dialog.show()
        dialog.window?.setLayout(
            (resources.displayMetrics.widthPixels * 0.86f).toInt(),
            ViewGroup.LayoutParams.WRAP_CONTENT,
        )
    }

    private fun syncChatToWatch() {
        val bridgeEnabled = getSharedPreferences("wristmind_service", MODE_PRIVATE)
            .getBoolean("bridge_enabled", false)
        if (bridgeEnabled) sendServiceAction(VoiceAssistantService.ACTION_SYNC_CHAT)
    }

    private fun renderState(state: String, message: String?) {
        val stateChanged = lastRenderedState != state
        lastRenderedState = state
        uiState = state
        orb.setMode(state)
        val copy = when (state) {
            "IDLE" -> Triple("Готов слушать", message ?: "Нажмите на часах или начните запись здесь", "Начать запись")
            "REC" -> Triple("Я внимательно слушаю", message ?: "Говорите свободно — запись идёт", "Остановить")
            "STOP" -> Triple("Запись сохранена", message ?: "Готовим аудио к отправке", "Подождите…")
            "SEND" -> Triple("Отправляю", message ?: "Аудио направляется на сервер", "Отправка…")
            "PROC" -> Triple("Думаю над ответом", message ?: "Распознаю речь и формирую ответ", "Обработка…")
            "READY" -> Triple("Ответ готов", message ?: "Короткая версия уже отправлена на часы", "Новый вопрос")
            "ERROR" -> Triple("Что-то пошло не так", message ?: "Сбросьте ошибку и запишите вопрос заново", "Сбросить")
            else -> Triple("Подключите Bip 6", "Один раз запустите фоновую связь с часами", "Начать запись")
        }
        headline.text = copy.first
        status.text = copy.second
        actionButton.text = copy.third
        actionButton.isEnabled = state in setOf("IDLE", "REC", "READY", "ERROR")
        actionButton.alpha = if (actionButton.isEnabled) 1f else 0.58f
        actionButton.background = rounded(
            when (state) {
                "REC" -> Color.rgb(227, 78, 99)
                "ERROR" -> Color.rgb(164, 103, 56)
                else -> COLOR_ACCENT
            },
            dp(24),
        )
        connectionBadge.text = when {
            watchConnected -> "●  BIP 6 В СЕТИ"
            serverConnected -> "●  VPS В СЕТИ"
            bridgeActive -> "●  ПОДКЛЮЧЕНИЕ"
            else -> "●  СВЯЗЬ ВЫКЛЮЧЕНА"
        }
        connectionBadge.setTextColor(
            when {
                watchConnected -> Color.rgb(107, 232, 184)
                serverConnected -> Color.rgb(120, 170, 255)
                bridgeActive -> Color.rgb(255, 177, 92)
                else -> COLOR_SECONDARY
            },
        )
        bridgeButton.text = when {
            watchConnected -> "МАРШРУТ ПОДКЛЮЧЕНИЯ\nBip 6  →  Zepp  →  VPS  →  телефон\nВсе звенья отвечают"
            serverConnected -> "МАРШРУТ ПОДКЛЮЧЕНИЯ\nТелефон  ↔  VPS — готово\nОткройте WristMind на Bip 6"
            bridgeActive -> "МАРШРУТ ПОДКЛЮЧЕНИЯ\nТелефон  →  VPS\nПроверяю сервер…"
            else -> "ВКЛЮЧИТЬ СВЯЗЬ\nТелефон  →  VPS  →  Zepp  →  Bip 6"
        }
        bridgeButton.isEnabled = !bridgeActive
        bridgeButton.alpha = if (bridgeActive) 0.82f else 1f
        actionButton.visibility = if (bridgeActive || state != "OFFLINE") View.VISIBLE else View.GONE
        if (stateChanged) {
            headline.alpha = 0.45f
            status.alpha = 0.35f
            headline.animate().alpha(1f).setDuration(220).start()
            status.animate().alpha(1f).setDuration(320).start()
            orb.scaleX = 0.96f
            orb.scaleY = 0.96f
            orb.animate().scaleX(1f).scaleY(1f).setDuration(260).start()
        }
    }

    private fun onPrimaryAction() {
        when (uiState) {
            "IDLE", "READY" -> sendServiceAction(VoiceAssistantService.ACTION_START_RECORDING)
            "REC" -> sendServiceAction(VoiceAssistantService.ACTION_STOP_RECORDING)
            "ERROR" -> sendServiceAction(VoiceAssistantService.ACTION_RESET)
        }
    }

    private fun requestPermissionsAndStart() {
        val permissions = buildList {
            add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
            if (Build.VERSION.SDK_INT >= 31) {
                add(Manifest.permission.BLUETOOTH_CONNECT)
                add(Manifest.permission.BLUETOOTH_ADVERTISE)
            }
        }.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (permissions.isEmpty()) startBridge() else requestPermissions(permissions.toTypedArray(), 100)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100 && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            startBridge()
        } else {
            renderState("ERROR", "Разрешите доступ к микрофону, Bluetooth и уведомлениям")
        }
    }

    private fun startBridge() {
        startForegroundService(
            Intent(this, VoiceAssistantService::class.java)
                .setAction(VoiceAssistantService.ACTION_START_BRIDGE),
        )
        requestBatteryExemptionOnce()
    }

    private fun sendServiceAction(action: String) {
        startForegroundService(Intent(this, VoiceAssistantService::class.java).setAction(action))
    }

    private fun requestBatteryExemptionOnce() {
        if (Build.VERSION.SDK_INT < 23) return
        val preferences = getSharedPreferences("wristmind_ui", MODE_PRIVATE)
        if (preferences.getBoolean("battery_prompt_shown", false)) return
        val powerManager = getSystemService(PowerManager::class.java)
        if (powerManager.isIgnoringBatteryOptimizations(packageName)) return
        preferences.edit().putBoolean("battery_prompt_shown", true).apply()
        runCatching {
            startActivity(
                Intent(
                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName"),
                ),
            )
        }
    }

    private fun requestPocoAutostartOnce() {
        if (!Build.MANUFACTURER.contains("xiaomi", ignoreCase = true)) return
        if (Build.VERSION.SDK_INT >= 23) {
            val powerManager = getSystemService(PowerManager::class.java)
            if (!powerManager.isIgnoringBatteryOptimizations(packageName)) return
        }
        val preferences = getSharedPreferences("wristmind_ui", MODE_PRIVATE)
        if (preferences.getBoolean("poco_autostart_prompt_shown", false)) return
        val intent = Intent().setComponent(
            ComponentName(
                "com.miui.securitycenter",
                "com.miui.permcenter.autostart.AutoStartManagementActivity",
            ),
        )
        runCatching {
            startActivity(intent)
            preferences.edit().putBoolean("poco_autostart_prompt_shown", true).apply()
        }
    }

    private fun formatAnswer(raw: String): String {
        val clean = raw.trim().replace(Regex("""[ \t]+\n"""), "\n")
        if (clean.contains("\n\n") || clean.length < 220) return clean
        val sentences = clean.split(Regex("""(?<=[.!?])\s+"""))
        if (sentences.size < 4) return clean
        return sentences.chunked(2).joinToString("\n\n") { it.joinToString(" ") }
    }

    private fun prepareMarkdown(raw: String): String {
        return raw
            .replace(Regex("""\\\[\s*"""), "\n\$\$\n")
            .replace(Regex("""\s*\\\]"""), "\n\$\$\n")
            .replace(Regex("""\\\(\s*"""), "\$\$")
            .replace(Regex("""\s*\\\)"""), "\$\$")
            .replace(Regex("""(?<!\$)\$([^$\n]+)\$(?!\$)""")) {
                "\$\$${it.groupValues[1]}\$\$"
            }
            .trim()
    }

    private fun textView(text: String, size: Float, color: Int, style: Int, gravity: Int) =
        TextView(this).apply {
            this.text = text
            textSize = size
            setTextColor(color)
            typeface = Typeface.create("sans-serif", style)
            this.gravity = gravity
        }

    private fun sectionLabel(text: String) =
        textView(text, 11f, Color.rgb(126, 134, 162), Typeface.BOLD, Gravity.START).apply {
            letterSpacing = 0.15f
        }

    private fun button(text: String, color: Int, textColor: Int) = Button(this).apply {
        this.text = text
        textSize = 16f
        setTextColor(textColor)
        isAllCaps = false
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        background = rounded(color, dp(24))
        stateListAnimator = null
    }

    private fun rounded(color: Int, radius: Int, strokeColor: Int? = null) =
        GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = radius.toFloat()
            setColor(color)
            if (strokeColor != null) setStroke(dp(1), strokeColor)
        }

    private fun matchWidth(height: Int = ViewGroup.LayoutParams.WRAP_CONTENT) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height)

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private val COLOR_BACKGROUND = Color.rgb(12, 15, 28)
        private val COLOR_ACCENT = Color.rgb(112, 86, 214)
        private val COLOR_SECONDARY = Color.rgb(145, 153, 181)
    }
}
