# WristMind Design System

## 1. Brand foundation

WristMind is a quiet, direct assistant: dark, focused, fast, and readable at a glance. The Wear visual signature is a cool graphite OLED canvas with a clean signal blue: brighter and clearer than the former muted aqua, but restrained enough for long chats. Blue is semantic, not an atmospheric wash. The watch experience must feel native to Wear OS, not like a reduced phone screen.

Launcher icons share the watch's abstract W and wireless-signal motif in electric blue, cyan and ice blue on deep graphite. The watch retains its precise vector icon; the phone companion and panel use separately generated PNG artwork inside adaptive icons. The companion keeps the bare mark; the panel adds restrained corner accents. Keep the artwork centered inside the adaptive safe area, with an opaque dark edge so launcher masks do not reveal a white plate. The panel PWA PNG icons use the panel variant.

The panel's Trusted Web Activity is immersive only when Digital Asset Links verifies the installed APK's signing certificate against `/.well-known/assetlinks.json`. If verification fails, the browser deliberately shows a URL toolbar; do not try to conceal it with CSS or WebView tricks.

## 2. Product surfaces

- Wear OS is the primary conversational surface and the strictest layout target: Xiaomi Watch 2, circular 466×466 px.
- The web panel is the administrative surface. It shares the logo and brand colors, but not the watch interaction patterns.
- Its overview summary includes an all-time `Запросы к ИИ` counter alongside modes, chats and devices; it counts answer requests, not internal maintenance jobs. The daily trend, error share, 14-day chart and per-mode load use real server aggregates and refresh while the overview is open. Device counts distinguish valid access from total enrolled devices, not network presence; unavailable token usage is not shown as a measured zero.
- The Android companion is infrastructure UI. It should remain minimal and should not reproduce chat or panel features.
- Its setup input accepts exactly six digits and opens a numeric keypad. Its health view names both the server reachability and watch reachability, offers a manual refresh, and separates destructive device disconnection from clearing local phone data.
- On the web panel, mobile confirmation and document-upload dialogs open as full-width bottom sheets and must never create horizontal page overflow. The upload sheet keeps its action area visible while its form scrolls independently. Core buttons, inputs, and list controls retain at least a 44 px touch target on mobile while desktop controls stay compact.
- The device-pairing dialog treats code issuance as a recoverable network operation. While a request is pending its primary action shows progress; an ambiguous weak-network failure keeps any existing live code, leaves a persistent inline explanation, and offers `Повторить`. Retries recover the same server-issued code instead of silently creating several codes.
- The devices page shows only access-bearing devices by default. Revoked devices remain auditable behind an explicit history toggle, and the main count reports access-bearing devices rather than historical enrollment rows. Service identities such as the Telegram bot are labelled as integrations, not as web panels.
- The administrator-only people and device controls live within `Настройки`, not as a sixth primary-nav item. Each destructive action has its own confirmation dialog: disconnecting one device explains the immediate loss of access; disabling a user explains that devices and unused codes are revoked while chats and knowledge stay retained.
- In chat and knowledge lists, the explicitly labelled `Удалить чат` / `Удалить источник` action runs immediately without a confirmation dialog or a typed phrase. Success and failure are reported with the existing toast; only a successful deletion removes the item from the view. This exception does not change confirmation for modes, people or devices.
- Operational classifier prompts that may need urgent correction also live in `Настройки`. Related prompts are grouped in execution order, use the existing page-level unsaved-changes bar, and never require the administrator to preserve runtime placeholders: the server appends conversation and source context itself.
- Long user-created names are truncated in list rows and may wrap only inside explanatory dialog text. While a web-chat answer is being generated, the empty assistant bubble shows three softly staggered aqua dots until the first text arrives; reduced-motion settings disable the perpetual motion.

## 3. Design concept

The watch chat is **a conversation canvas with one stable lower editor action**. The corner history action floats over the canvas, while the first message receives only the clearance required to avoid it; there is no visual header. Keyboard and voice editing live on a focused full-screen route. Voice creates an editable draft and never sends on its own.

## 4. Color tokens

| Token | Value | Use |
| --- | --- | --- |
| `background` / Ink | `#070B12` | cool OLED canvas |
| `surfaceContainerLow` | `#0F151F` | subtle grouped regions |
| `surfaceContainer` / Panel | `#161E2A` | assistant messages |
| `surfaceContainerHigh` / Panel Raised | `#1F2A38` | draft and elevated controls |
| `primary` / Signal Blue | `#69AEFF` | compact primary action and active signal |
| `primaryDim` | `#438DE3` | restrained active state |
| `primaryContainer` | `#1B4F86` | clearly blue user messages and selection |
| `onBackground`, `onSurface` | `#F5F7FA` | primary text |
| `onSurfaceVariant` / Soft Text | `#B2BDCA` | secondary text |
| `error` / Danger | `#FFB4AB` | error dot and destructive feedback |

Color is semantic. Signal Blue marks the action currently worth taking and distinguishes the user's side of the conversation; it is not decoration. Error is shown as a small persistent signal, with the full description exposed to accessibility services.

## 5. Contrast

Measured WCAG contrast ratios for the implemented pairs:

- primary text on background: 18.36:1;
- secondary text on background: 10.35:1;
- primary text on assistant surface: 15.61:1;
- user-message text on primary container: 7.78:1;
- Signal Blue on background: 8.54:1;
- secondary text on raised surface: 7.62:1.

All core text pairs exceed AA. Icons must use the same semantic foreground tokens rather than raw colors.

## 6. Typography

Use Wear Compose Material 3 typography and the Wear OS system font. Conversation text uses `bodyMedium`; compact metadata uses `bodySmall` or `labelSmall`; screen headings use `titleMedium`. Do not hardcode text sizes in feature components. Wear platform type sizes may be smaller than generic web minimums because they follow the platform type scale and are validated with Wear font-scale previews.

The in-chat processing-status pill is denser than ordinary metadata: its label uses 90% of the Wear `labelSmall` token, stays on one line, and ellipsizes only when the available round-screen width is exhausted. Accessibility semantics retain the complete status text. Answer and message typography is unchanged.

## 7. Shape language

Use Material 3 component shapes. Conversation cards are compact, soft containers rather than speech-balloon illustrations. Circular icon buttons are reserved for direct single-tap actions. Avoid outlines unless they encode focus or a real boundary; separation comes from tone and spacing.

## 8. Spacing and safe area

- Feed and composer consume `ScreenScaffold` content padding and `WindowInsets.safeDrawing`; for each edge use the larger value, never their sum.
- The lower editor action has no fixed outer side or bottom inset. Its base inset is the greater of scaffold and `safeDrawing` values; because Android does not expose the round glass curve as a window inset, circular action clearance has a token-derived floor of half `IconButtonDefaults.DefaultButtonSize`.
- The editor action is a compact 28 dp visual Wear M3 vector icon with a platform-aware invisible touch target. The editor microphone and clear controls render at 32 dp in their lower safe-area; tapping the draft opens the system keyboard.
- The feed bottom inset is the measured lower-action height. The action is an overlay sibling of the scroll scaffold rather than a list item, so message-list transformations never move or resize it.
- The chat feed stays lazy and round-screen-aware through `TransformingLazyColumn`, but message bubbles keep a stable measured height while scrolling. Per-frame edge height transforms remain available for short control lists and the full-answer reader header; applying them to every chat bubble or answer block causes avoidable text remeasurement and visible frame drops on physical hardware.
- Keep meaningful labels and controls away from the circular screen corners.
- Full-screen text uses the largest axis-aligned square contained by the round display: its inset is derived from the actual screen diameter, then compared with scaffold and system safe insets.
- Prefer `ScreenScaffold` padding, `TransformingLazyColumn`, and platform transformations over hand-authored curved geometry.

## 9. Chat anatomy

- A small upper-left corner action opens history and chat creation; there is no separate `+` or full-width header on the conversation screen. Its 32 dp visual surface uses 75% opacity (25% transparency), is lifted 2 dp within the mathematically safe round inset, and retains a compact 40 dp tap target.
- User messages align right in `primaryContainer`; assistant messages align left on `surfaceContainer`.
- Chat type uses a matched 1.8 dp vector pair everywhere it is shown: an outline message bubble for ordinary chats and the same bubble with an internal lightning mark for Quick Chat. Quick Chat never relies on color alone for identification.
- History keeps its controls light: ordinary controls, single-line chat cards, and the Quick Chat control share one 48 dp visual baseline and touch target. The wide New Chat control pairs with a square Quick Chat control using the same vertical placement and pill radius. Each chat card starts with a compact uppercase three-character mode badge, followed by a one-line ellipsized title; this replaces a second metadata row and keeps the 52 dp card compact.
- Seven rapid taps on the History heading explicitly export the watch's recent content-free transport diagnostics to the owner's Telegram bot. The heading looks unchanged; the export reports success or failure with a brief toast.
- A chat begins as `Новый чат` (or the Quick Chat default). The server queues one low-priority title job when its first user message is accepted. That job uses the cheapest configured text model and writes a two- or three-word topic title only once; answer generation always has priority and never waits for it.
- A normal tap on a history chat card opens it. Long press replaces that card with one compact red vector-trash `Удалить` action; a tap on it removes the card immediately without a confirmation dialog. There are no horizontal destructive gestures. The delete request is persisted locally and retried in the background until the server accepts it, so a temporary network failure never returns the card.
- Bubbles retain side breathing room with a compact 13 dp horizontal inset and 8 dp top / 6 dp bottom padding. Use `ButtonDefaults.IconSpacing` between bubbles rather than inflating message padding.
- Assistant messages show at most three lines in the feed. A completed response opens only after measured visual overflow; a live streamed response opens as soon as its first fragment appears, and the full reader continues updating with later fragments.
- Full answers render headings, emphasis, links, lists, quotes, code and common Markdown/TeX formulas as readable Wear-native blocks; raw Markdown markers and math delimiters must not be shown to the reader.
- Full-answer blocks form one vertical reading flow without an outer card per block. Keep 12 dp horizontal clearance and 4 dp vertical clearance around each block, plus 40 dp of empty space after the final content so the last lines can scroll above the round edge; quotes, code, formulas and tables retain their own existing block styling.
- The main chat has no `TextField` or send button: one compact lower message action opens the focused editor. Voice input is intentionally absent from the main chat and lives in the focused editor.
- The user can use the microphone or tap the draft to open the system keyboard. Keyboard `Done` only stores the current text and returns to the preview; it never exits to chat. The upper primary check confirms editing, returns to the same chat, and submits a non-blank draft immediately. An empty draft simply returns to chat.
- The full-screen editor is an edge-to-edge continuation of the screen background: no enclosing card, only text inside a diameter-derived circular safe area. It wraps the complete text and scrolls the whole content vertically without truncating the stored value.
- The full-screen preview keeps two small Wear M3 vector actions in its dedicated lower safe-area: clear and microphone. The microphone opens Wear OS's own recognition activity; a successful final transcript is appended to the captured draft and shown back on this same preview route. A tap on a word in the draft selects that whole word and opens the system keyboard, so the next typed text replaces only the mistaken word. Voice input never sends automatically. Confirmation is a separate 28 dp primary check near the safe upper-right edge, retaining a larger invisible touch target.
- While an answer is pending, running or streaming, the lower editor action keeps its size and position but shows a stop icon. Two taps within 700 ms request server cancellation; the existing answer text stays visible, then the normal editor action returns.
- Sending is optimistic on the watch: confirming a non-blank editor draft immediately clears it and stores the submitted text as a local pending draft. Restore it only when the send request itself fails or times out before acceptance; a slow accepted generation must not make the editor jump back.
- The watch keeps a durable message outbox with `queued`, `accepted`, `streaming`, `complete`, and `failed` stages. A completed stream is committed to the local conversation immediately; fetching the authoritative messages and generated chat title happens afterward in the background. On restart, an unfinished job resumes from its stored job ID and SSE cursor instead of making the user resend the message.

## 10. Voice, generation, and errors

- The system recognition activity returns only its final transcript to the editable draft; recognition never auto-sends or exposes an in-app recording/stop state.
- Before the first response fragment, the compact assistant bubble combines three softly staggered typing dots with one short, event-backed stage label. Delivery and local-first preparation distinguish `Отправляю запрос…`, `Запрос принят…`, `Подбираю материалы…`, and `Выбираю способ ответа…`. A reused chat source, deep search, page opening, material evaluation/extraction/save, and RESEARCH drafting/checking/refinement each have their own brief label only while that operation actually runs. Repeated searches, result reviews and page opens show their pass number from the second pass onward (`· 2`) so a continuing search is distinguishable from a stuck step. Search exhaustion/unavailability is stated honestly; the VPS fallback says `Резервный сервер отвечает…` and never claims to search. Router reasoning levels are not shown as actual provider effort until they control the provider call. The first response token replaces the indicator immediately, and internal protocol names or hidden model reasoning are never displayed.
- Errors do not replace the draft or add retry buttons. A red dot on the menu is the quiet persistent signal; the normal send path remains available.

## 11. Navigation and scrolling

Use standard Wear OS swipe-to-dismiss navigation. The app has one root `AppScaffold`; each destination owns a `ScreenScaffold`. Scrollable feeds use `TransformingLazyColumn` and `ScrollIndicator`. Do not nest vertical scroll containers except the intentional fullscreen draft text scroll. The chat list state and measured composer inset live above editor navigation, so confirming a draft/full answer restores the exact list position without scrolling or a one-frame layout jump. Reveal the latest item only when a new message appears, a pending question is inserted, or the first streamed answer becomes visible.

Persist modes, chat summaries, and recently opened message lists locally on the watch. Render this cache first, then refresh it in the background. Chat content is always scoped to its `chatId`; changing or creating a chat clears the old content before any network result may render.

## 12. Motion and feedback

Use platform component transformations where they do not destabilize dense conversational text, and use platform navigation motion. Motion must communicate position or state, not decorate. Favor immediate press feedback and short transitions. Respect the system animation-duration scale. The only custom perpetual motion is the active typing indicator: a 900 ms Material-eased scale/opacity wave with 120 ms staggering, removed as soon as response text appears.

## 13. Accessibility and localization

- Every icon-only action needs a localized content description.
- Error and processing state must be available through semantics even when visual text is omitted.
- Verify all chat variants with `WearPreviewDevices` and `WearPreviewFontScales`.
- Russian is the primary current UI language, but layouts must tolerate longer localized labels.
- Do not rely on color alone for interactive meaning; shape, icon, enabled state, and semantics must agree.

## 14. Reference decisions and quality gate

- The panel's Settings page exposes a Developer mode switch, off by default. Only while it is on, the desktop sidebar and the phone's “Ещё” sheet show “Промпты”. System and internal prompt editors live there; mode prompts remain editable in their mode screens regardless of this switch. The server enforces the same boundary for prompt updates. The fixed WristMind identity and developer attribution stay in code and are appended after editable answer instructions.
- The Devices page identifies a session by its browser/OS and a short identifier, and shows the last known public IP when available. A revoked entry can be removed from the visible list while its audit row remains stored.
- The mobile Overview tab is active on both `/` and `/main`.
- The web chat header carries exactly two roles: the chat's identity (title, plus one mode chip or the Quick Chat chip under it) and one action cluster on the right (a compact `Источники · N` control only when this chat actually has sources, and the overflow menu). Rename lives inside that menu, not as a standing header button. Message counts, relative update time and the mode knowledge-base source badge do not appear in the header: the base's emptiness is reported once, in the chat's empty state, where the `Загрузить` action sits next to it.
- The assistant message head (avatar and `WristMind` label) scrolls away with its own message on every breakpoint. It is never pinned inside the message scroll area, because a pinned head floats over the answer body while that message is still being read.

## 15. Knowledge context and token budget

- In the web mode list and mode detail, an eye action toggles whether the mode appears in the watch's mode picker. The hidden state is named `Скрыт на часах` and remains visible to the administrator. This action preserves the mode, its knowledge and existing chats; the trash action remains separate. The eye has a localized accessible label and a pressed state.
- The full-screen Wear draft has one persistent answer-mode control between Clear and Voice. Repeated taps switch only between neutral gray `AUTO` and red `RESEARCH`. `AUTO` delegates source choice to the server’s local-first router; it is not a promise of web search. `RESEARCH` adds bounded answer review/refinement, but likewise does not force internet retrieval. Research uses a distinct search-and-check icon as well as color, and every state has a localized accessible description. The chosen state remains selected after Send and across app restarts; each unfinished submission also stores its exact flags for safe retry. Research progress is shown only through high-level user-facing statuses—drafting, checking, and refining—never hidden chain-of-thought. Source links remain available through the server and web panel but are omitted from Wear answers.
- Web material used in a chat is handled without a save confirmation on the watch: a lightweight reference is recorded for displayed results, and a material that is genuinely needed for continued work may become a chat-local Working Source automatically. The separate existing interchat knowledge feature remains outside this flow. No automatic search result is added to it.
- In the web chat, the action under an answer identifies saved text, unverified older source metadata, or found links. In the source panel, a Working Source is explicitly labelled as saved to this chat and opens its complete saved text on demand, with a character count. A Referenced Source is labelled as a link only and says that its text was not saved for later use. These labels describe server state, never the assistant's claim in a generated answer.
- Markdown tables are converted on Wear into a bold compact header and vertical rows. Two-column rows use `→`; wider rows use `·`, so no horizontal table needs to fit a round display.
- Knowledge passed to the model is explicitly typed: `OCR` is text recognized from a source, while `VISION` is a model-generated description of an image or document and must never be treated as a verbatim quotation.
- The global prompt stays intentionally concise; stable behavioral constraints belong in application logic and structured context rather than being repeated in every model request.
- The web Settings screen exposes a history-context limit. Its default is 12 individual messages (not turns), with a safe range of 2–50, so an administrator can trade continuity for token cost without changing a prompt.
- On a phone, dialogs become safe-area-aware bottom sheets. Their grid tracks and preview rows use `minmax(0, 1fr)` / `min-w-0`, so long chat or document names truncate inside the sheet rather than widening it beyond the viewport.

The implementation follows the official guidance for [designing for round Wear OS screens](https://developer.android.com/design/ui/wear/guides/get-started/design-for-wearables), [Wear app layouts](https://developer.android.com/design/ui/wear/guides/surfaces/apps/layouts), [Compose lists](https://developer.android.com/training/wearables/compose/lists), and [Wear input methods](https://developer.android.com/training/wearables/user-input/wear-ime). Specific adopted decisions are the single scaffold hierarchy, edge-aware transforming list, platform scroll indicator, compact bottom actions, and a swipe-dismissable full-screen draft route that hands entry to the system IME.

Concept-test verdict: the blue-on-cool-graphite conversation canvas, asymmetric message alignment, floating history control, and stable voice-first composer remain recognizably WristMind when the product name is hidden. The weakest constraint is horizontal space when send appears on the smallest watch; it is intentionally handled with platform-size touch targets and a flexible field rather than shrinking the controls below Wear guidance.

Before accepting a Wear UI change:

1. Build with JDK 21 and Java/Kotlin target 17.
2. Compile device and font-scale previews.
3. Test on a round 466×466 AVD, including empty, draft, listening, processing, error, and long-answer states.
4. Confirm the primary action is reachable with one finger and no control clips at the circular edge.
5. Confirm no business-state transition changed as part of a visual refactor.
# Устройства и обзор

После отзыва доступа устройство сразу исчезает из интерфейса. Панель с отозванным токеном открывает подключение по новому коду. На обзоре нет блока «Требует внимания».
