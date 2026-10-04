package dev.wristmind.wear

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import android.os.SystemClock
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalScrollCaptureInProgress
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.Card
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.CompactButton
import androidx.wear.compose.material3.FilledTonalIconButton
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.touchTargetAwareSize
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import dev.wristmind.core.Chat
import kotlinx.coroutines.delay

private const val ROUTE_PAIR = "pair"
private const val ROUTE_CHAT = "chat"
private const val ROUTE_HISTORY = "history"
private const val ROUTE_MODES = "modes"
private const val ROUTE_ANSWER = "answer"
private const val ROUTE_DRAFT = "draft"
private const val ROUTE_SOURCE = "source"
private const val QUICK_CHAT_MODE_NAME = "Быстрый чат"
private const val SERVER_STATUS_REFRESH_MS = 10_000L

private object HistoryLayout {
    val controlHeight = 48.dp
    val quickChatVisualSize = controlHeight
    val chatCardHeight = 52.dp
}

private fun Chat.typeIcon(): ImageVector =
    if (modeName == QUICK_CHAT_MODE_NAME) WearIcons.QuickChat else WearIcons.Chat

private fun Chat.typeDescription(): String =
    if (modeName == QUICK_CHAT_MODE_NAME) "Быстрый чат" else "Обычный чат"

private fun Chat.modeBadge(): String = modeName.trim().take(3).uppercase()

@Composable
fun WristMindWearApp(
    screenWakeController: ScreenWakeController,
    launchSystemSpeech: ((String?) -> Unit) -> Unit,
    vm: WearViewModel = viewModel(),
) {
    val state by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.operationActive) {
        screenWakeController.setOperationActive(state.operationActive)
    }
    LaunchedEffect(state.draft) {
        if (state.draft.isNotEmpty()) screenWakeController.onInteraction()
    }
    val startVoiceInput: () -> Unit = {
        val draftBeforeSpeech = state.draft
        screenWakeController.setOperationActive(true)
        launchSystemSpeech { transcript ->
            screenWakeController.setOperationActive(false)
            transcript?.let { vm.applyRecognizedSpeech(draftBeforeSpeech, it) }
        }
    }
    WristMindWearTheme {
        AppScaffold(timeText = {}) {
            val navController = rememberSwipeDismissableNavController()
            val chatListState = key(state.activeChatId) {
                rememberTransformingLazyColumnState()
            }
            var chatComposerHeightPx by remember { mutableIntStateOf(0) }
            val startDestination = remember { if (state.paired) ROUTE_CHAT else ROUTE_PAIR }
            LaunchedEffect(state.paired) {
                if (state.paired && navController.currentDestination?.route == ROUTE_PAIR) {
                    navController.navigate(ROUTE_CHAT) {
                        popUpTo(ROUTE_PAIR) { inclusive = true }
                        launchSingleTop = true
                    }
                }
                if (!state.paired && navController.currentDestination?.route != ROUTE_PAIR) {
                    navController.navigate(ROUTE_PAIR) {
                        popUpTo(navController.graph.id) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            }
            SwipeDismissableNavHost(navController, startDestination) {
                composable(ROUTE_PAIR) { PairScreen(state, vm) }
                composable(ROUTE_CHAT) {
                    ChatScreen(
                        state = state,
                        listState = chatListState,
                        composerHeightPx = chatComposerHeightPx,
                        onComposerHeightChanged = { chatComposerHeightPx = it },
                        onHistory = { navController.navigate(ROUTE_HISTORY); Unit },
                        onEditDraft = { navController.navigate(ROUTE_DRAFT); Unit },
                        onCancelAnswer = vm::cancelCurrentAnswer,
                        onAnswer = { id ->
                            vm.selectAnswer(id)
                            navController.navigate(ROUTE_ANSWER)
                        },
                        onOpenSource = { navController.navigate(ROUTE_SOURCE); Unit },
                    )
                }
                composable(ROUTE_DRAFT) {
                    DraftInputScreen(
                        draft = state.draft,
                        answerSearchMode = state.answerSearchMode,
                        onDraftChange = vm::updateDraft,
                        onToggleWebSearch = vm::toggleWebSearch,
                        onVoice = startVoiceInput,
                        onDone = {
                            // updateDraft runs synchronously before this callback. The outbox
                            // clears a non-empty draft locally before starting its HTTP request.
                            vm.sendDraft()
                            navController.popBackStack()
                            Unit
                        },
                    )
                }
                composable(ROUTE_HISTORY) {
                    HistoryScreen(
                        state = state,
                        onNewChat = { navController.navigate(ROUTE_MODES); Unit },
                        onQuickChat = {
                            vm.createQuickChat {
                                navController.popBackStack(ROUTE_CHAT, false)
                            }
                        },
                        onChat = { id ->
                            vm.selectChat(id)
                            navController.popBackStack(ROUTE_CHAT, false)
                            Unit
                        },
                        onDeleteChat = vm::deleteChat,
                        onServerStatusCheck = vm::refreshServerConnectionStatus,
                    )
                }
                composable(ROUTE_MODES) {
                    ModePickerScreen(
                        state = state,
                        onMode = { id ->
                            vm.createChat(id) {
                                navController.popBackStack(ROUTE_CHAT, false)
                            }
                        },
                    )
                }
                // This is Compose state, so the full answer updates with every SSE delta.
                composable(ROUTE_ANSWER) { FullAnswerScreen(selectedAnswerContent(state)) }
                composable(ROUTE_SOURCE) {
                    val candidate = state.sourceCandidates.firstOrNull()
                    if (candidate != null) {
                        FullAnswerScreen(
                            answer = candidate.content.ifBlank { candidate.preview },
                            title = candidate.title,
                            truncationNote = candidate.truncated,
                            footer = {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Button(onClick = {
                                        vm.saveSourceCandidate(candidate.id)
                                        navController.popBackStack()
                                    }) { Text("Добавить") }
                                    CompactButton(onClick = {
                                        vm.dismissSourceCandidate(candidate.id)
                                        navController.popBackStack()
                                    }) { Text("Отменить") }
                                }
                            },
                        )
                    } else navController.popBackStack()
                }
            }
        }
    }
}

@Composable
private fun PairScreen(state: WearState, vm: WearViewModel) {
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    ScreenScaffold(
        scrollState = listState,
        scrollIndicator = wearScrollIndicator(listState),
    ) { contentPadding ->
        TransformingLazyColumn(
            state = listState,
            contentPadding = contentPadding,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item {
                Image(
                    painter = painterResource(R.drawable.ic_wristmind_wear),
                    contentDescription = null,
                    modifier = Modifier.size(52.dp).transformedHeight(this, transformationSpec),
                )
            }
            item {
                ListHeader(
                    modifier = Modifier
                        .fillMaxWidth()
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
            item {
                Text(
                    text = "Код из Настройки → Подключить устройство",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth(.82f)
                        .transformedHeight(this, transformationSpec),
                )
            }
            item {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding)
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    ),
                ) {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        if (state.pairCode.isEmpty()) {
                            Text(
                                "000000",
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .45f),
                            )
                        }
                        BasicTextField(
                            value = state.pairCode,
                            onValueChange = vm::setPairCode,
                            textStyle = MaterialTheme.typography.titleMedium.merge(
                                TextStyle(
                                    color = MaterialTheme.colorScheme.onSurface,
                                    textAlign = TextAlign.Center,
                                ),
                            ),
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.NumberPassword,
                                imeAction = ImeAction.Done,
                            ),
                            keyboardActions = KeyboardActions(onDone = { vm.pair() }),
                            singleLine = true,
                            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
            item {
                Button(
                    onClick = vm::pair,
                    enabled = !state.loading && state.pairCode.length >= 6,
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding)
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                    label = {
                        if (state.loading) CircularProgressIndicator(Modifier.size(20.dp))
                        else Text("Подключить")
                    },
                )
            }
            state.error?.let { error ->
                item {
                    Text(
                        error,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth(.82f)
                            .transformedHeight(this, transformationSpec),
                    )
                }
            }
        }
    }
}

@Composable
private fun HistoryScreen(
    state: WearState,
    onNewChat: () -> Unit,
    onQuickChat: () -> Unit,
    onChat: (String) -> Unit,
    onDeleteChat: (String) -> Unit,
    onServerStatusCheck: () -> Unit,
) {
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    var deleteActionChatId by remember { mutableStateOf<String?>(null) }
    var deleteActionBounds by remember { mutableStateOf<Rect?>(null) }
    LaunchedEffect(listState.isScrollInProgress) {
        if (listState.isScrollInProgress) deleteActionChatId = null
    }
    LaunchedEffect(Unit) {
        while (true) {
            onServerStatusCheck()
            delay(SERVER_STATUS_REFRESH_MS)
        }
    }
    ScreenScaffold(
        scrollState = listState,
        scrollIndicator = wearScrollIndicator(listState),
    ) { contentPadding ->
        TransformingLazyColumn(
            state = listState,
            contentPadding = contentPadding,
            modifier = Modifier.pointerInput(deleteActionChatId, deleteActionBounds) {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent()
                        if (deleteActionChatId != null && event.changes.any { it.pressed }) {
                            val position = event.changes.first().position
                            if (deleteActionBounds?.contains(position) != true) deleteActionChatId = null
                        }
                    }
                }
            },
        ) {
            item {
                ListHeader(
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(
                            ListHeaderDefaults.minimumTopListContentPadding,
                            ListHeaderDefaults.minimumBottomListContentPadding,
                        )
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                ) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("История")
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(if (state.vpsConnected) Color(0xFF35D07F) else MaterialTheme.colorScheme.error)
                                .semantics {
                                    contentDescription = if (state.vpsConnected) "Сервер доступен" else "Нет доступа к серверу"
                                },
                        )
                        if (state.fallbackActive) {
                            Box(
                                modifier = Modifier
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(Color(0xFFF4B942))
                                    .semantics {
                                        contentDescription = "Резервный режим, без сохранённых источников"
                                    },
                            )
                        }
                    }
                }
            }
            item {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Button(
                        onClick = {
                            deleteActionChatId = null
                            onNewChat()
                        },
                        modifier = Modifier
                            .weight(1f)
                            .height(HistoryLayout.controlHeight)
                            .transformedHeight(this@item, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec),
                        colors = ButtonDefaults.filledTonalButtonColors(),
                        icon = {
                            Icon(
                                WearIcons.Chat,
                                contentDescription = null,
                                modifier = Modifier.size(ButtonDefaults.IconSize),
                            )
                        },
                        label = { Text("Новый чат", maxLines = 1) },
                    )
                    FilledTonalIconButton(
                        onClick = {
                            deleteActionChatId = null
                            onQuickChat()
                        },
                        modifier = Modifier
                            .size(HistoryLayout.quickChatVisualSize)
                            .touchTargetAwareSize(HistoryLayout.controlHeight)
                            .transformedHeight(this@item, transformationSpec),
                    ) {
                        Icon(WearIcons.QuickChat, contentDescription = "Быстрый чат")
                    }
                }
            }
            items(state.chats, key = { it.id }) { chat ->
                if (deleteActionChatId == chat.id) {
                    Button(
                        onClick = {
                            deleteActionChatId = null
                            onDeleteChat(chat.id)
                        },
                        label = { Text("Удалить") },
                        icon = {
                            Icon(
                                WearIcons.Delete,
                                contentDescription = null,
                                modifier = Modifier.size(ButtonDefaults.IconSize),
                            )
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .onGloballyPositioned { deleteActionBounds = it.boundsInRoot() }
                            .height(HistoryLayout.chatCardHeight)
                            .transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.error,
                            contentColor = MaterialTheme.colorScheme.onError,
                        ),
                    )
                } else {
                    Button(
                        onClick = {
                            deleteActionChatId = null
                            onChat(chat.id)
                        },
                        onLongClick = { deleteActionChatId = chat.id },
                        onLongClickLabel = "Показать удаление",
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(HistoryLayout.chatCardHeight)
                            .transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec),
                        colors = if (chat.id == state.activeChatId) {
                            ButtonDefaults.filledVariantButtonColors()
                        } else {
                            ButtonDefaults.filledTonalButtonColors()
                        },
                        label = {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(ButtonDefaults.IconSpacing),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(
                                    modifier = Modifier
                                        .clip(MaterialTheme.shapes.small)
                                        .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                                        .padding(horizontal = 4.dp, vertical = 2.dp),
                                ) {
                                    Text(
                                        chat.modeBadge(),
                                        maxLines = 1,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                                Text(
                                    chat.title,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        },
                    )
                }
            }
            if (state.chats.isEmpty()) {
                item {
                    Text(
                        "Здесь появятся ваши чаты",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                    )
                }
            }
        }
    }
}

@Composable
private fun ModePickerScreen(state: WearState, onMode: (String) -> Unit) {
    val visibleModes = state.modes.filterNot { it.hiddenOnWatch }
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    ScreenScaffold(
        scrollState = listState,
        scrollIndicator = wearScrollIndicator(listState),
    ) { contentPadding ->
        TransformingLazyColumn(state = listState, contentPadding = contentPadding) {
            item {
                ListHeader(
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(
                            ListHeaderDefaults.minimumTopListContentPadding,
                            ListHeaderDefaults.minimumBottomListContentPadding,
                        )
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                ) {
                    Text("Выберите режим")
                }
            }
            items(visibleModes, key = { it.id }) { mode ->
                Button(
                    onClick = { if (!state.creatingChat) onMode(mode.id) },
                    enabled = !state.creatingChat,
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding)
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                    colors = ButtonDefaults.filledTonalButtonColors(),
                    icon = {
                        Icon(
                            WearIcons.Chat,
                            contentDescription = null,
                            modifier = Modifier.size(ButtonDefaults.IconSize),
                        )
                    },
                    label = {
                        Text(mode.name, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    },
                )
            }
            if (state.creatingChat) {
                item(key = "creating-chat") {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .size(28.dp)
                            .transformedHeight(this, transformationSpec),
                    )
                }
            }
            state.error?.let { error ->
                item(key = "mode-picker-error") {
                    Text(
                        text = error,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, transformationSpec),
                    )
                }
            }
            if (visibleModes.isEmpty()) {
                item {
                    Text(
                        "Создайте режим на сайте",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                    )
                }
            }
        }
    }
}

@Composable
private fun FullAnswerScreen(
    answer: String,
    title: String = "Ответ",
    truncationNote: Boolean = false,
    footer: (@Composable () -> Unit)? = null,
) {
    val blocks = remember(answer) { parseMarkdown(withoutSearchSources(answer)) }
    LaunchedEffect(answer) {
        val stripped = withoutSearchSources(answer)
        // A blank answer produces no blocks in the reader.
        WearAnswerTrace.log(
            "reader_render",
            "title_chars" to title.length,
            "raw_chars" to answer.length,
            "stripped_chars" to stripped.length,
            "blocks" to blocks.size,
            "empty_block" to blocks.isEmpty(),
        )
    }
    val listState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec()
    ScreenScaffold(
        scrollState = listState,
        scrollIndicator = wearScrollIndicator(listState),
    ) { contentPadding ->
        TransformingLazyColumn(state = listState, contentPadding = contentPadding) {
            item {
                ListHeader(
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumVerticalContentPadding(
                            ListHeaderDefaults.minimumTopListContentPadding,
                            ListHeaderDefaults.minimumBottomListContentPadding,
                        )
                        .transformedHeight(this, transformationSpec),
                    transformation = SurfaceTransformation(transformationSpec),
                ) {
                    Text(title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            items(blocks) { block ->
                Box(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                ) {
                    MarkdownBlockView(block)
                }
            }
            if (truncationNote) item {
                Text("Показана первая часть большого материала", modifier = Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall)
            }
            if (footer != null) item { footer() }
            item(key = "answer-bottom-space") {
                Spacer(Modifier.fillMaxWidth().height(40.dp))
            }
        }
    }
}

@Composable
private fun wearScrollIndicator(
    state: androidx.wear.compose.foundation.lazy.TransformingLazyColumnState,
): (@Composable androidx.compose.foundation.layout.BoxScope.() -> Unit)? =
    if (LocalScrollCaptureInProgress.current) {
        null
    } else {
        { ScrollIndicator(state = state) }
    }

internal fun stageLabel(stage: ProcessingStage) = when (stage) {
    ProcessingStage.DISCONNECTED -> "Нет связи"
    ProcessingStage.READY -> "Готово"
    ProcessingStage.SENDING -> "Отправка"
    ProcessingStage.WAITING -> "Запрос принят"
    ProcessingStage.CONTEXT -> "Контекст"
    ProcessingStage.ROUTING -> "Выбор способа ответа"
    ProcessingStage.USING_CHAT_SOURCE -> "Источник чата"
    ProcessingStage.FRAMING_REQUEST -> "Уточнение задачи"
    ProcessingStage.SOURCE_INTENT -> "Подбор материала"
    ProcessingStage.SEARCH_QUERY -> "Уточнение запроса"
    ProcessingStage.SEARCHING -> "Поиск источников"
    ProcessingStage.REVIEWING_SOURCES -> "Сверка найденного"
    ProcessingStage.OPENING_SOURCE -> "Чтение источника"
    ProcessingStage.EVALUATING_SOURCE -> "Проверка материала"
    ProcessingStage.EXTRACTING_SOURCE -> "Выделение фрагмента"
    ProcessingStage.SAVING_SOURCE -> "Сохранение в чат"
    ProcessingStage.SEARCH_NO_RESULTS -> "Источники не найдены"
    ProcessingStage.SEARCH_UNAVAILABLE -> "Поиск недоступен"
    ProcessingStage.RESEARCH_DRAFTING -> "Подготовка решения"
    ProcessingStage.RESEARCH_CHECKING -> "Проверка ответа"
    ProcessingStage.RESEARCH_REFINING -> "Улучшение ответа"
    ProcessingStage.GENERATING -> "Формирование ответа"
    ProcessingStage.FALLBACK_GENERATING -> "Резервный ответ"
    ProcessingStage.COMPLETE -> "Готово"
    ProcessingStage.ERROR -> "Ошибка"
}
