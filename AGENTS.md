# WristMind: working map

WristMind is a personal AI assistant with a web control panel, a standalone Wear OS chat client, an optional Android companion/proxy, and a FastAPI backend. The public panel and API base are `https://wm.xspase.ru`; public API routes are under `/v1`.

## Read first

- [Project context](docs/PROJECT_CONTEXT.md) — architecture, data flow, API and runtime topology.
- [Current state](docs/CURRENT_STATE.md) — implemented work, unresolved work and latest verification.
- [Design system](DESIGN_SYSTEM.md) — shared brand rules and the authoritative Wear UI decisions.
- [Wear product specification](docs/WEAR_OS_APP_SPEC.md) — product intent; when it conflicts with current behavior, follow `CURRENT_STATE.md` and code.
- [Wear proxy protocol](docs/WEAR_OS_PROTOCOL_DRAFT.md) — background/design draft; the implemented v1 contract is in `android/core/.../ProxyProtocol.kt`.
- [Self-hosting vision](docs/SELF_HOSTING_VISION.md) — target third-party experience: server install, watch install through the companion, and the server management menu. Vision only; nothing there is implemented yet.

Some older documents (`README.md`, `docs/ARCHITECTURE.md`, `docs/MVP_RUNBOOK.md`, `docs/PROTOCOL.md`) describe the original Poco F6 + Amazfit BLE MVP. They are historical and **not** the architecture of the active Wear OS client.

## Modules

| Location | Purpose | Status / boundary |
| --- | --- | --- |
| `server/` | FastAPI API, async SQLAlchemy models, worker, provider adapters, knowledge ingestion/retrieval | Active backend. Preserve database and private-file volumes. |
| `web/` | React/Vinext control panel, served as the site and installable web app | Active administration surface. |
| `android/core/` | Shared Kotlin API client, encrypted device config, Data Layer proxy JSON/protocol | Shared by `:wear` and `:phone`. |
| `android/wear/` | Standalone Xiaomi Watch 2 Wear OS client | Primary chat client. Direct HTTPS is preferred; proxy is fallback. See `android/wear/AGENTS.md`. |
| `android/phone/` | Minimal Android companion | Pairing/status/pause/remove/logout and Wearable Data Layer proxy only; never add a second chat UI here. |
| `android/panel/` | Trusted Web Activity wrapper for the web panel | Opens `/main` on `wm.xspase.ru`; app-link verification must match the deployed `assetlinks.json`. |
| `android/app/` | Old Android implementation | Legacy/user-owned; it is not included by Gradle. Do not mix it with `:phone` or `:wear`. |
| `watch/` | Amazfit Bip 6 / Zepp OS implementation | Legacy. Keep it intact and separate from Wear OS. |
| `assets/branding/` | WristMind mark and lockups | Canonical vector branding assets. |

## Non-negotiable rules

1. Start navigation/investigation with `codebase_memory_mcp` (`search_graph`, `get_architecture`, `get_code_snippet`, `search_code`, `trace_path`). Re-index if necessary; use direct reads only for the exact files being changed or when the graph cannot represent generated/untracked state.
2. The checkout is intentionally dirty. Preserve unrelated user work, especially `android/app/`, `watch/`, `dist/`, historic docs and external attachments. Do not use reset/checkout/clean to make it look tidy.
3. Do not commit, log, paste, or place provider credentials, bootstrap secrets, device tokens, or private server paths in documentation. Secrets belong in ignored `.env` / `local.properties` only.
4. Do not delete server-side user data, database rows, private source files, devices, modes or chats without explicit user authorization. API “delete” is generally soft-delete; maintain that property.
5. Keep the active Watch path direct HTTPS first. The Data Layer route is called **“proxy through Wearable Data Layer”**, not “Bluetooth proxy”: Google Play services may use Bluetooth or Wi-Fi.
6. A chat's mode is immutable. Quick Chat is built-in/universal and hidden from ordinary mode lists. Do not surface internal processing stage labels in the Wear chat.

## Local verification

Use JDK 21 to run Gradle; Kotlin/Java bytecode target stays 17. JDK 25 is known incompatible with the current toolchain. On Windows, a subst drive such as `W:\android` may be needed when Gradle has trouble with the Cyrillic repository path.

```powershell
# Android (from android/)
$env:JAVA_HOME = '<path to JDK 21>'
.\gradlew.bat :core:test :wear:testDebugUnitTest :wear:assembleDebug
.\gradlew.bat :phone:assembleDebug :panel:assembleDebug

# Server (from server/; use the local venv appropriate to the workstation)
python -m pytest -q

# Web (from web/)
npm run lint
npm run build
```

For Wear visual changes, additionally install `wear-debug.apk` into the round `WristMind_Wear_466` AVD and inspect empty, paired, long-answer, draft, listening, generation and error states. An emulator cannot validate real-watch microphone availability, real network changes, or physical one-hand ergonomics.

## Runtime and deployment guardrails

- Orange Pi is reached as `ssh my-server` and runs the backend Docker Compose stack. The public VPS terminates HTTPS and proxies the site/API; see `PROJECT_CONTEXT.md` before modifying either side.
- Deploy API/worker changes only after the relevant test suite and a health check. The existing server checkout/path and service status must be inspected at deployment time; older runbooks contain historic paths.
- The public web service is deployed separately from the backend. Build/lint success alone does not deploy it.

## Scope conventions

- Put product/architecture decisions in `docs/`; put immediate truth and handoff details in `docs/CURRENT_STATE.md`.
- Update `DESIGN_SYSTEM.md` whenever a user-visible design decision changes.
- Keep legacy documentation marked as legacy instead of silently rewriting historical protocols.
