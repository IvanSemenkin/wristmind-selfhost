package dev.wristmind.wear

import android.os.SystemClock
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.StartOffsetType
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.TextFieldLineLimits
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.LocalScrollCaptureInProgress
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnItemScope
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.FilledIconButton
import androidx.wear.compose.material3.FilledTonalIconButton
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.IconButtonDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.touchTargetAwareSize
import androidx.wear.compose.ui.tooling.preview.WearPreviewDevices
import androidx.wear.compose.ui.tooling.preview.WearPreviewFontScales
import dev.wristmind.core.ChatMessage
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged

private object ChatLayout {
    const val messageWidthFraction = .84f
    val historyVisualSize = 32.dp
    val historyTouchTargetSize = 40.dp
    val historyVisualLift = 2.dp
}

private data class ChatContentMarker(
    val messageCount: Int,
    val pendingQuestionVisible: Boolean,
    val streamingAnswerVisible: Boolean,
)

internal fun pendingServerUserIndex(
    messages: List<ChatMessage>,
    pendingQuestion: String,
    baseMessageId: String?,
): Int? {
    if (pendingQuestion.isBlank()) return null
    val baseIndex = baseMessageId?.let { id -> messages.indexOfLast { it.id == id } } ?: -1
    val contentMatch = (baseIndex + 1 until messages.size).lastOrNull { index ->
        messages[index].role == "user" && messages[index].content == pendingQuestion
    }
    if (contentMatch != null) return contentMatch

    // A state_changed push can refresh messages while the POST is still being
    // reconciled locally. The authoritative list then ends in the new user
    // message plus its empty streaming assistant placeholder. Treat that pair
    // as the accepted pending turn even if the baseline/content comparison was
    // invalidated by a fallback-cache migration. Otherwise the server question,
    // placeholder and optimistic local question are all drawn at once.
    val assistantIndex = messages.lastIndex
    val userIndex = assistantIndex - 1
    val assistant = messages.getOrNull(assistantIndex)
    val user = messages.getOrNull(userIndex)
    return userIndex.takeIf {
        userIndex > baseIndex &&
            user?.role == "user" &&
            assistant?.role == "assistant" &&
            assistant.status == "streaming" &&
            assistant.content.isBlank()
    }
}

@Composable
internal fun ChatScreen(
    state: WearState,
    listState: TransformingLazyColumnState,
    composerHeightPx: Int,
    onComposerHeightChanged: (Int) -> Unit,
    onHistory: () -> Unit,
    onEditDraft: () -> Unit,
    onCancelAnswer: () -> Unit,
    onAnswer: (String) -> Unit,
    onOpenSource: () -> Unit,
) {
    // A message list can arrive after navigation has switched chats. Never let such a
    // response render into the newly opened chat, even for a single composition frame.
    val isCurrentContent = state.activeChatId != null && state.contentChatId == state.activeChatId
    val visibleMessages = if (state.messagesChatId == state.activeChatId) {
        state.messages.filterNot { it.role == "assistant" && it.status == "cancelled" && it.content.isBlank() }
    } else emptyList()
    // A background sync may load both the submitted user message and its assistant
    // placeholder before the SSE stream finishes. Match after the outbox baseline:
    // the final item is already the assistant, and earlier questions may have the
    // same text.
    val pendingUserIndex = if (isCurrentContent) {
        pendingServerUserIndex(visibleMessages, state.pendingQuestion, state.pendingBaseMessageId)
    } else null
    val serverAnswerIndex = pendingUserIndex?.plus(1)?.takeIf { index ->
        visibleMessages.getOrNull(index)?.role == "assistant"
    }
    val localAnswer = if (isCurrentContent) state.streamingAnswer else ""
    val serverAnswer = serverAnswerIndex?.let(visibleMessages::get)
    val useLocalAnswer = localAnswer.isNotBlank() &&
        (serverAnswer == null || localAnswer.length > serverAnswer.content.length)
    val renderedMessages = visibleMessages.filterIndexed { index, _ ->
        index != serverAnswerIndex || (serverAnswer?.content?.isNotBlank() == true && !useLocalAnswer)
    }
    val visiblePendingQuestion = if (isCurrentContent && pendingUserIndex == null) {
        state.pendingQuestion
    } else {
        ""
    }
    val visibleStreamingAnswer = if (useLocalAnswer) localAnswer else ""
      val awaitingFirstToken = isCurrentContent && state.stage in setOf(
          ProcessingStage.SENDING,
          ProcessingStage.WAITING,
          ProcessingStage.CONTEXT,
          ProcessingStage.ROUTING,
          ProcessingStage.USING_CHAT_SOURCE,
          ProcessingStage.FRAMING_REQUEST,
          ProcessingStage.SOURCE_INTENT,
          ProcessingStage.SEARCH_QUERY,
          ProcessingStage.SEARCHING,
          ProcessingStage.REVIEWING_SOURCES,
          ProcessingStage.OPENING_SOURCE,
          ProcessingStage.EVALUATING_SOURCE,
          ProcessingStage.EXTRACTING_SOURCE,
          ProcessingStage.SAVING_SOURCE,
          ProcessingStage.SEARCH_NO_RESULTS,
          ProcessingStage.SEARCH_UNAVAILABLE,
          ProcessingStage.RESEARCH_DRAFTING,
          ProcessingStage.RESEARCH_CHECKING,
          ProcessingStage.RESEARCH_REFINING,
          ProcessingStage.GENERATING,
          ProcessingStage.FALLBACK_GENERATING,
    ) && visibleStreamingAnswer.isBlank() && serverAnswer?.content.isNullOrBlank()
    val density = LocalDensity.current
    val renderedCount = renderedMessages.size +
        listOf(visiblePendingQuestion, visibleStreamingAnswer).count(String::isNotBlank) +
        if (awaitingFirstToken) 1 else 0

    val contentMarker = ChatContentMarker(
        messageCount = renderedMessages.size,
        pendingQuestionVisible = visiblePendingQuestion.isNotBlank(),
        streamingAnswerVisible = visibleStreamingAnswer.isNotBlank(),
    )
    var previousContentMarker by remember { mutableStateOf(contentMarker) }
    LaunchedEffect(contentMarker) {
        val previous = previousContentMarker
        previousContentMarker = contentMarker
        val newContentAppeared =
            contentMarker.messageCount > previous.messageCount ||
                (!previous.pendingQuestionVisible && contentMarker.pendingQuestionVisible) ||
                (!previous.streamingAnswerVisible && contentMarker.streamingAnswerVisible)
        if (newContentAppeared && renderedCount > 0) {
            listState.animateScrollToItem(renderedCount - 1)
        }
    }
    val layoutDirection = LocalLayoutDirection.current
    val safeDrawingPadding = WindowInsets.safeDrawing.asPaddingValues()
    val composerHeight = with(density) { composerHeightPx.toDp() }
    BoxWithConstraints(Modifier.fillMaxSize().imePadding()) {
        // The corner of an axis-aligned rectangle needs extra clearance on a round display.
        // This is the inset of the largest square that fits fully inside the screen circle.
        val circularCornerInset = minOf(maxWidth, maxHeight) * 0.1464466f
        ScreenScaffold(
            scrollState = listState,
            timeText = {},
            scrollIndicator = chatScrollIndicator(listState),
        ) { scaffoldPadding ->
            val adaptivePadding = PaddingValues(
                start = maxOf(
                    scaffoldPadding.calculateStartPadding(layoutDirection),
                    safeDrawingPadding.calculateStartPadding(layoutDirection),
                ),
                top = maxOf(
                    scaffoldPadding.calculateTopPadding(),
                    safeDrawingPadding.calculateTopPadding(),
                ),
                end = maxOf(
                    scaffoldPadding.calculateEndPadding(layoutDirection),
                    safeDrawingPadding.calculateEndPadding(layoutDirection),
                ),
                bottom = maxOf(
                    scaffoldPadding.calculateBottomPadding(),
                    safeDrawingPadding.calculateBottomPadding(),
                ),
            )
            if (state.activeChatId == null && !state.loading) {
                EmptyChat()
            } else {
                TransformingLazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(
                        start = adaptivePadding.calculateStartPadding(layoutDirection),
                        // Keep the first message clear of the floating corner action without
                        // introducing a separate full-width header.
                        top = maxOf(
                            adaptivePadding.calculateTopPadding(),
                            circularCornerInset +
                                ChatLayout.historyTouchTargetSize +
                                ButtonDefaults.IconSpacing,
                        ),
                        end = adaptivePadding.calculateEndPadding(layoutDirection),
                        bottom = maxOf(
                            adaptivePadding.calculateBottomPadding(),
                            composerHeight,
                        ),
                    ),
                    verticalArrangement = Arrangement.spacedBy(ButtonDefaults.IconSpacing),
                ) {
                    items(renderedMessages, key = { it.id }) { message ->
                        MessageBubble(message, onAnswer)
                    }
                    if (visiblePendingQuestion.isNotBlank()) {
                        item(key = "pending-question") {
                            MessageBubble(
                                text = visiblePendingQuestion,
                                user = true,
                                preview = false,
                                canOpenFullAnswer = false,
                                onClick = {},
                            )
                        }
                    }
                    if (visibleStreamingAnswer.isNotBlank()) {
                        item(key = "streaming-answer") {
                            MessageBubble(
                                text = visibleStreamingAnswer,
                                user = false,
                                preview = true,
                                canOpenFullAnswer = true,
                                openBeforeOverflow = true,
                                onClick = { onAnswer(STREAMING_ANSWER_ID) },
                            )
                        }
                        } else if (awaitingFirstToken) {
                          item(key = "generation-indicator") {
                            GenerationBubble(state.stage, state.progressOrdinal)
                        }
                    }
                }
            }
            if (state.loading && state.activeChatId == null) {
                CircularProgressIndicator(Modifier.size(32.dp).align(Alignment.Center))
            }
            ChatTopAction(
                state = state,
                onHistory = onHistory,
                contentPadding = adaptivePadding,
                circularCornerInset = circularCornerInset,
            )
        }
        // This layer is deliberately outside ScreenScaffold and TransformingLazyColumn:
        // scrolling messages must never transform, translate, or resize the composer.
        if (state.activeChatId != null) {
            ChatControls(
                state = state,
                onEditDraft = onEditDraft,
                onCancelAnswer = onCancelAnswer,
                contentPadding = safeDrawingPadding,
                onHeightChanged = onComposerHeightChanged,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .zIndex(1f),
            )
        }
        val sourceCandidate = state.sourceCandidates.firstOrNull()
        if (sourceCandidate != null && !state.operationActive) {
            SourceSavePrompt(
                onOpen = onOpenSource,
            )
        }
    }
}

@Composable
private fun ChatTopAction(
    state: WearState,
    onHistory: () -> Unit,
    contentPadding: PaddingValues,
    circularCornerInset: androidx.compose.ui.unit.Dp,
) {
    val layoutDirection = LocalLayoutDirection.current
    val topPadding = maxOf(
        contentPadding.calculateTopPadding(),
        circularCornerInset,
    )
    val startPadding = maxOf(
        contentPadding.calculateStartPadding(layoutDirection),
        circularCornerInset,
    )
    Box(
        Modifier
            .fillMaxWidth()
            .padding(start = startPadding, top = topPadding),
        contentAlignment = Alignment.TopStart,
    ) {
        Box(
            modifier = Modifier
                .size(ChatLayout.historyTouchTargetSize)
                .clickable(onClick = onHistory)
                .semantics {
                    contentDescription = "История и новый чат"
                if (state.stage == ProcessingStage.ERROR || state.error != null) {
                    stateDescription = "Ошибка"
                }
            },
            contentAlignment = Alignment.Center,
        ) {
            // The visual surface is small, while the 40 dp target stays practical without
            // reserving the oversized default icon-button area.
            Box(
                modifier = Modifier
                    .size(ChatLayout.historyVisualSize)
                    .offset(y = -ChatLayout.historyVisualLift)
                    .background(
                        MaterialTheme.colorScheme.surfaceContainerHigh.copy(alpha = .75f),
                        RoundedCornerShape(
                            topStart = 8.dp,
                            topEnd = 16.dp,
                            bottomEnd = 16.dp,
                            bottomStart = 16.dp,
                        ),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = WearIcons.History,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
                if (state.stage == ProcessingStage.ERROR || state.error != null) {
                    Box(
                        Modifier
                            .align(Alignment.TopEnd)
                            .size(7.dp)
                            .background(MaterialTheme.colorScheme.error, CircleShape),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyChat() {
    Column(
        Modifier.fillMaxSize().padding(horizontal = 34.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            WearIcons.Chat,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(36.dp),
        )
        Spacer(Modifier.height(8.dp))
        Text("Чатов пока нет", style = MaterialTheme.typography.titleMedium)
        Text(
            "Откройте историю и создайте чат",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun SourceSavePrompt(
    onOpen: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(top = 56.dp, end = 42.dp),
        contentAlignment = Alignment.TopEnd,
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .semantics {
                    contentDescription = "Открыть найденный материал"
                    role = Role.Button
                }
                .clickable(onClickLabel = "Открыть найденный материал", onClick = onOpen),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(24.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.secondaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    WearIcons.Search,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSecondaryContainer,
                    modifier = Modifier.size(16.dp),
                )
            }
        }
    }
}

@Composable
private fun ChatControls(
    state: WearState,
    onEditDraft: () -> Unit,
    onCancelAnswer: () -> Unit,
    contentPadding: PaddingValues,
    onHeightChanged: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val processing = state.stage.isProcessing()
    var lastStopTapAt by remember(state.activeChatId, processing) { mutableStateOf(0L) }
    Box(
        modifier = modifier
            .fillMaxWidth()
            .onSizeChanged { onHeightChanged(it.height) }
            .padding(bottom = contentPadding.calculateBottomPadding()),
        contentAlignment = Alignment.BottomCenter,
    ) {
        FilledTonalIconButton(
            onClick = {
                if (processing) {
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastStopTapAt <= 700L) {
                        lastStopTapAt = 0L
                        onCancelAnswer()
                    } else lastStopTapAt = now
                } else onEditDraft()
            },
            modifier = Modifier.touchTargetAwareSize(28.dp),
        ) {
            Icon(
                if (processing) WearIcons.Stop else WearIcons.Chat,
                contentDescription = if (processing) "Дважды нажмите, чтобы остановить ответ" else "Написать сообщение",
                modifier = Modifier.size(16.dp),
            )
        }
    }
}

@Composable
internal fun DraftInputScreen(
    draft: String,
    answerSearchMode: AnswerSearchMode,
    onDraftChange: (String) -> Unit,
    onToggleWebSearch: () -> Unit,
    onVoice: () -> Unit,
    onDone: () -> Unit,
) {
    val textFieldState = rememberTextFieldState(initialText = draft)
    val contentScrollState = androidx.compose.foundation.rememberScrollState()
    val focusRequester = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    val currentDraft by rememberUpdatedState(draft)
    val currentOnDraftChange by rememberUpdatedState(onDraftChange)
    val currentOnVoice by rememberUpdatedState(onVoice)
    val currentOnDone by rememberUpdatedState(onDone)
    var keyboardRequest by remember { mutableIntStateOf(0) }
    var textLayoutResult by remember { mutableStateOf<TextLayoutResult?>(null) }
    val openKeyboard: () -> Unit = {
        keyboardRequest += 1
    }

    LaunchedEffect(draft) {
        if (textFieldState.text.toString() != draft) {
            textFieldState.setTextAndPlaceCursorAtEnd(draft)
        }
    }
    LaunchedEffect(textFieldState) {
        snapshotFlow { textFieldState.text.toString() }
            .distinctUntilChanged()
            .collect { text ->
                if (text != currentDraft) currentOnDraftChange(text)
            }
    }
    LaunchedEffect(keyboardRequest) {
        if (keyboardRequest > 0) {
            focusRequester.requestFocus()
            withFrameNanos { }
            delay(80)
            keyboardController?.show()
        }
    }

    ScreenScaffold(timeText = {}) { scaffoldPadding ->
        val layoutDirection = LocalLayoutDirection.current
        val safeDrawingPadding = WindowInsets.safeDrawing.asPaddingValues()
        BoxWithConstraints(Modifier.fillMaxSize()) {
            // The largest axis-aligned square fully contained by a circle starts at
            // (1 - 1/sqrt(2)) / 2 of the diameter. Unlike rectangular window insets,
            // this also protects text near the curved top corners.
            val circularSafeInset = minOf(maxWidth, maxHeight) * 0.1464466f
            val startPadding = maxOf(
                scaffoldPadding.calculateStartPadding(layoutDirection),
                safeDrawingPadding.calculateStartPadding(layoutDirection),
                circularSafeInset,
            )
            val topPadding = maxOf(
                scaffoldPadding.calculateTopPadding(),
                safeDrawingPadding.calculateTopPadding(),
                circularSafeInset,
            )
            val endPadding = maxOf(
                scaffoldPadding.calculateEndPadding(layoutDirection),
                safeDrawingPadding.calculateEndPadding(layoutDirection),
                circularSafeInset,
            )
            val bottomPadding = maxOf(
                scaffoldPadding.calculateBottomPadding(),
                safeDrawingPadding.calculateBottomPadding(),
                circularSafeInset,
            )
            val bottomControlsPadding = maxOf(
                scaffoldPadding.calculateBottomPadding(),
                safeDrawingPadding.calculateBottomPadding(),
                IconButtonDefaults.DefaultButtonSize / 2,
            )
            val controlBand = IconButtonDefaults.DefaultButtonSize
            val topActionPadding = maxOf(
                scaffoldPadding.calculateTopPadding(),
                safeDrawingPadding.calculateTopPadding(),
                IconButtonDefaults.DefaultButtonSize / 4,
            )
            val editorTopPadding = maxOf(
                circularSafeInset,
                topActionPadding + controlBand,
            )
            val editorBottomPadding = bottomPadding + controlBand
            val editorMinHeight = (
                maxHeight - editorTopPadding - editorBottomPadding
            )
                .coerceAtLeast(IconButtonDefaults.DefaultButtonSize)

            Box(Modifier.fillMaxSize()) {
                FilledIconButton(
                    onClick = {
                        currentOnDraftChange(textFieldState.text.toString())
                        keyboardController?.hide()
                        focusManager.clearFocus()
                        currentOnDone()
                    },
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(top = topActionPadding, end = endPadding)
                        .touchTargetAwareSize(28.dp),
                ) {
                    Icon(
                        WearIcons.Check,
                        contentDescription = "Готово",
                        modifier = Modifier.size(16.dp),
                    )
                }

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(
                            start = startPadding,
                            top = editorTopPadding,
                            end = endPadding,
                            bottom = editorBottomPadding,
                        )
                        .verticalScroll(contentScrollState),
                ) {
                    BasicTextField(
                        state = textFieldState,
                        textStyle = MaterialTheme.typography.bodyMedium.merge(
                            TextStyle(color = MaterialTheme.colorScheme.onSurface),
                        ),
                        lineLimits = TextFieldLineLimits.MultiLine(),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        onTextLayout = { getResult ->
                            textLayoutResult = getResult()
                        },
                        onKeyboardAction = {
                            currentOnDraftChange(textFieldState.text.toString())
                            keyboardController?.hide()
                            focusManager.clearFocus()
                        },
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                        decorator = { innerTextField ->
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .heightIn(min = editorMinHeight),
                            ) {
                                if (textFieldState.text.isEmpty()) {
                                    Text(
                                        "Написать сообщение…",
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        style = MaterialTheme.typography.bodyMedium,
                                    )
                                }
                                innerTextField()
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = editorMinHeight)
                            .focusRequester(focusRequester)
                            .pointerInput(textLayoutResult, textFieldState.text) {
                                detectTapGestures { position ->
                                    val layout = textLayoutResult ?: return@detectTapGestures
                                    val offset = layout.getOffsetForPosition(position)
                                    textFieldState.edit {
                                        selection = wordSelectionAt(
                                            text = textFieldState.text.toString(),
                                            offset = offset,
                                        )
                                    }
                                    openKeyboard()
                                }
                            },
                    )
                }

                Row(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = bottomControlsPadding),
                    horizontalArrangement = Arrangement.spacedBy(ButtonDefaults.IconSpacing),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    FilledTonalIconButton(
                        onClick = {
                            textFieldState.setTextAndPlaceCursorAtEnd("")
                            currentOnDraftChange("")
                        },
                        enabled = textFieldState.text.isNotEmpty(),
                        modifier = Modifier.touchTargetAwareSize(32.dp),
                    ) {
                        Icon(
                            WearIcons.Delete,
                            contentDescription = "Очистить всё",
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    FilledTonalIconButton(
                        onClick = onToggleWebSearch,
                        modifier = Modifier.touchTargetAwareSize(32.dp),
                    ) {
                        Icon(
                            if (answerSearchMode == AnswerSearchMode.RESEARCH) WearIcons.Research else WearIcons.Search,
                            contentDescription = when (answerSearchMode) {
                                AnswerSearchMode.RESEARCH -> "Исследование с проверкой ответа включено"
                                AnswerSearchMode.AUTO -> "Автоматический подбор источников"
                            },
                            tint = when {
                                answerSearchMode == AnswerSearchMode.RESEARCH -> MaterialTheme.colorScheme.error
                                else -> MaterialTheme.colorScheme.onSurfaceVariant
                            },
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    FilledTonalIconButton(
                        onClick = {
                            keyboardController?.hide()
                            focusManager.clearFocus()
                            currentOnVoice()
                        },
                        modifier = Modifier.touchTargetAwareSize(32.dp),
                    ) {
                        Icon(
                            WearIcons.Mic,
                            contentDescription = "Голосовой ввод",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        }
    }
}

/** Selects a whole word for a quick correction, while preserving a precise cursor elsewhere. */
internal fun wordSelectionAt(text: String, offset: Int): TextRange {
    if (text.isEmpty()) return TextRange.Zero

    val clampedOffset = offset.coerceIn(0, text.length)
    val characterIndex = when {
        clampedOffset < text.length && text[clampedOffset].isDraftWordCharacter() -> clampedOffset
        clampedOffset == text.length && text.last().isDraftWordCharacter() -> text.lastIndex
        else -> return TextRange(clampedOffset)
    }

    var start = characterIndex
    while (start > 0 && text[start - 1].isDraftWordCharacter()) start -= 1

    var end = characterIndex + 1
    while (end < text.length && text[end].isDraftWordCharacter()) end += 1

    return TextRange(start, end)
}

private fun Char.isDraftWordCharacter(): Boolean =
    isLetterOrDigit() || this == '-' || this == '\'' || this == '’'

private fun ProcessingStage.isProcessing(): Boolean = this in setOf(
    ProcessingStage.SENDING,
    ProcessingStage.WAITING,
    ProcessingStage.CONTEXT,
    ProcessingStage.ROUTING,
    ProcessingStage.USING_CHAT_SOURCE,
    ProcessingStage.FRAMING_REQUEST,
    ProcessingStage.SOURCE_INTENT,
    ProcessingStage.SEARCH_QUERY,
    ProcessingStage.SEARCHING,
    ProcessingStage.REVIEWING_SOURCES,
    ProcessingStage.OPENING_SOURCE,
    ProcessingStage.EVALUATING_SOURCE,
    ProcessingStage.EXTRACTING_SOURCE,
    ProcessingStage.SAVING_SOURCE,
    ProcessingStage.SEARCH_NO_RESULTS,
    ProcessingStage.SEARCH_UNAVAILABLE,
    ProcessingStage.RESEARCH_DRAFTING,
    ProcessingStage.RESEARCH_CHECKING,
    ProcessingStage.RESEARCH_REFINING,
    ProcessingStage.GENERATING,
    ProcessingStage.FALLBACK_GENERATING,
)

@Composable
private fun TransformingLazyColumnItemScope.MessageBubble(
    message: ChatMessage,
    onAnswer: (String) -> Unit,
) {
    if (message.role != "user" && message.content.isBlank()) {
        TypingIndicatorBubble()
        return
    }
    MessageBubble(
        text = if (message.role == "user") message.content else withoutSearchSources(message.content),
        user = message.role == "user",
        preview = message.role != "user",
        canOpenFullAnswer = message.role != "user",
        onClick = { onAnswer(message.id) },
    )
}

@Composable
private fun TransformingLazyColumnItemScope.MessageBubble(
    text: String,
    user: Boolean,
    preview: Boolean,
    canOpenFullAnswer: Boolean,
    openBeforeOverflow: Boolean = false,
    onClick: () -> Unit,
) {
    val visibleText = if (user) text else withoutSearchSources(text)
    var hasMoreThanThreeLines by remember(visibleText) { mutableStateOf(false) }
    // The feed shows a compact, marker-free preview; only the full reader renders
    // the Markdown block layout. Cached per text so streaming deltas reparse once.
    val renderedText = remember(visibleText, user) {
        if (user) AnnotatedString(visibleText) else previewMarkdown(visibleText)
    }
    val maxLines = if (user) 6 else 3
    val canExpand = !user && preview && canOpenFullAnswer &&
        (openBeforeOverflow || hasMoreThanThreeLines)
    Box(
        Modifier
            .fillMaxWidth()
            .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
        contentAlignment = if (user) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        val bubbleModifier = Modifier
            .fillMaxWidth(ChatLayout.messageWidthFraction)
            .clip(MaterialTheme.shapes.large)
            .background(
                if (user) {
                    MaterialTheme.colorScheme.primaryContainer
                } else {
                    MaterialTheme.colorScheme.surfaceContainer
                },
            )
            .then(if (canExpand) Modifier.clickable(onClick = onClick) else Modifier)
            // Cards use generous default content padding. Bubbles stay dense, with a
            // one-dp breathing margin on every edge so text does not hug the container.
            .padding(start = 13.dp, top = 8.dp, end = 13.dp, bottom = 6.dp)
        Box(
            modifier = bubbleModifier,
            contentAlignment = Alignment.CenterStart,
        ) {
            MessageText(
                text = renderedText,
                maxLines = maxLines,
                onTextLayout = { hasMoreThanThreeLines = it.hasVisualOverflow },
            )
        }
    }
}

@Composable
private fun TransformingLazyColumnItemScope.GenerationBubble(stage: ProcessingStage, ordinal: Int?) =
    TypingIndicatorBubble(processingLabel(stage, ordinal))

internal fun processingLabel(stage: ProcessingStage, ordinal: Int? = null): String = when (stage) {
    ProcessingStage.SENDING -> "Отправляю запрос…"
    ProcessingStage.WAITING -> "Запрос принят…"
    ProcessingStage.CONTEXT -> "Подбираю материалы…"
    ProcessingStage.ROUTING -> "Выбираю способ ответа…"
    ProcessingStage.USING_CHAT_SOURCE -> "Использую источник чата…"
    ProcessingStage.FRAMING_REQUEST -> "Уточняю задачу…"
    ProcessingStage.SOURCE_INTENT -> "Подбираю нужный текст…"
    ProcessingStage.SEARCH_QUERY -> "Уточняю поиск…"
    ProcessingStage.SEARCHING -> "Ищу источники${progressNumber(ordinal)}…"
    ProcessingStage.REVIEWING_SOURCES -> "Сверяю найденное${progressNumber(ordinal)}…"
    ProcessingStage.OPENING_SOURCE -> "Читаю источник${progressNumber(ordinal)}…"
    ProcessingStage.EVALUATING_SOURCE -> "Проверяю материал…"
    ProcessingStage.EXTRACTING_SOURCE -> "Выделяю фрагмент…"
    ProcessingStage.SAVING_SOURCE -> "Сохраняю в чат…"
    ProcessingStage.SEARCH_NO_RESULTS -> "Источники не найдены…"
    ProcessingStage.SEARCH_UNAVAILABLE -> "Поиск недоступен…"
    ProcessingStage.RESEARCH_DRAFTING -> "Составляю ответ…"
    ProcessingStage.RESEARCH_CHECKING -> "Проверяю ответ…"
    ProcessingStage.RESEARCH_REFINING -> "Уточняю ответ…"
    ProcessingStage.GENERATING -> "Готовлю ответ…"
    ProcessingStage.FALLBACK_GENERATING -> "Резервный сервер отвечает…"
    else -> "Формирую ответ…"
}

private fun progressNumber(ordinal: Int?): String = if (ordinal != null && ordinal > 1) " · $ordinal" else ""

@Composable
private fun TransformingLazyColumnItemScope.TypingIndicatorBubble(
    label: String = "Формирую ответ…",
) {
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            modifier = Modifier
                .wrapContentSize()
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceContainer)
                .padding(horizontal = 9.dp, vertical = 8.dp)
                .semantics { contentDescription = label },
            contentAlignment = Alignment.Center,
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                repeat(3) { index -> TypingDot(index) }
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall.copy(
                        fontSize = MaterialTheme.typography.labelSmall.fontSize * 0.9f,
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun TypingDot(index: Int) {
    val transition = rememberInfiniteTransition(label = "typing-dot-$index")
    val emphasis by transition.animateFloat(
        initialValue = .68f,
        targetValue = .68f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 900
                .68f at 0 using FastOutSlowInEasing
                1f at 180 using FastOutSlowInEasing
                .68f at 360 using FastOutSlowInEasing
                .68f at 900
            },
            initialStartOffset = StartOffset(
                offsetMillis = index * 120,
                offsetType = StartOffsetType.Delay,
            ),
        ),
        label = "typing-dot-emphasis-$index",
    )
    Box(
        Modifier
            .size(6.dp)
            .graphicsLayer {
                scaleX = emphasis
                scaleY = emphasis
                alpha = .42f + emphasis * .58f
            }
            .background(MaterialTheme.colorScheme.onSurfaceVariant, CircleShape),
    )
}

@Composable
private fun MessageText(
    text: AnnotatedString,
    maxLines: Int,
    onTextLayout: (androidx.compose.ui.text.TextLayoutResult) -> Unit = {},
) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
        onTextLayout = onTextLayout,
    )
}

@Composable
private fun chatScrollIndicator(
    state: TransformingLazyColumnState,
): (@Composable androidx.compose.foundation.layout.BoxScope.() -> Unit)? =
    if (LocalScrollCaptureInProgress.current) null else ({ ScrollIndicator(state = state) })

@WearPreviewDevices
@WearPreviewFontScales
@Composable
private fun ChatScreenPreview() {
    ChatScreenPreviewContent("Уточни второй пункт и приведи пример")
}

@Preview(
    name = "Composer 192 dp",
    device = "spec:width=192dp,height=192dp,dpi=320,isRound=true",
)
@Preview(
    name = "Composer 216 dp",
    device = "spec:width=216dp,height=216dp,dpi=320,isRound=true",
)
@Preview(
    name = "Composer Xiaomi Watch 2 233 dp",
    device = "spec:width=233dp,height=233dp,dpi=320,isRound=true",
)
@Preview(
    name = "Composer 240 dp",
    device = "spec:width=240dp,height=240dp,dpi=320,isRound=true",
)
@Composable
private fun ChatComposerSizePreviews() {
    ChatScreenPreviewContent(
        "Это длинный черновик на четыре строки: поле показывает только три строки и прокручивает остальной текст внутри без многоточия.",
    )
}

@Composable
private fun ChatScreenPreviewContent(draft: String) {
    val listState = rememberTransformingLazyColumnState()
    var composerHeightPx by remember { mutableIntStateOf(0) }
    WristMindWearTheme {
        AppScaffold(timeText = {}) {
            ChatScreen(
                state = WearState(
                    paired = true,
                    stage = ProcessingStage.READY,
                    vpsConnected = true,
                    activeChatId = "preview-chat",
                    messages = listOf(
                        ChatMessage(
                            id = "assistant-1",
                            role = "assistant",
                            content = "Короткий ответ остаётся читаемым с первого взгляда. Нажмите, чтобы открыть его полностью.",
                            status = "complete",
                        ),
                        ChatMessage(
                            id = "user-1",
                            role = "user",
                            content = "А длинный вопрос удобно дочитать в ленте?",
                            status = "complete",
                        ),
                    ),
                    draft = draft,
                ),
                listState = listState,
                composerHeightPx = composerHeightPx,
                onComposerHeightChanged = { composerHeightPx = it },
                onHistory = {},
                onEditDraft = {},
                onCancelAnswer = {},
                onAnswer = {},
                onOpenSource = {},
            )
        }
    }
}
