# Wear OS client instructions

`android/wear` is the standalone Xiaomi Watch 2 client. It is not the Amazfit/Zepp app in `../../watch/`, and it must not rely on the phone for the baseline chat flow.

## Read before changing UI or transport

- [../../DESIGN_SYSTEM.md](../../DESIGN_SYSTEM.md) — authoritative UI/UX decisions.
- [../../docs/CURRENT_STATE.md](../../docs/CURRENT_STATE.md) — current implementation and open validation work.
- [../../docs/WEAR_OS_APP_SPEC.md](../../docs/WEAR_OS_APP_SPEC.md) — product intent.
- `WearApp.kt`, `WearChatScreen.kt`, `WearViewModel.kt`, `WearGateway.kt`, `WearDataLayerGateway.kt`, `WearLocalStore.kt` — current behavior.

Use the installed `wear-compose-m3` skill for any Wear Compose Material 3 change. Keep one `AppScaffold`; every route owns a `ScreenScaffold`; scrolling content uses `TransformingLazyColumn` with the scaffold padding and guarded `ScrollIndicator`.

## Behavioral invariants

- Production base URL is supplied by `BuildConfig.WRISTMIND_BASE_URL` and defaults to `https://wm.xspase.ru/`; never replace it with a LAN/IP default.
- Pair with a one-time numeric code. The encrypted device token is persisted through `DeviceConfigStore`; the active chat, per-chat drafts, pending request ID/job/cursor are persisted through `WearLocalStore`.
- Startup restores the saved chat if it still exists, otherwise the latest API chat.
- Transport is `FailoverWearGateway`: direct HTTPS first; only I/O/network transport failures fall back to a reachable phone through Wearable Data Layer. HTTP status errors do not trigger fallback.
- Voice input is in-app SpeechKit dictation: mono PCM is uploaded during recording through direct HTTPS, with Wearable Data Layer proxy fallback. Confirmation appends normalized text to the editable draft; it never sends automatically. System recognizer code remains legacy/inactive.
- The compact chat composer opens a full-screen draft preview. Keyboard `Done` returns to that preview; only the upper check returns to chat, and only chat Send submits.
- Draft/editor navigation must preserve the hoisted chat list state. Only genuinely new messages/pending question/first stream token may auto-scroll.
- Assistant bubbles show at most three lines. Only actual visual overflow makes a persisted assistant answer tappable; full answer uses a scrollable Markdown screen.
- Processing uses the three-dot response bubble, not verbose status text. Errors preserve the draft and are shown by the menu error signal.
- Keep screen on for 180 seconds after interaction; retain it during recording/processing and release it in `onStop`.

## Proxy contract

`android/core/ProxyProtocol.kt` is the protocol source of truth. It has v1 envelopes, checksums, 48 KiB parts, 64-part/3 MiB ceilings, a 25-second RPC timeout, 120-second assembly timeout, five-minute response-part cache and six-second event windows. Preserve idempotent `requestId` behavior and the one retry for a missing response part.

## Verification

```powershell
$env:JAVA_HOME = '<path to JDK 21>'
.\gradlew.bat :core:test :wear:testDebugUnitTest :wear:assembleDebug
```

Use the round `WristMind_Wear_466` emulator for layout smoke testing. Keep `:phone` and `:wear` signed/package-compatible for Data Layer, but do not change application IDs or signing strategy casually.

## SelfHost copy override

This checkout uses a neutral HTTPS placeholder until the companion configures the user's server. Firebase is optional. Stage 7 adds a point-to-point installation configuration acknowledgement; the existing config/proxy/direct-first behavior stays intact. See ../../docs/COMPANION_SETUP.md. Never copy production credentials into this build.
