# WristMind — запуск на Omarchy

Этот репозиторий содержит исходный код WristMind. Перед началом работы прочитай:

1. `AGENTS.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/CURRENT_STATE.md`
4. `DESIGN_SYSTEM.md`
5. `android/wear/AGENTS.md` — только при работе с Wear OS

## Быстрый старт

```bash
git clone https://github.com/IvanSemenkin/wristMind.git
cd wristMind
```

Установи JDK 21, Android SDK, Node.js, Python 3.12 и Docker/Compose. Для Android создай
`android/local.properties` заново с Linux-путём к SDK; этот файл не переносится из Windows.

```bash
cd android
export JAVA_HOME=/path/to/jdk-21
./gradlew :core:test :wear:testDebugUnitTest :wear:assembleDebug

cd ../server
python -m pytest -q

cd ../web
npm ci
npm run lint
npm run build
```

## Приватные файлы с флешки

Никогда не добавляй эти файлы в Git и не вставляй их содержимое в чат:

- `android/wear/google-services.json` — нужен для Firebase в debug/release-сборках Wear;
- `.env`/`server/.env`, если в них находятся ключи провайдеров для локального запуска сервера;
- Firebase service-account JSON, только если требуется развёртывать сервер и FCM;
- release signing key, если он появится для публикации Android-приложений.

После переноса проверь, что все эти файлы игнорируются через `git status --ignored`.

## Правила для Codex

- Рабочее дерево может быть грязным. Ничего не удаляй, не делай `git reset --hard`,
  `git checkout --` или `git clean`.
- Для навигации по коду сначала используй `codebase_memory_mcp`.
- Любые изменения Wear UI делай с `wear-compose-m3` и `ui-ux-kit`; repo содержит
  локальную копию `ui-ux-kit`. Если `wear-compose-m3` не установлен, сообщи об этом.
- Wear-клиент работает через direct HTTPS в первую очередь; телефон — только fallback
  через Wearable Data Layer, не отдельный чат-клиент.
- Перед серверным деплоем проверь тесты, состояние целевого сервера и health check.
  Данные PostgreSQL и приватные файлы на сервере нельзя удалять или пересоздавать.
- Источником текущей архитектуры являются перечисленные выше документы, а не старые
  материалы про Amazfit/Zepp в `watch/` и исторических документах.
