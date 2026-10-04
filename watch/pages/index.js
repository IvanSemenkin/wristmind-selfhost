import {
  mstBuildProfile,
  mstConnect,
  mstDestroyProfileInstance,
  mstDisconnect,
  mstOffAllCb,
  mstOnCharaNotification,
  mstOnCharaWriteComplete,
  mstOnDescWriteComplete,
  mstOnPrepare,
  mstStartScan,
  mstStopScan,
  mstWriteCharacteristic,
  mstWriteDescriptor,
} from '@zos/ble'
import {
  pauseDropWristScreenOff,
  pausePalmScreenOff,
  resetDropWristScreenOff,
  resetPalmScreenOff,
  resetPageBrightTime,
  setPageBrightTime,
} from '@zos/display'
import { GESTURE_RIGHT, onGesture } from '@zos/interaction'
import { createWidget, widget, align, text_style, prop } from '@zos/ui'
import { px, log } from '@zos/utils'

const SERVICE_UUID = '8a710001-5f31-4a7c-bc51-6a7c250d6f10'
const SERVICE_UUID_COMPACT = SERVICE_UUID.replace(/-/g, '')
const ADVERTISING_UUID_COMPACT = '0000fff000001000800000805f9b34fb'
const COMMAND_UUID = '8a710002-5f31-4a7c-bc51-6a7c250d6f10'
const EVENT_UUID = '8a710003-5f31-4a7c-bc51-6a7c250d6f10'
const CCCD_UUID = '2902'
const logger = log.getLogger('wristmind-page')

function utf8FromBuffer(buffer) {
  const bytes = new Uint8Array(buffer)
  let result = ''
  let index = 0
  while (index < bytes.length) {
    const first = bytes[index++]
    if (first < 128) {
      result += String.fromCharCode(first)
    } else if (first < 224) {
      const second = bytes[index++]
      result += String.fromCharCode(((first & 31) << 6) | (second & 63))
    } else if (first < 240) {
      const second = bytes[index++]
      const third = bytes[index++]
      result += String.fromCharCode(
        ((first & 15) << 12) | ((second & 63) << 6) | (third & 63),
      )
    } else {
      const second = bytes[index++]
      const third = bytes[index++]
      const fourth = bytes[index++]
      let codePoint =
        ((first & 7) << 18) |
        ((second & 63) << 12) |
        ((third & 63) << 6) |
        (fourth & 63)
      codePoint -= 0x10000
      result += String.fromCharCode(
        0xd800 + (codePoint >> 10),
        0xdc00 + (codePoint & 1023),
      )
    }
  }
  return result
}

function compactUuid(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^0-9a-f]/g, '')
}

function bufferKey(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

function asciiBuffer(value) {
  return new Uint8Array(
    value.split('').map((character) => character.charCodeAt(0)),
  ).buffer
}

function isAdvertisingUuid(value) {
  const uuid = compactUuid(value)
  return uuid === 'fff0' || uuid === ADVERTISING_UUID_COMPACT
}

function hasWristMindMarker(item) {
  if (!item || !isAdvertisingUuid(item.uuid) || !item.service_data) return false
  const bytes = new Uint8Array(item.service_data)
  return bytes.length >= 2 && bytes[0] === 0x57 && bytes[1] === 0x4d
}

Page({
  state: 'CONNECTING',
  connectId: null,
  profileId: null,
  deviceAddress: null,
  isScanning: false,
  bleTimer: null,
  scannedAddresses: {},
  statusText: null,
  timerText: null,
  recognizedText: null,
  answerText: null,
  actionButton: null,
  timerHandle: null,
  startedAt: 0,
  commandSequence: 0,
  answerChunks: [],
  recognizedChunks: [],
  connectAttempt: 0,
  scannedDeviceCount: 0,
  scanElapsed: 0,
  lastRightSwipeAt: 0,
  rightSwipeHintTimer: null,
  currentStatusLabel: 'Поиск телефона…',

  build() {
    setPageBrightTime({ brightTime: 2147483000 })
    pauseDropWristScreenOff({ duration: 0 })
    pausePalmScreenOff({ duration: 0 })
    onGesture({
      callback: (event) => {
        if (event !== GESTURE_RIGHT) return false
        const now = Date.now()
        if (now - this.lastRightSwipeAt <= 1500) {
          this.lastRightSwipeAt = 0
          if (this.rightSwipeHintTimer) {
            clearTimeout(this.rightSwipeHintTimer)
            this.rightSwipeHintTimer = null
          }
          return false
        }
        this.lastRightSwipeAt = now
        this.statusText &&
          this.statusText.setProperty(prop.TEXT, 'Ещё раз вправо для выхода')
        if (this.rightSwipeHintTimer) clearTimeout(this.rightSwipeHintTimer)
        this.rightSwipeHintTimer = setTimeout(() => {
          this.lastRightSwipeAt = 0
          this.rightSwipeHintTimer = null
          this.statusText &&
            this.statusText.setProperty(prop.TEXT, this.currentStatusLabel)
        }, 1500)
        return true
      },
    })
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
      w: px(190),
      h: px(24),
      text: 'WRISTMIND',
      color: 0x9c82ff,
      text_size: px(18),
      align_h: align.LEFT,
      align_v: align.CENTER_V,
    })
    createWidget(widget.TEXT, {
      x: px(34),
      y: px(38),
      w: px(190),
      h: px(22),
      text: 'голос рядом',
      color: 0x8991aa,
      text_size: px(16),
      align_h: align.LEFT,
      align_v: align.CENTER_V,
    })
    createWidget(widget.FILL_RECT, {
      x: px(263),
      y: px(22),
      w: px(107),
      h: px(32),
      radius: px(16),
      color: 0x171c2c,
    })
    createWidget(widget.TEXT, {
      x: px(263),
      y: px(22),
      w: px(107),
      h: px(32),
      text: '● FIX 0.3.5',
      color: 0x6be8b8,
      text_size: px(14),
      align_h: align.CENTER_H,
      align_v: align.CENTER_V,
    })
    createWidget(widget.FILL_RECT, {
      x: px(18),
      y: px(73),
      w: px(354),
      h: px(116),
      radius: px(28),
      color: 0x141827,
    })
    this.statusText = createWidget(widget.TEXT, {
      x: px(36),
      y: px(88),
      w: px(318),
      h: px(42),
      text: 'Поиск телефона…',
      color: 0xe7e9f3,
      text_size: px(24),
      align_h: align.CENTER_H,
      align_v: align.CENTER_V,
      text_style: text_style.WRAP,
    })
    this.timerText = createWidget(widget.TEXT, {
      x: px(36),
      y: px(126),
      w: px(318),
      h: px(52),
      text: '',
      color: 0x9c82ff,
      text_size: px(40),
      align_h: align.CENTER_H,
      align_v: align.CENTER_V,
    })
    this.recognizedText = createWidget(widget.TEXT, {
      x: px(24),
      y: px(196),
      w: px(342),
      h: px(31),
      text: 'Распознано: —',
      color: 0x8991aa,
      text_size: px(13),
      align_h: align.LEFT,
      align_v: align.CENTER_V,
      text_style: text_style.WRAP,
    })
    createWidget(widget.TEXT, {
      x: px(24),
      y: px(229),
      w: px(342),
      h: px(20),
      text: 'ОТВЕТ',
      color: 0x717a98,
      text_size: px(14),
      align_h: align.LEFT,
      align_v: align.CENTER_V,
    })
    createWidget(widget.FILL_RECT, {
      x: px(18),
      y: px(252),
      w: px(354),
      h: px(92),
      radius: px(24),
      color: 0x111522,
    })
    this.answerText = createWidget(widget.TEXT, {
      x: px(36),
      y: px(262),
      w: px(318),
      h: px(72),
      text: 'Короткий ответ появится здесь',
      color: 0xdfe3f0,
      text_size: px(19),
      align_h: align.LEFT,
      align_v: align.CENTER_V,
      text_style: text_style.WRAP,
    })
    this.actionButton = createWidget(widget.BUTTON, {
      x: px(32),
      y: px(364),
      w: px(326),
      h: px(66),
      radius: px(30),
      normal_color: 0x6f56d6,
      press_color: 0x5138a8,
      text: 'Подключение…',
      text_size: px(23),
      color: 0xffffff,
      click_func: () => this.onAction(),
    })
    this.connectToPhone()
  },

  connectToPhone() {
    this.cleanupBle()
    this.setState('CONNECTING', 'BLE API · запуск…')
    this.scannedDeviceCount = 0
    this.scanElapsed = 0
    this.scannedAddresses = {}
    const attempt = ++this.connectAttempt
    this.timerText && this.timerText.setProperty(prop.TEXT, '0 с')
    this.bleTimer = setInterval(() => {
      if (attempt !== this.connectAttempt || this.state !== 'CONNECTING') return
      this.scanElapsed = Math.min(15, this.scanElapsed + 1)
      this.timerText &&
        this.timerText.setProperty(prop.TEXT, `${this.scanElapsed} с`)
      this.setStatus(
        `BLE OK · ${this.scanElapsed}/15 · найдено ${this.scannedDeviceCount}`,
      )
      if (this.scanElapsed >= 15) {
        this.stopBleScan()
        this.setState(
          'ERROR',
          `Телефон не найден · устройств: ${this.scannedDeviceCount}`,
        )
      }
    }, 1000)
    try {
      this.isScanning = mstStartScan((device) => {
        if (attempt !== this.connectAttempt) return
        const addressKey = bufferKey(device.dev_addr)
        if (!this.scannedAddresses[addressKey]) {
          this.scannedAddresses[addressKey] = true
          this.scannedDeviceCount += 1
        }
        const services = device.service_uuid_array || []
        const serviceData = device.service_data_array || []
        const found =
          services.some((uuid) => compactUuid(uuid) === SERVICE_UUID_COMPACT) ||
          services.some(isAdvertisingUuid) ||
          serviceData.some(hasWristMindMarker)
        if (!found) return
        this.stopBleScan()
        this.deviceAddress = device.dev_addr
        this.setStatus('Телефон найден · подключение…')
        const started = mstConnect(device.dev_addr, (result) => {
          if (attempt !== this.connectAttempt) return
          if (result.connected !== 0) {
            this.setState('ERROR', `Телефон не подключён · код ${result.connected}`)
            return
          }
          this.connectId = result.connect_id
          this.prepareProfile(device.dev_addr, result.connect_id)
        })
        if (!started) this.setState('ERROR', 'BLE не запустил подключение')
      })
      if (!this.isScanning) {
        this.setState('ERROR', 'Zepp OS не запустил BLE-сканирование')
      } else {
        this.setStatus('BLE API OK · поиск устройств')
      }
    } catch (error) {
      logger.log(`BLE scan error: ${error}`)
      this.setState('ERROR', 'Сбой BLE-сканирования Zepp OS')
    }
  },

  prepareProfile(deviceAddress, connectId) {
    this.setStatus('Настройка канала…')
    mstOnCharaNotification((first, uuidArg, dataArg) => {
      const event =
        typeof first === 'object'
          ? first
          : { profile: first, uuid: uuidArg, data: dataArg }
      if (
        event.profile === this.profileId &&
        compactUuid(event.uuid) === compactUuid(EVENT_UUID)
      ) {
        this.onFrame(utf8FromBuffer(event.data))
      }
    })
    mstOnCharaWriteComplete((first, uuidArg, statusArg) => {
      const event =
        typeof first === 'object'
          ? first
          : { profile: first, uuid: uuidArg, status: statusArg }
      if (event.profile === this.profileId && event.status !== 0) {
        this.setState('ERROR', `Команда не отправлена · код ${event.status}`)
      }
    })
    mstOnDescWriteComplete((first, uuidArg, descArg, statusArg) => {
      const event =
        typeof first === 'object'
          ? first
          : {
              profile: first,
              uuid: uuidArg,
              desc: descArg,
              status: statusArg,
            }
      if (event.profile !== this.profileId) return
      if (event.status === 0) this.setState('IDLE', 'Готов к записи')
      else this.setState('ERROR', `Уведомления BLE · код ${event.status}`)
    })
    mstOnPrepare((first, statusArg) => {
      const event =
        typeof first === 'object'
          ? first
          : { profile: first, status: statusArg }
      if (event.status !== 0) {
        this.setState('ERROR', `Ошибка BLE-профиля · код ${event.status}`)
        return
      }
      this.profileId = event.profile
      const cccd = new Uint8Array([1, 0]).buffer
      const started = mstWriteDescriptor(
        this.profileId,
        EVENT_UUID,
        CCCD_UUID,
        cccd,
        2,
      )
      if (!started) this.setState('ERROR', 'Не включились BLE-уведомления')
    })
    const profile = {
      pair: false,
      id: connectId,
      profile: 'WristMind',
      dev: deviceAddress,
      len: 1,
      list: [
        {
          uuid: true,
          size: 1,
          len: 1,
          list: [
            {
              uuid: SERVICE_UUID,
              permission: 0,
              len1: 2,
              len2: 2,
              list: [
                {
                  uuid: COMMAND_UUID,
                  permission: 32,
                  desc: 0,
                  len: 0,
                },
                {
                  uuid: EVENT_UUID,
                  permission: 32,
                  desc: 1,
                  len: 1,
                  list: [{ uuid: CCCD_UUID, permission: 32 }],
                },
              ],
            },
          ],
        },
      ],
    }
    setTimeout(() => {
      const started = mstBuildProfile(profile)
      if (!started) this.setState('ERROR', 'Не создан BLE-профиль')
    }, 80)
  },

  onFrame(frame) {
    logger.log(`RX ${frame}`)
    const parts = frame.split('|')
    if (parts[0] === 'S') {
      this.onStatus(parts[1])
    } else if (parts[0] === 'E') {
      this.setState('ERROR', `Ошибка: ${parts[1] || 'неизвестно'}`)
    } else if (parts[0] === 'T' && parts.length >= 4) {
      const sequence = Number(parts[1])
      const total = Number(parts[2])
      this.recognizedChunks[sequence - 1] = parts.slice(3).join('|')
      const received = this.recognizedChunks.filter(
        (chunk) => chunk !== undefined,
      ).length
      if (received === total) {
        this.recognizedText.setProperty(
          prop.TEXT,
          `Распознано: ${this.recognizedChunks.join('')}`,
        )
        this.recognizedChunks = []
      }
    } else if (parts[0] === 'A' && parts.length >= 4) {
      const sequence = Number(parts[1])
      const total = Number(parts[2])
      this.answerChunks[sequence - 1] = parts.slice(3).join('|')
      const received = this.answerChunks.filter((chunk) => chunk !== undefined).length
      if (received === total) {
        this.answerText.setProperty(prop.TEXT, this.answerChunks.join(''))
        this.answerChunks = []
      }
    }
  },

  onStatus(status) {
    const labels = {
      IDLE: 'Готов к записи',
      REC: 'Запись идёт',
      STOP: 'Запись остановлена',
      SEND: 'Отправка',
      PROC: 'Распознавание и ответ',
      READY: 'Готово',
      ERROR: 'Ошибка',
    }
    this.setState(status, labels[status] || status)
  },

  onAction() {
    if (this.state === 'IDLE' || this.state === 'READY') {
      this.answerText.setProperty(prop.TEXT, 'Слушаю ваш вопрос…')
      this.recognizedText.setProperty(prop.TEXT, 'Распознано: слушаю…')
      this.sendCommand('START')
      this.setStatus('Команда отправлена…')
    } else if (this.state === 'REC') {
      this.sendCommand('STOP')
      this.setStatus('Остановка…')
    } else if (this.state === 'ERROR') {
      this.connectToPhone()
    }
  },

  sendCommand(name) {
    this.commandSequence = (this.commandSequence + 1) % 100000
    const frame = `C|${this.commandSequence}|${name}`
    logger.log(`TX ${frame}`)
    if (this.profileId === null) {
      this.setState('ERROR', 'Нет BLE-профиля')
      return
    }
    const data = asciiBuffer(frame)
    mstWriteCharacteristic(this.profileId, COMMAND_UUID, data, data.byteLength)
  },

  setState(state, label) {
    this.state = state
    this.setStatus(label)
    const buttonLabels = {
      CONNECTING: 'Подключение…',
      IDLE: 'Начать запись',
      REC: 'Остановить',
      STOP: 'Подождите…',
      SEND: 'Отправка…',
      PROC: 'Обработка…',
      READY: 'Новый вопрос',
      ERROR: 'Повторить',
    }
    this.actionButton &&
      this.actionButton.setProperty(prop.TEXT, buttonLabels[state] || 'Подождите…')
    if (state === 'REC') this.startTimer()
    else this.stopTimer()
  },

  setStatus(label) {
    this.currentStatusLabel = label
    this.statusText && this.statusText.setProperty(prop.TEXT, label)
  },

  startTimer() {
    this.stopTimer()
    this.startedAt = Date.now()
    this.updateTimer()
    this.timerHandle = setInterval(() => this.updateTimer(), 1000)
  },

  updateTimer() {
    const seconds = Math.floor((Date.now() - this.startedAt) / 1000)
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    const value = `${minutes}:${rest < 10 ? '0' : ''}${rest}`
    this.timerText.setProperty(prop.TEXT, value)
  },

  stopTimer() {
    if (this.timerHandle) {
      clearInterval(this.timerHandle)
      this.timerHandle = null
    }
    if (this.timerText && this.state !== 'REC') {
      this.timerText.setProperty(prop.TEXT, '')
    }
  },

  stopBleScan() {
    if (this.isScanning) {
      try {
        mstStopScan()
      } catch (error) {
        logger.log(`BLE stop scan error: ${error}`)
      }
      this.isScanning = false
    }
    if (this.bleTimer) {
      clearInterval(this.bleTimer)
      this.bleTimer = null
    }
  },

  cleanupBle() {
    this.stopBleScan()
    try {
      if (this.profileId !== null) mstDestroyProfileInstance(this.profileId)
      if (this.connectId !== null) mstDisconnect(this.connectId)
      mstOffAllCb()
    } catch (error) {
      logger.log(`BLE cleanup error: ${error}`)
    }
    this.profileId = null
    this.connectId = null
    this.deviceAddress = null
  },

  onDestroy() {
    this.connectAttempt += 1
    this.stopTimer()
    if (this.rightSwipeHintTimer) clearTimeout(this.rightSwipeHintTimer)
    this.cleanupBle()
    resetPageBrightTime()
    resetDropWristScreenOff()
    resetPalmScreenOff()
  },
})
