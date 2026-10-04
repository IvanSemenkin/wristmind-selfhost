# Запуск MVP

## 1. Тестовый сервер

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\uvicorn wristmind_server.main:app --host 0.0.0.0 --port 8000
```

Проверка: `http://127.0.0.1:8000/health`.

## 2. Android

1. Откройте каталог `android` в Android Studio.
2. В `android/local.properties` укажите `wristmind.baseUrl`:
   - реальный телефон и ПК в одной Wi-Fi сети: `http://IP_ПК:8000/`;
   - Android Emulator: `http://10.0.2.2:8000/`.
3. Соберите и установите debug-вариант.
4. Разрешите уведомления, микрофон и Bluetooth Nearby devices.
5. Нажмите «Запустить связь».

На HyperOS для устойчивой фоновой работы также разрешите автозапуск и выберите
для приложения режим батареи «Без ограничений».

## 3. Amazfit Bip 6

```powershell
cd watch
npm install
npx zeus build
npx zeus preview
```

Для `preview` нужен вход в Zepp Developer и включённый Developer Mode в Zepp App.
После запуска мини-приложение сканирует BLE-сервис `WristMind`, подключается и
показывает кнопку записи.

## Ограничения первого среза

- тестовый сервер не выполняет STT и возвращает детерминированную заглушку;
- используется встроенный микрофон телефона;
- Android 14+ не позволяет незаметно начать microphone foreground service из
  полностью остановленного приложения: сначала пользователь один раз запускает
  связь из UI;
- устойчивость одновременного BLE-соединения Zepp App и отдельного GATT-канала
  нужно подтвердить на конкретной прошивке Bip 6.

