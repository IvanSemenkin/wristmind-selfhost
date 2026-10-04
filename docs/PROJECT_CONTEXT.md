# WristMind — контекст проекта

Обновлено: 2 октября 2026. Этот документ описывает фактическую систему, а не только исходный MVP. Для того, что проверялось последним, открывайте [CURRENT_STATE.md](CURRENT_STATE.md).

## Назначение

WristMind — персональный AI-ассистент с режимами работы, отдельными базами знаний и чатами, привязанными к режимам. Основной пользовательский сценарий — краткий чат прямо на Xiaomi Watch 2; управление режимами, источниками и устройствами происходит в веб-панели. Телефон не нужен для прямого сценария часов, но может быть сетевым посредником.

Публичная точка входа: `https://wm.xspase.ru`.

## Карта системы

```text
 Xiaomi Watch 2                         Web panel / TWA
  :wear                                  web/ + :panel
  direct HTTPS ───────────────────┐       HTTPS /v1
  (preferred)                     │          │
                                  ▼          ▼
                       public VPS: TLS / reverse proxy
                       / → wristmind-web (systemd)
                       /v1 → loopback :18080
                                  │
                       reverse SSH tunnel (Orange Pi → VPS)
                                  │
                                  ▼
 Orange Pi (`ssh my-server`) — Docker Compose
 nginx → FastAPI api ── PostgreSQL + pgvector
             │
             └── worker → OpenRouter / GigaChat / OCR / embeddings
                            └── SearXNG (only when source search is requested)

 Optional fallback:
 Xiaomi Watch 2 ⇄ Wearable Data Layer ⇄ :phone companion ⇄ HTTPS VPS
                   (Bluetooth or Wi-Fi is selected by Google Play services)
```

The reverse tunnel and service names are operational facts, not an API contract: inspect the active VPS and Orange Pi state before deploying. No secret, token or private key belongs in the repository.

## Repository modules

### Backend: `server/`

FastAPI + async SQLAlchemy backend.

- `src/wristmind_server/main.py` exposes REST/SSE API and creates jobs.
- `db_models.py` holds durable data: devices, one-time pairing codes, global prompt, modes, chats, messages, sources/chunks, jobs and job events.
- `worker.py` claims queued work and processes `ANSWER` and `INGEST` jobs.
- `providers.py` routes streaming answers, embeddings, OCR/Vision and STT integrations to mock, OpenRouter or GigaChat providers.
- `knowledge.py` extracts documents, chunks them and builds per-mode context.
- `compose.yaml` defines PostgreSQL 16 + pgvector, API, worker, nginx, routing helper, private SearXNG and optional reverse-tunnel service. SearXNG has no published port and sits on its own bridge subnet; its source-address routing rule sends its external traffic through the host's main/direct route, independently of model-provider VPN rules.

The production Docker volumes hold PostgreSQL and private uploaded source files. Do not delete/recreate them as part of a code deployment.

### Web panel: `web/`

The active panel is React 19 + Vite under `web/src/`. Its application shell is `src/app/App.tsx`, the API adapter is `src/services/ApiWristMindService.ts`, and chat/source UI lives in `src/pages/chats/`. The older Vinext files under `web/app/`, `web/components/wristmind/` and `web/lib/wristmind-api.ts` remain in the checkout as historical code; they are not the active panel.

Routes are browser-history routes, not distinct backend pages:

| URL | Meaning |
| --- | --- |
| `/main` | overview/dashboard |
| `/chats` / `/chats/{id}` / `/chats/new` | list, selected chat, new-chat mode selection |
| `/modes` | mode creation, edit and soft delete |
| `/knowledge` | mode-scoped source list, upload, detail, reprocess and delete |
| `/settings` | global prompt, classifier prompts, response settings and pairing code |
| `/devices` | connected devices |

The web panel stores only its administrative device session in `localStorage` (`wristmind.web.session`). On first use it enrolls through a one-time pairing code (`/v1/devices/admin/enroll-by-code`); bootstrap-secret enrollment remains an API fallback. Revoked devices are filtered from the panel UI.

The panel has desktop sidebar and mobile top/bottom navigation layouts. Chat streaming happens through the job SSE endpoint; a selected chat uses a constrained full-height workspace so the composer is not covered by mobile navigation.

### Android shared code: `android/core/`

`DeviceConfigStore` keeps server URL/device token in encrypted Android storage. `WristMindApi` is the shared Kotlin REST/SSE client. `ProxyJson.kt` and `ProxyProtocol.kt` implement the Wearable Data Layer envelope and parser shared by phone and watch.

### Wear OS client: `android/wear/`

The active chat application for Xiaomi Watch 2, Kotlin + Wear Compose Material 3. It is standalone: normal requests go straight from the watch to the public VPS. Its key classes are:

- `WearApp.kt` — swipe-dismissable routes: pairing, chat, history, mode picker, draft editor and full answer.
- `WearChatScreen.kt` — round-screen chat layout, compact composer, editor UX and typing indicator.
- `WearViewModel.kt` — state, pairing, local restoration, speech state, submission, SSE consumption and bounded recovery.
- `WearGateway.kt` — direct HTTPS route and retry policy.
- `WearDataLayerGateway.kt` — proxy route plus direct-first failover.
- `WearLocalStore.kt` — active chat, drafts, pending request/job/cursor persistence.
- `WearSpeechRecognizer.kt` — watch system speech recognizer with partial results.
- `WearConfigService.kt` — receives shared configuration from the phone.

### Android companion: `android/phone/`

Intentionally narrow companion app, not a mobile copy of the panel or chat. Its UI exposes only pairing code entry, current status/watch reachability, pause/resume, remove watch and logout.

`WearProxyService` is a `WearableListenerService`. It receives proxy RPCs from the watch, reassembles chunks, performs the corresponding VPS request, caches multipart responses and returns SSE events as short windows. Pause rejects requests immediately with `PAUSED`; it does not erase the device token. `WatchLink` synchronizes configuration over `/wristmind/config/v1`.

### TWA panel wrapper: `android/panel/`

Trusted Web Activity package `dev.wristmind.panel`. It opens `https://wm.xspase.ru/main` and uses the site’s `/.well-known/assetlinks.json` plus its Android `asset_statements` for verification. It wraps the web panel; it is not the companion app.

### Legacy code

- `watch/` is the old Zepp OS/Amazfit Bip 6 BLE implementation.
- `android/app/` is the old phone app and is not in the active Gradle settings.
- Historical BLE protocol/runbook files describe those modules. Keep them for reference; do not merge their transport/UI into the Wear OS path.

## Backend domain model and behavior

### Devices and enrollment

Each device has `kind` (`PHONE`, `WATCH`, `WEB`), an owning user, administrative flag, hash of bearer token, timestamps and `revoked_at`. Raw bearer tokens are returned only while enrolling and are not persisted by the server. The administrator can create a normal user and issue a time-limited code specifically for that user; enrollment binds a new watch or web panel to that owner.

Normal users see only their own chats and knowledge sources. Modes are administrator-managed shared templates: a normal user may select an active mode for a chat or source, but cannot create, alter or delete modes, settings, pairing codes, devices or users.

An admin creates a time-limited numeric pairing code. A watch or phone exchanges that code for its own `WATCH` device token; a web panel uses the same code to create an administrative `WEB` session. Revocation is soft (`revoked_at`) and a device can revoke itself.

### Modes, chats and messages

A mode contains name, description, color/icon, mode system prompt and selected response model. Mode deletion is soft. A chat stores `mode_id` and a mode-name snapshot; the API never exposes changing a chat’s mode. If the mode has been deleted, the existing chat survives and the worker falls back to the default model without the deleted mode’s context.

Quick Chat is created through `POST /v1/chats/quick` with an internal universal mode. It is deliberately hidden from normal mode selectors but can appear in chat history.

Message submission is asynchronous. An `ANSWER` request is idempotent by its `client_request_id` within its chat, even when direct and proxy requests reach the API through different device tokens. The API saves the user message plus an empty assistant placeholder, then returns a queued `Job`. AUTO uses a local-first router to choose `none`, `chat_sources`, `web` or `deep_web`; RESEARCH adds bounded answer verification without forcing internet access. The worker may search through private SearXNG and open selected public pages with network and size limits. If search is unavailable, the answer degrades gracefully. See [SEARCH_REDESIGN.md](SEARCH_REDESIGN.md) for the current source lifecycle.

### Jobs and SSE

The worker updates jobs and persists every event in `job_events`:

1. `state: context` and, when relevant, search/research progress states;
2. `state: generating`;
3. one or more `delta` events;
4. terminal `complete`, or `error`.

`GET /v1/jobs/{id}/events?after=N` streams stored/new events and lets clients resume from a numeric cursor. The assistant message is updated as chunks arrive; upon completion its provider/model/timings are persisted and an initially named `Новый чат` takes the first question as its title.

### Knowledge ingestion and current retrieval

Sources belong to exactly one mode. Upload accepts a processing mode (`OCR` or `VISION`), stores the original file privately and schedules an `INGEST` job. PDF/image OCR uses `pypdf`/Tesseract; `VISION` first asks the configured model and falls back to OCR only when providers are mocked or Vision fails under mock conditions. Documents are chunked near 4,000 characters and embedded.

At answer time, the worker retrieves only ready, non-deleted sources of the chat’s mode:

- when total source size is at or below `full_context_threshold_tokens` (default 12,000), all chunks are included;
- otherwise it embeds the question and ranks chunks by 75% cosine similarity + 25% lexical overlap, filling `retrieval_context_budget_tokens` (default 6,000).

Chat-scoped Working Sources are separate from this mode knowledge base. They are retrieved for the current chat only and ranked for the current question. A lightweight Referenced Source records a searched URL used in an answer; it is not a RAG document. The new search flow never promotes either source to the existing interchat knowledge base automatically.

### Providers and response policy

Configured model identifiers are `provider:model`. Current defaults include OpenRouter Gemini 2.5 Flash Lite, DeepSeek V4 Flash, Qwen3.8 Flash and GigaChat-2; Quick Chat defaults to Qwen3.8 Flash. DeepSeek answers come from the official DeepSeek API (`https://api.deepseek.com`, model `deepseek-flash`), not OpenRouter; the former OpenRouter catalog id is kept only as an alias that routes to that API so existing modes, chats and `WRISTMIND_DEFAULT_MODEL_ID` / `WRISTMIND_QUICK_CHAT_MODEL_ID` keep working. The global prompt asks for the user’s language, concise direct answers and no invented facts. There is no special server-side “translation output only” rule beyond prompt/model behavior.

The GigaChat OAuth cache normalizes millisecond expiration values and, on an explicit `Token has expired` reply, refreshes once and retries the request once. TLS verification for GigaChat remains an explicit environment setting because the legacy OAuth chain may need a locally installed CA.

## API summary

All protected routes use `Authorization: Bearer <device token>`.

| Area | Routes |
| --- | --- |
| Health and STT | `GET /health`, `POST /v1/stt` |
| Device lifecycle | `POST /v1/devices/admin/enroll`, `POST /v1/devices/pairing-codes`, `POST /v1/devices/enroll`, `POST /v1/devices/admin/enroll-by-code`, `GET /v1/devices`, `DELETE /v1/devices/self`, `DELETE /v1/devices/{id}` |
| Config/modes | `GET /v1/models`, `GET/PUT /v1/settings`, `GET/POST /v1/modes`, `PATCH/DELETE /v1/modes/{id}` |
| Chats/messages | `GET/POST /v1/chats`, `POST /v1/chats/quick`, `PATCH/DELETE /v1/chats/{id}`, `GET/POST /v1/chats/{id}/messages`, `GET /v1/chats/{id}/sources` |
| Jobs | `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/events?after=N` |
| Knowledge | `GET/POST /v1/knowledge`, `GET /v1/knowledge/{id}`, `POST /v1/knowledge/{id}/reprocess`, `DELETE /v1/knowledge/{id}` |

## Wear-to-phone proxy protocol

Implemented protocol v1 uses a JSON envelope with `protocolVersion`, UUID `requestId`, operation, zero-based part index/count, full byte count, full-payload SHA-256 checksum and base64 part. Response fields include status, HTTP status, error code and retryability.

| Constraint | Value |
| --- | --- |
| Source bytes per part | ≤ 48 KiB |
| Parts / payload | ≤ 64 / ≤ 3 MiB |
| One RPC | 25 seconds |
| Full assembly | 120 seconds |
| Cached outgoing response parts | 5 minutes |
| SSE proxy window | 6 seconds |

Duplicate identical parts are idempotent; conflicting parts are rejected. The watch can ask once for a missing response part. For `send_message`, the same request ID becomes the server `client_request_id`. Direct HTTPS failure is defined as an `IOException` that is not an HTTP/API exception; only those errors enter proxy fallback.

## Wear UX contract

The current UI is described exhaustively in [DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md). In short:

- history/new-chat lives behind a small upper-left corner action, not a full header or visible `+`;
- a mode is selected before creating a normal chat and never shown/changed inside the active conversation;
- user messages are right-aligned, assistant messages left-aligned; assistant feed previews are three lines and only true overflow opens the full Markdown screen;
- chat composer stays one line; focused draft editing is a separate fullscreen preview with mic/keyboard/clear controls;
- keyboard Done returns to preview, the preview check returns to chat, and chat Send alone submits;
- partial speech updates the same draft and never submits;
- a compact three-dot assistant bubble replaces verbose processing labels; errors retain the draft and signal through the history action;
- the chat list is hoisted above editor navigation, preserving scroll position when returning.

## Branding

Canonical SVG assets are in `assets/branding/`. The same mark is used for website favicon/PWA icons, panel wrapper and Wear assets. Wear colors/tokens are defined in `android/wear/.../WearTheme.kt`; web panel has its own denser administrative treatment.
