import { BasePage } from '@zeppos/zml/base-page'
import {
  pauseDropWristScreenOff,
  pausePalmScreenOff,
  resetDropWristScreenOff,
  resetPalmScreenOff,
  resetPageBrightTime,
  setPageBrightTime,
} from '@zos/display'
import { SCROLL_MODE_FREE, scrollTo, setScrollMode } from '@zos/page'
import {
  createWidget,
  getTextLayout,
  widget,
  align,
  text_style,
  prop,
} from '@zos/ui'
import { LocalStorage } from '@zos/storage'
import { px } from '@zos/utils'

const storage = new LocalStorage()

const LABELS = {
  OFFLINE: 'Телефон не в сети',
  IDLE: 'Готов к записи',
  REC: 'Запись идёт',
  STOP: 'Запись остановлена',
  SEND: 'Отправка',
  PROC: 'Формирование ответа',
  READY: 'Ответ готов',
  ERROR: 'Произошла ошибка',
}

Page(
  BasePage({
    state: {
      statusText: null,
      timerText: null,
      recognizedText: null,
      answerText: null,
      actionButton: null,
      pollHandle: null,
      recordTimer: null,
      pollBusy: false,
      serverState: 'OFFLINE',
      phoneOnline: false,
      recordingStartedAt: 0,
      connectionLamp: null,
      historyButton: null,
      historyWidgets: [],
      historyTitle: null,
      historyChatTitle: null,
      historyQuestion: null,
      historyAnswer: null,
      historyIndex: 0,
      history: [],
      chatTitle: 'Текущий диалог',
      lampTapCount: 0,
      lastLampTapAt: 0,
      recoveryTimers: [],
      sideServiceOnline: false,
      chats: [],
      activeChatId: 0,
      chatWidgets: [],
      chatScreenTitle: null,
      chatScreenName: null,
      chatScreenPreview: null,
      chatIndex: 0,
      fullWidgets: [],
      fullTitle: null,
      fullText: null,
      fullPages: [],
      fullPageIndex: 0,
      pendingFullAnswer: false,
      readyContainer: null,
      readyScrollbar: null,
      readyWidgets: [],
      readyBackground: null,
      readyQuestionCard: null,
      readyQuestionText: null,
      readyAnswerLabel: null,
      readyAnswerCard: null,
      readyAnswerText: null,
      readyNewQuestionButton: null,
      readyHistoryButton: null,
      readySpacer: null,
      readyAnswerKey: '',
      readyAnswer: '',
      readyTranscript: '',
      readyDismissed: false,
      screenMode: 'MAIN',
      mainBodyWidgets: [],
      mainAnswerCard: null,
      mainPageSpacer: null,
      mainAnswerKey: '',
    },

    build() {
      setScrollMode({
        mode: SCROLL_MODE_FREE,
        options: { modeParams: { bounce: true } },
      })
      setPageBrightTime({ brightTime: 2147483000 })
      pauseDropWristScreenOff({ duration: 0 })
      pausePalmScreenOff({ duration: 0 })

      createWidget(widget.FILL_RECT, {
        x: 0,
        y: 0,
        w: px(390),
        h: px(450),
        color: 0x090c16,
      })
      createWidget(widget.FILL_RECT, {
        x: px(18),
        y: px(18),
        w: px(5),
        h: px(38),
        radius: px(3),
        color: 0x9c82ff,
      })
      createWidget(widget.TEXT, {
        x: px(34),
        y: px(16),
        w: px(205),
        h: px(25),
        text: 'WRISTMIND',
        color: 0x9c82ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      createWidget(widget.TEXT, {
        x: px(34),
        y: px(39),
        w: px(205),
        h: px(22),
        text: 'голос рядом',
        color: 0x8991aa,
        text_size: px(15),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      this.state.connectionLamp = createWidget(widget.BUTTON, {
        x: px(252),
        y: px(22),
        w: px(120),
        h: px(32),
        radius: px(16),
        normal_color: 0x33291a,
        press_color: 0x49391e,
        text: '● ПРОВЕРКА',
        color: 0x6be8b8,
        text_size: px(12),
        click_func: () => this.onConnectionTap(),
      })

      const mainStatusCard = createWidget(widget.FILL_RECT, {
        x: px(18),
        y: px(76),
        w: px(354),
        h: px(132),
        radius: px(28),
        color: 0x141827,
      })
      this.state.statusText = createWidget(widget.TEXT, {
        x: px(38),
        y: px(89),
        w: px(314),
        h: px(47),
        text: 'Подключение через Zepp…',
        color: 0xe7e9f3,
        text_size: px(24),
        align_h: align.CENTER_H,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      this.state.timerText = createWidget(widget.TEXT, {
        x: px(38),
        y: px(137),
        w: px(314),
        h: px(56),
        text: '—',
        color: 0x9c82ff,
        text_size: px(40),
        align_h: align.CENTER_H,
        align_v: align.CENTER_V,
      })

      this.state.recognizedText = createWidget(widget.TEXT, {
        x: px(24),
        y: px(218),
        w: px(342),
        h: px(36),
        text: 'Распознано: —',
        color: 0x8991aa,
        text_size: px(13),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      const mainAnswerLabel = createWidget(widget.TEXT, {
        x: px(24),
        y: px(257),
        w: px(342),
        h: px(20),
        text: 'КОРОТКИЙ ОТВЕТ',
        color: 0x717a98,
        text_size: px(13),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      this.state.historyButton = createWidget(widget.BUTTON, {
        x: px(257),
        y: px(248),
        w: px(109),
        h: px(30),
        radius: px(15),
        normal_color: 0x24203b,
        press_color: 0x3b315d,
        text: 'ИСТОРИЯ ›',
        text_size: px(12),
        color: 0xbca7ff,
        click_func: () => this.showHistory(),
      })
      const mainAnswerCard = createWidget(widget.FILL_RECT, {
        x: px(18),
        y: px(280),
        w: px(354),
        h: px(82),
        radius: px(22),
        color: 0x111522,
      })
      this.state.mainAnswerCard = mainAnswerCard
      this.state.answerText = createWidget(widget.TEXT, {
        x: px(34),
        y: px(288),
        w: px(322),
        h: px(66),
        text: 'Ответ появится здесь',
        color: 0xdfe3f0,
        text_size: px(17),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      this.state.actionButton = createWidget(widget.BUTTON, {
        x: px(32),
        y: px(374),
        w: px(326),
        h: px(60),
        radius: px(28),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: 'Подключение…',
        text_size: px(22),
        color: 0xffffff,
        click_func: () => this.onAction(),
      })
      this.state.mainPageSpacer = createWidget(widget.FILL_RECT, {
        x: 0,
        y: px(449),
        w: 1,
        h: 1,
        color: 0x090c16,
      })
      this.state.mainBodyWidgets = [
        mainStatusCard,
        this.state.statusText,
        this.state.timerText,
        this.state.recognizedText,
        mainAnswerLabel,
        this.state.historyButton,
        mainAnswerCard,
        this.state.answerText,
        this.state.actionButton,
      ]

      this.restoreCachedHistory()
      this.buildHistoryOverlay()
      this.buildChatOverlay()
      this.buildFullAnswerOverlay()
      this.pollState()
      this.state.pollHandle = setInterval(() => this.pollState(), 1200)
    },

    pollState() {
      if (this.state.pollBusy) return
      this.state.pollBusy = true
      let phase = this.state.sideServiceOnline ? 'STATE' : 'ZEPP'
      const prepare = this.state.sideServiceOnline
        ? Promise.resolve()
        : this.request({ method: 'PING', params: { sentAt: Date.now() } }).then(() => {
            this.state.sideServiceOnline = true
            phase = 'STATE'
          })
      prepare
        .then(() => this.request({ method: 'STATE' }))
        .then(({ result }) => this.applyServerState(result))
        .catch((error) => {
          this.state.phoneOnline = false
          if (phase === 'ZEPP') {
            this.state.sideServiceOnline = false
            this.setConnectionIndicator('● НЕТ ZEPP', 0x3c1f28, 0xff7185)
            this.setText(this.state.statusText, 'Откройте Zepp на телефоне')
          } else {
            this.setConnectionIndicator('● НЕТ VPS', 0x3c1f28, 0xff7185)
            const detail = this.compact(
              String((error && error.message) || error || ''),
              36,
            )
            this.setText(
              this.state.statusText,
              detail ? `VPS недоступен · ${detail}` : 'Нет связи с VPS',
            )
          }
          this.setText(this.state.actionButton, 'Повторить')
        })
        .then(() => {
          this.state.pollBusy = false
        })
    },

    applyServerState(result) {
      if (!result) return
      this.state.phoneOnline = Boolean(result.phone_online)
      this.setConnectionIndicator(
        this.state.phoneOnline ? '● В СЕТИ' : '● ТЕЛЕФОН',
        this.state.phoneOnline ? 0x173028 : 0x33291a,
        this.state.phoneOnline ? 0x6be8b8 : 0xffb15c,
      )
      const nextState = this.state.phoneOnline ? result.state : 'OFFLINE'
      const previousState = this.state.serverState
      this.state.serverState = nextState
      this.setText(
        this.state.statusText,
        nextState === 'ERROR' && result.message
          ? this.compact(result.message, 70)
          : LABELS[nextState] || result.message || 'Обработка',
      )

      if (nextState === 'REC') {
        if (previousState !== 'REC') {
          this.state.recordingStartedAt = Date.now()
          this.startRecordTimer()
        }
      } else {
        this.stopRecordTimer()
        this.setText(
          this.state.timerText,
          nextState === 'OFFLINE' ? '—' : nextState === 'READY' ? '✓' : '•••',
        )
      }

      if (result.transcript) {
        this.setText(
          this.state.recognizedText,
          `Распознано: ${this.compact(result.transcript, 82)}`,
        )
      }
      const answerForScreen =
        result.watch_answer || result.answer || result.short_answer
      if (nextState === 'READY' && answerForScreen) {
        this.updateMainAnswer(answerForScreen, true)
      } else if (nextState !== 'READY') {
        this.state.mainAnswerKey = ''
        this.updateMainAnswer(
          answerForScreen || 'Ответ появится здесь',
          false,
        )
        if (previousState === 'READY') scrollTo({ y: 0 })
      }
      if (Array.isArray(result.history)) {
        this.state.history = result.history.slice(-5)
        this.state.chatTitle = result.chat_title || 'Текущий диалог'
        storage.setItem(
          'chat_history',
          JSON.stringify({
            title: this.state.chatTitle,
            items: this.state.history,
          }),
        )
        if (this.state.historyWidgets[0]) this.renderHistory()
      }
      if (Array.isArray(result.chats)) {
        const previousActiveChatId = this.state.activeChatId
        this.state.chats = result.chats
        this.state.activeChatId = Number(result.active_chat_id || 0)
        const activeIndex = this.state.chats.findIndex(
          (chat) => Number(chat.id) === this.state.activeChatId,
        )
        if (
          activeIndex >= 0 &&
          (
            previousActiveChatId !== this.state.activeChatId ||
            this.state.chatIndex >= this.state.chats.length
          )
        ) {
          this.state.chatIndex = activeIndex
        }
        if (this.state.chatWidgets[0]) this.renderChats()
      }
      if (
        this.state.pendingFullAnswer &&
        result.message === 'Полный ответ загружен' &&
        result.answer
      ) {
        this.state.pendingFullAnswer = false
        this.openFullAnswer(result.answer)
      }

      const buttonLabels = {
        OFFLINE: 'Откройте WristMind на телефоне',
        IDLE: 'Начать запись',
        REC: 'Остановить',
        STOP: 'Подождите…',
        SEND: 'Отправка…',
        PROC: 'Обработка…',
        READY: 'Новый вопрос',
        ERROR: 'Сбросить',
      }
      this.setText(this.state.actionButton, buttonLabels[nextState] || 'Подождите…')
      this.updateMainActionLayout(nextState === 'READY')
    },

    updateMainAnswer(value, expanded) {
      const fullText = String(value || '').trim() || 'Ответ пуст'
      const text = expanded ? fullText : this.compact(fullText, 170)
      const textHeight = expanded
        ? this.measureTextHeight(text, px(17), px(322), px(66))
        : px(66)
      const cardHeight = textHeight + px(16)
      this.state.mainAnswerCard.setProperty(prop.MORE, {
        x: px(18),
        y: px(280),
        w: px(354),
        h: cardHeight,
        radius: px(22),
        color: 0x111522,
      })
      this.state.answerText.setProperty(prop.MORE, {
        x: px(34),
        y: px(288),
        w: px(322),
        h: textHeight,
        text,
        color: 0xdfe3f0,
        text_size: px(17),
        align_h: align.LEFT,
        align_v: expanded ? align.TOP : align.CENTER_V,
        text_style: text_style.WRAP,
      })
      this.state.mainPageSpacer.setProperty(prop.MORE, {
        y: Math.max(px(449), px(280) + cardHeight + px(22)),
      })
      const key = `${fullText.length}:${fullText.slice(-32)}`
      if (expanded && key !== this.state.mainAnswerKey) {
        this.state.mainAnswerKey = key
        scrollTo({ y: 0 })
      }
    },

    updateMainActionLayout(ready) {
      this.state.timerText.setProperty(prop.VISIBLE, !ready)
      this.state.actionButton.setProperty(prop.MORE, ready
        ? {
            x: px(82),
            y: px(142),
            w: px(226),
            h: px(50),
            radius: px(23),
            text_size: px(18),
          }
        : {
            x: px(32),
            y: px(374),
            w: px(326),
            h: px(60),
            radius: px(28),
            text_size: px(22),
          })
    },

    onAction() {
      if (!this.state.phoneOnline) {
        this.pollState()
        return
      }
      if (this.state.serverState === 'READY') {
        this.state.readyDismissed = true
        this.state.screenMode = 'MAIN'
        this.hideReadyAnswer()
      }
      const name =
        this.state.serverState === 'REC'
          ? 'STOP'
          : this.state.serverState === 'ERROR'
            ? 'RESET'
            : 'START'
      const commandId = `watch-${Date.now()}`
      this.setText(this.state.statusText, 'Отправка команды…')
      this.request({
        method: 'COMMAND',
        params: { command_id: commandId, name },
      })
        .then(() => {
          this.setText(this.state.statusText, 'Команда принята VPS')
          setTimeout(() => this.pollState(), 250)
        })
        .catch(() => {
          this.setText(this.state.statusText, 'Команда не отправлена')
          this.setText(this.state.actionButton, 'Повторить')
        })
    },

    onConnectionTap() {
      const now = Date.now()
      if (now - this.state.lastLampTapAt > 2400) this.state.lampTapCount = 0
      this.state.lastLampTapAt = now
      this.state.lampTapCount += 1
      if (this.state.lampTapCount < 3) {
        const remaining = 3 - this.state.lampTapCount
        this.setText(
          this.state.statusText,
          `Ещё ${remaining} ${remaining === 1 ? 'нажатие' : 'нажатия'} для восстановления`,
        )
        return
      }
      this.state.lampTapCount = 0
      this.recoverConnection()
    },

    recoverConnection() {
      this.state.sideServiceOnline = false
      this.setConnectionIndicator('● РЕМОНТ', 0x4a3319, 0xffc06e)
      this.setText(this.state.statusText, 'Диагностика Zepp → VPS → телефон')
      this.state.pollBusy = false
      this.request({ method: 'PING', params: { sentAt: Date.now() } })
        .then(() =>
          this.request({
            method: 'COMMAND',
            params: { command_id: `recover-${Date.now()}`, name: 'PING' },
          }),
        )
        .then(() => {
          this.setText(this.state.statusText, 'Сигнал восстановления отправлен')
        })
        .catch(() => {
          this.setText(this.state.statusText, 'Канал ещё недоступен · продолжаю поиск')
        })
      ;[0, 1500, 4000, 8000].forEach((delay) => {
        const handle = setTimeout(() => this.pollState(), delay)
        this.state.recoveryTimers.push(handle)
      })
    },

    setConnectionIndicator(text, background, foreground) {
      if (!this.state.connectionLamp) return
      this.state.connectionLamp.setProperty(prop.MORE, {
        normal_color: background,
        press_color: background,
        text,
        color: foreground,
      })
    },

    restoreCachedHistory() {
      try {
        const cached = JSON.parse(storage.getItem('chat_history', '{}'))
        if (cached && Array.isArray(cached.items)) {
          this.state.history = cached.items.slice(-5)
          this.state.chatTitle = cached.title || 'Текущий диалог'
        }
      } catch (_) {
        this.state.history = []
      }
    },

    buildReadyOverlay() {
      const container = createWidget(widget.VIEW_CONTAINER, {
        x: 0,
        y: px(68),
        w: px(390),
        h: px(382),
        scroll_enable: 1,
        bounce: 1,
      })
      container.setProperty(prop.VISIBLE, false)
      this.state.readyContainer = container

      const add = (type, options) => {
        const target = container.createWidget(type, options)
        target.setProperty(prop.VISIBLE, false)
        this.state.readyWidgets.push(target)
        return target
      }
      this.state.readyBackground = add(widget.FILL_RECT, {
        x: 0,
        y: 0,
        w: px(390),
        h: px(382),
        color: 0x090c16,
      })
      add(widget.TEXT, {
        x: px(18),
        y: px(10),
        w: px(354),
        h: px(34),
        text: 'ОТВЕТ ГОТОВ',
        color: 0x74e7bd,
        text_size: px(21),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      add(widget.TEXT, {
        x: px(24),
        y: px(48),
        w: px(342),
        h: px(22),
        text: 'РАСПОЗНАНО',
        color: 0x75aefc,
        text_size: px(12),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      this.state.readyQuestionCard = add(widget.FILL_RECT, {
        x: px(12),
        y: px(72),
        w: px(366),
        h: px(54),
        radius: px(20),
        color: 0x172640,
      })
      this.state.readyQuestionText = add(widget.TEXT, {
        x: px(26),
        y: px(82),
        w: px(338),
        h: px(34),
        text: '—',
        color: 0xdceaff,
        text_size: px(15),
        align_h: align.LEFT,
        align_v: align.TOP,
        text_style: text_style.WRAP,
      })
      this.state.readyAnswerLabel = add(widget.TEXT, {
        x: px(24),
        y: px(144),
        w: px(342),
        h: px(22),
        text: 'WRISTMIND',
        color: 0xbca7ff,
        text_size: px(12),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      this.state.readyAnswerCard = add(widget.FILL_RECT, {
        x: px(12),
        y: px(168),
        w: px(366),
        h: px(100),
        radius: px(22),
        color: 0x211b37,
      })
      this.state.readyAnswerText = add(widget.TEXT, {
        x: px(26),
        y: px(182),
        w: px(338),
        h: px(72),
        text: '—',
        color: 0xf4f0ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.TOP,
        text_style: text_style.WRAP,
      })
      this.state.readyNewQuestionButton = add(widget.BUTTON, {
        x: px(20),
        y: px(286),
        w: px(350),
        h: px(58),
        radius: px(27),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: 'Новый вопрос',
        text_size: px(20),
        color: 0xffffff,
        click_func: () => {
          this.state.readyDismissed = true
          this.state.screenMode = 'MAIN'
          this.hideReadyAnswer()
          this.onAction()
        },
      })
      this.state.readyHistoryButton = add(widget.BUTTON, {
        x: px(20),
        y: px(354),
        w: px(350),
        h: px(48),
        radius: px(23),
        normal_color: 0x202536,
        press_color: 0x30374d,
        text: 'Диалоги и история',
        text_size: px(16),
        color: 0xcfd5e8,
        click_func: () => this.showHistory(),
      })
      this.state.readySpacer = add(widget.FILL_RECT, {
        x: 0,
        y: px(418),
        w: 1,
        h: 1,
        color: 0x090c16,
      })

      this.state.readyScrollbar = createWidget(widget.PAGE_SCROLLBAR, {
        target: container,
      })
      this.state.readyScrollbar.setProperty(prop.VISIBLE, false)
    },

    measureTextHeight(value, textSize, width, minimum) {
      try {
        const layout = getTextLayout(String(value || '—'), {
          text_size: textSize,
          text_width: width,
          wrapped: 1,
          rows_max: 0,
        })
        if (layout && layout.height) return Math.max(minimum, layout.height)
      } catch (_) {}
      const estimatedLines = Math.max(
        1,
        Math.ceil(String(value || '—').length / 31),
      )
      return Math.max(minimum, estimatedLines * Math.round(textSize * 1.35))
    },

    showReadyAnswer(transcript, answer) {
      if (
        this.state.screenMode === 'HISTORY' ||
        this.state.screenMode === 'CHATS' ||
        this.state.screenMode === 'FULL'
      ) {
        return
      }
      const question = String(transcript || 'Вопрос с часов')
      const fullAnswer = String(answer || 'Ответ пуст')
      const key = `${question.length}:${fullAnswer.length}:${fullAnswer.slice(-32)}`
      this.state.readyAnswer = fullAnswer
      this.state.readyTranscript = question
      this.state.screenMode = 'READY'

      if (key !== this.state.readyAnswerKey) {
        this.state.readyAnswerKey = key
        const questionHeight = this.measureTextHeight(
          question,
          px(15),
          px(338),
          px(34),
        )
        const answerHeight = this.measureTextHeight(
          fullAnswer,
          px(18),
          px(338),
          px(48),
        )
        const questionCardY = px(72)
        const questionCardHeight = questionHeight + px(20)
        const answerLabelY = questionCardY + questionCardHeight + px(14)
        const answerCardY = answerLabelY + px(26)
        const answerCardHeight = answerHeight + px(28)
        const newQuestionY = answerCardY + answerCardHeight + px(18)
        const historyY = newQuestionY + px(68)
        const contentHeight = historyY + px(66)

        this.state.readyBackground.setProperty(prop.MORE, {
          h: Math.max(px(382), contentHeight),
        })
        this.state.readyQuestionCard.setProperty(prop.MORE, {
          h: questionCardHeight,
        })
        this.state.readyQuestionText.setProperty(prop.MORE, {
          h: questionHeight,
          text: question,
        })
        this.state.readyAnswerLabel.setProperty(prop.MORE, { y: answerLabelY })
        this.state.readyAnswerCard.setProperty(prop.MORE, {
          y: answerCardY,
          h: answerCardHeight,
        })
        this.state.readyAnswerText.setProperty(prop.MORE, {
          y: answerCardY + px(14),
          h: answerHeight,
          text: fullAnswer,
        })
        this.state.readyNewQuestionButton.setProperty(prop.MORE, {
          y: newQuestionY,
        })
        this.state.readyHistoryButton.setProperty(prop.MORE, { y: historyY })
        this.state.readySpacer.setProperty(prop.MORE, { y: contentHeight })
        this.state.readyContainer.setProperty(prop.MORE, { pos_y: 0 })
      }
      this.state.readyContainer.setProperty(prop.VISIBLE, true)
      this.state.readyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      this.state.mainBodyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, false),
      )
      this.state.readyScrollbar.setProperty(prop.VISIBLE, true)
    },

    hideReadyAnswer() {
      this.state.readyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, false),
      )
      if (this.state.readyContainer) {
        this.state.readyContainer.setProperty(prop.VISIBLE, false)
      }
      if (this.state.readyScrollbar) {
        this.state.readyScrollbar.setProperty(prop.VISIBLE, false)
      }
      this.state.mainBodyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      if (this.state.screenMode === 'READY') this.state.screenMode = 'MAIN'
    },

    buildHistoryOverlay() {
      const add = (type, options) => {
        const target = createWidget(type, options)
        target.setProperty(prop.VISIBLE, false)
        this.state.historyWidgets.push(target)
        return target
      }
      add(widget.FILL_RECT, {
        x: 0,
        y: px(68),
        w: px(390),
        h: px(382),
        color: 0x090c16,
      })
      this.state.historyTitle = add(widget.TEXT, {
        x: px(22),
        y: px(76),
        w: px(220),
        h: px(28),
        text: 'ИСТОРИЯ',
        color: 0xbca7ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      add(widget.BUTTON, {
        x: px(258),
        y: px(74),
        w: px(114),
        h: px(32),
        radius: px(16),
        normal_color: 0x24203b,
        press_color: 0x3b315d,
        text: 'ДИАЛОГИ',
        text_size: px(12),
        color: 0xbca7ff,
        click_func: () => this.showChats(),
      })
      this.state.historyChatTitle = add(widget.TEXT, {
        x: px(22),
        y: px(104),
        w: px(346),
        h: px(24),
        text: 'Текущий диалог',
        color: 0x7f88a5,
        text_size: px(13),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      add(widget.FILL_RECT, {
        x: px(18),
        y: px(136),
        w: px(354),
        h: px(82),
        radius: px(20),
        color: 0x182743,
      })
      this.state.historyQuestion = add(widget.TEXT, {
        x: px(32),
        y: px(145),
        w: px(326),
        h: px(64),
        text: 'Вопросов пока нет',
        color: 0xdce8ff,
        text_size: px(16),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      add(widget.FILL_RECT, {
        x: px(18),
        y: px(228),
        w: px(354),
        h: px(136),
        radius: px(20),
        color: 0x221c38,
      })
      this.state.historyAnswer = add(widget.TEXT, {
        x: px(32),
        y: px(238),
        w: px(326),
        h: px(88),
        text: 'Ответы активного диалога появятся здесь',
        color: 0xf0ebff,
        text_size: px(17),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      add(widget.BUTTON, {
        x: px(218),
        y: px(330),
        w: px(140),
        h: px(27),
        radius: px(13),
        normal_color: 0x3a2d61,
        press_color: 0x58418d,
        text: 'ПОЛНЫЙ ОТВЕТ',
        text_size: px(11),
        color: 0xd9caff,
        click_func: () => this.requestFullAnswer(),
      })
      add(widget.BUTTON, {
        x: px(18),
        y: px(378),
        w: px(70),
        h: px(54),
        radius: px(25),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '‹',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveHistory(-1),
      })
      add(widget.BUTTON, {
        x: px(98),
        y: px(378),
        w: px(194),
        h: px(54),
        radius: px(25),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: 'К записи',
        text_size: px(18),
        color: 0xffffff,
        click_func: () => this.hideHistory(),
      })
      add(widget.BUTTON, {
        x: px(302),
        y: px(378),
        w: px(70),
        h: px(54),
        radius: px(25),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '›',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveHistory(1),
      })
    },

    showHistory() {
      this.hideReadyAnswer()
      this.state.screenMode = 'HISTORY'
      this.state.historyIndex = Math.max(0, this.state.history.length - 1)
      this.state.historyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      this.renderHistory()
    },

    hideHistory() {
      this.state.historyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, false),
      )
      this.state.screenMode = 'MAIN'
      if (
        this.state.serverState === 'READY' &&
        this.state.readyAnswer &&
        !this.state.readyDismissed
      ) {
        this.showReadyAnswer(this.state.readyTranscript, this.state.readyAnswer)
      }
    },

    moveHistory(direction) {
      if (!this.state.history.length) return
      this.state.historyIndex = Math.max(
        0,
        Math.min(this.state.history.length - 1, this.state.historyIndex + direction),
      )
      this.renderHistory()
    },

    renderHistory() {
      const total = this.state.history.length
      this.setText(
        this.state.historyTitle,
        total ? `ИСТОРИЯ · ${this.state.historyIndex + 1}/${total}` : 'ИСТОРИЯ · ПУСТО',
      )
      this.setText(
        this.state.historyChatTitle,
        this.compact(this.state.chatTitle, 42),
      )
      const item = total ? this.state.history[this.state.historyIndex] : null
      this.setText(
        this.state.historyQuestion,
        item ? this.compact(`Вы: ${item.question}`, 150) : 'Вопросов пока нет',
      )
      this.setText(
        this.state.historyAnswer,
        item
          ? this.compact(`WristMind: ${item.answer}`, 300)
          : 'Ответы активного диалога появятся здесь',
      )
    },

    buildChatOverlay() {
      const add = (type, options) => {
        const target = createWidget(type, options)
        target.setProperty(prop.VISIBLE, false)
        this.state.chatWidgets.push(target)
        return target
      }
      add(widget.FILL_RECT, {
        x: 0,
        y: px(68),
        w: px(390),
        h: px(382),
        color: 0x090c16,
      })
      this.state.chatScreenTitle = add(widget.TEXT, {
        x: px(22),
        y: px(76),
        w: px(220),
        h: px(30),
        text: 'ДИАЛОГИ',
        color: 0xbca7ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      add(widget.BUTTON, {
        x: px(252),
        y: px(74),
        w: px(120),
        h: px(34),
        radius: px(16),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: '+ НОВЫЙ',
        text_size: px(13),
        color: 0xffffff,
        click_func: () => this.createWatchChat(),
      })
      add(widget.BUTTON, {
        x: px(18),
        y: px(116),
        w: px(104),
        h: px(32),
        radius: px(15),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '‹ ИСТОРИЯ',
        text_size: px(12),
        color: 0xcfd5e8,
        click_func: () => {
          this.hideChats()
          this.showHistory()
        },
      })
      add(widget.FILL_RECT, {
        x: px(18),
        y: px(158),
        w: px(354),
        h: px(188),
        radius: px(24),
        color: 0x171b2c,
      })
      this.state.chatScreenName = add(widget.TEXT, {
        x: px(36),
        y: px(176),
        w: px(318),
        h: px(62),
        text: 'Диалогов пока нет',
        color: 0xf0ecff,
        text_size: px(20),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      this.state.chatScreenPreview = add(widget.TEXT, {
        x: px(36),
        y: px(244),
        w: px(318),
        h: px(82),
        text: 'Создайте первый диалог',
        color: 0x929bb7,
        text_size: px(15),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      add(widget.BUTTON, {
        x: px(18),
        y: px(366),
        w: px(70),
        h: px(62),
        radius: px(28),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '‹',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveChat(-1),
      })
      add(widget.BUTTON, {
        x: px(98),
        y: px(366),
        w: px(194),
        h: px(62),
        radius: px(28),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: 'Выбрать',
        text_size: px(18),
        color: 0xffffff,
        click_func: () => this.selectWatchChat(),
      })
      add(widget.BUTTON, {
        x: px(302),
        y: px(366),
        w: px(70),
        h: px(62),
        radius: px(28),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '›',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveChat(1),
      })
    },

    showChats() {
      this.hideHistory()
      this.hideReadyAnswer()
      this.state.screenMode = 'CHATS'
      this.state.chatIndex = Math.max(
        0,
        this.state.chats.findIndex(
          (chat) => Number(chat.id) === this.state.activeChatId,
        ),
      )
      this.state.chatWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      this.renderChats()
    },

    hideChats() {
      this.state.chatWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, false),
      )
      if (this.state.screenMode === 'CHATS') this.state.screenMode = 'MAIN'
    },

    moveChat(direction) {
      if (!this.state.chats.length) return
      this.state.chatIndex = Math.max(
        0,
        Math.min(this.state.chats.length - 1, this.state.chatIndex + direction),
      )
      this.renderChats()
    },

    renderChats() {
      const total = this.state.chats.length
      this.setText(
        this.state.chatScreenTitle,
        total ? `ДИАЛОГИ · ${this.state.chatIndex + 1}/${total}` : 'ДИАЛОГИ · ПУСТО',
      )
      const chat = total ? this.state.chats[this.state.chatIndex] : null
      const selected = chat && Number(chat.id) === this.state.activeChatId
      this.setText(
        this.state.chatScreenName,
        chat
          ? `${selected ? '● ' : ''}${this.compact(chat.title, 72)}`
          : 'Диалогов пока нет',
      )
      this.setText(
        this.state.chatScreenPreview,
        chat && chat.preview
          ? this.compact(chat.preview, 180)
          : 'Создайте новый диалог и задайте вопрос',
      )
    },

    createWatchChat() {
      this.setText(this.state.chatScreenTitle, 'СОЗДАЮ ДИАЛОГ…')
      this.request({
        method: 'COMMAND',
        params: { command_id: `chat-new-${Date.now()}`, name: 'CHAT_CREATE' },
      })
        .then(() => {
          this.state.readyDismissed = true
          this.hideReadyAnswer()
          this.hideChats()
          this.hideHistory()
          this.state.fullWidgets.forEach((target) =>
            target.setProperty(prop.VISIBLE, false),
          )
          this.state.screenMode = 'MAIN'
          this.setText(this.state.statusText, 'Новый диалог создан')
          setTimeout(() => this.pollState(), 300)
          setTimeout(() => this.pollState(), 1200)
        })
        .catch(() => this.setText(this.state.chatScreenTitle, 'НЕ УДАЛОСЬ СОЗДАТЬ'))
    },

    selectWatchChat() {
      const chat = this.state.chats[this.state.chatIndex]
      if (!chat) return
      this.setText(this.state.chatScreenTitle, 'ПЕРЕКЛЮЧАЮ…')
      this.request({
        method: 'COMMAND',
        params: {
          command_id: `chat-select-${Date.now()}`,
          name: 'CHAT_SELECT',
          chat_id: Number(chat.id),
        },
      })
        .then(() => {
          this.state.readyDismissed = true
          this.hideReadyAnswer()
          this.hideChats()
          this.hideHistory()
          this.state.fullWidgets.forEach((target) =>
            target.setProperty(prop.VISIBLE, false),
          )
          this.state.screenMode = 'MAIN'
          this.setText(this.state.statusText, 'Диалог выбран')
          setTimeout(() => this.pollState(), 300)
          setTimeout(() => this.pollState(), 1200)
        })
        .catch(() => this.setText(this.state.chatScreenTitle, 'НЕ УДАЛОСЬ ВЫБРАТЬ'))
    },

    buildFullAnswerOverlay() {
      const add = (type, options) => {
        const target = createWidget(type, options)
        target.setProperty(prop.VISIBLE, false)
        this.state.fullWidgets.push(target)
        return target
      }
      add(widget.FILL_RECT, {
        x: 0,
        y: px(68),
        w: px(390),
        h: px(382),
        color: 0x090c16,
      })
      this.state.fullTitle = add(widget.TEXT, {
        x: px(22),
        y: px(78),
        w: px(346),
        h: px(30),
        text: 'ПОЛНЫЙ ОТВЕТ',
        color: 0xbca7ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
      })
      add(widget.FILL_RECT, {
        x: px(18),
        y: px(120),
        w: px(354),
        h: px(238),
        radius: px(24),
        color: 0x221c38,
      })
      this.state.fullText = add(widget.TEXT, {
        x: px(34),
        y: px(136),
        w: px(322),
        h: px(206),
        text: 'Загрузка…',
        color: 0xf4f0ff,
        text_size: px(18),
        align_h: align.LEFT,
        align_v: align.CENTER_V,
        text_style: text_style.WRAP,
      })
      add(widget.BUTTON, {
        x: px(18),
        y: px(370),
        w: px(70),
        h: px(58),
        radius: px(27),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '‹',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveFullPage(-1),
      })
      add(widget.BUTTON, {
        x: px(98),
        y: px(370),
        w: px(194),
        h: px(58),
        radius: px(27),
        normal_color: 0x6f56d6,
        press_color: 0x5138a8,
        text: 'К истории',
        text_size: px(18),
        color: 0xffffff,
        click_func: () => this.returnToHistory(),
      })
      add(widget.BUTTON, {
        x: px(302),
        y: px(370),
        w: px(70),
        h: px(58),
        radius: px(27),
        normal_color: 0x24293b,
        press_color: 0x353d58,
        text: '›',
        text_size: px(30),
        color: 0xdce1f2,
        click_func: () => this.moveFullPage(1),
      })
    },

    requestFullAnswer() {
      const item = this.state.history[this.state.historyIndex]
      if (!item || !item.id) return
      this.state.pendingFullAnswer = true
      this.setText(this.state.historyAnswer, 'Загружаю полный ответ с телефона…')
      this.request({
        method: 'COMMAND',
        params: {
          command_id: `chat-detail-${Date.now()}`,
          name: 'CHAT_DETAIL',
          exchange_id: Number(item.id),
        },
      })
        .then(() => {
          setTimeout(() => this.pollState(), 300)
          setTimeout(() => this.pollState(), 1200)
          setTimeout(() => this.pollState(), 2500)
        })
        .catch(() => {
          this.state.pendingFullAnswer = false
          this.setText(this.state.historyAnswer, 'Не удалось загрузить полный ответ')
        })
    },

    openFullAnswer(value) {
      this.hideReadyAnswer()
      this.state.screenMode = 'FULL'
      this.hideHistory()
      this.hideChats()
      this.state.fullPages = this.paginate(value, 330)
      this.state.fullPageIndex = 0
      this.state.fullWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      this.renderFullAnswer()
    },

    paginate(value, limit) {
      let remaining = String(value || '').replace(/\s+/g, ' ').trim()
      const pages = []
      while (remaining.length > limit) {
        let splitAt = remaining.lastIndexOf(' ', limit)
        if (splitAt < limit * 0.55) splitAt = limit
        pages.push(remaining.slice(0, splitAt).trim())
        remaining = remaining.slice(splitAt).trim()
      }
      if (remaining) pages.push(remaining)
      return pages.length ? pages : ['Ответ пуст']
    },

    moveFullPage(direction) {
      this.state.fullPageIndex = Math.max(
        0,
        Math.min(
          this.state.fullPages.length - 1,
          this.state.fullPageIndex + direction,
        ),
      )
      this.renderFullAnswer()
    },

    renderFullAnswer() {
      this.setText(
        this.state.fullTitle,
        `ПОЛНЫЙ ОТВЕТ · ${this.state.fullPageIndex + 1}/${this.state.fullPages.length}`,
      )
      this.setText(
        this.state.fullText,
        this.state.fullPages[this.state.fullPageIndex] || 'Ответ пуст',
      )
    },

    returnToHistory() {
      this.state.fullWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, false),
      )
      this.state.historyWidgets.forEach((target) =>
        target.setProperty(prop.VISIBLE, true),
      )
      this.state.screenMode = 'HISTORY'
      this.renderHistory()
    },

    startRecordTimer() {
      this.stopRecordTimer()
      const update = () => {
        const seconds = Math.max(
          0,
          Math.floor((Date.now() - this.state.recordingStartedAt) / 1000),
        )
        const minutes = Math.floor(seconds / 60)
          .toString()
          .padStart(2, '0')
        const rest = (seconds % 60).toString().padStart(2, '0')
        this.setText(this.state.timerText, `${minutes}:${rest}`)
      }
      update()
      this.state.recordTimer = setInterval(update, 1000)
    },

    stopRecordTimer() {
      if (this.state.recordTimer) {
        clearInterval(this.state.recordTimer)
        this.state.recordTimer = null
      }
    },

    compact(value, limit) {
      const text = String(value || '').replace(/\s+/g, ' ').trim()
      return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`
    },

    setText(target, value) {
      target && target.setProperty(prop.TEXT, value)
    },

    onDestroy() {
      if (this.state.pollHandle) clearInterval(this.state.pollHandle)
      this.stopRecordTimer()
      this.state.recoveryTimers.forEach((handle) => clearTimeout(handle))
      resetPageBrightTime()
      resetDropWristScreenOff()
      resetPalmScreenOff()
    },
  }),
)
