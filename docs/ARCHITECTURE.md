# Архитектура

## MVP

```text
Amazfit Bip 6              Poco F6                       Test API
Zepp OS mini app           Android foreground service   FastAPI
      |                           |                          |
      | BLE: start_recording      |                          |
      |-------------------------->| AudioRecord.start()      |
      |<-- status: recording -----|                          |
      |                           |                          |
      | BLE: stop_recording       |                          |
      |-------------------------->| AudioRecord.stop()       |
      |<-- recording_stopped -----|                          |
      |<-- sending ---------------| POST /v1/audio/query     |
      |                           |------------------------->|
      |<-- processing ------------|                          |
      |                           |<-- transcript + answer ---|
      |<-- ready + shortAnswer ---|                          |
```

Часы являются BLE Central, телефон — BLE Peripheral/GATT Server. Аудио никогда
не проходит через часы или Zepp App. Все состояния на часах приходят от телефона,
а `ready` отправляется только после успешного ответа сервера.

## Следующие модули

1. `server/transcription` — провайдер STT.
2. `server/llm` — провайдер языковой модели.
3. `server/rag` — индексатор PDF, маршрутизатор AUTO/BOOK/NORMAL и retrieval.
4. `android/history` — Room.
5. `android/speech` — Android TTS и выбор аудиовыхода.
6. `android/audio` — выбор USB Type-C микрофона с fallback.

