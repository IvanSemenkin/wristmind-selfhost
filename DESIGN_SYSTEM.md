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

The per-answer source badge says `Текст сохранён в чат` only when that answer's
server metadata confirms a save and identifies the exact working source.
Previously available sources use `Материалы чата`; their count never confirms
that a newly requested text was saved. Referenced links use `Найдены ссылки`.

The watch chat is **a conversation canvas with one stable lower editor action**. History opens with a deliberate right-to-left swipe on the conversation canvas; there is no corner history button or visual header. Keyboard and voice editing live on a focused full-screen route. Voice creates an editable draft and never sends on its own.

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

The web-panel answer renderer displays Cyrillic labels after `_` as a complete
lower index: `c_ал` renders with both letters below the baseline. Single-letter
Latin/Greek variables with Cyrillic indices are recognized in ordinary prose
(including `(c_ал = 920)`) as well as explicit TeX formulas. Code, escaped
underscores, URLs and ordinary multi-letter identifiers remain literal.

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

- History and chat creation open after a deliberate right-to-left swipe on the chat screen. Navigation happens on release after at least 18% of the screen width and at least 36 dp of leftward travel; small, clearly vertical and rightward movements do not open history; diagonals up to 45 degrees can acquire the gesture, and subsequent curvature is allowed. The reverse swipe remains platform back navigation. The empty chat provides a swipe hint, and accessibility exposes an explicit history action. Removing the corner control also removes its extra message-list top clearance; scaffold safe padding remains. The error dot moves to the lower composer action.
- User messages align right in `primaryContainer`; assistant messages align left on `surfaceContainer`.
- Chat type uses a matched 1.8 dp vector pair everywhere it is shown: an outline message bubble for ordinary chats and the same bubble with an internal lightning mark for Quick Chat. Quick Chat never relies on color alone for identification.
- History keeps its controls light: ordinary controls, single-line chat cards, and the Quick Chat control share one 48 dp visual baseline and touch target. The wide New Chat control pairs with a square Quick Chat control using the same vertical placement and pill radius. Each chat card starts with a compact uppercase three-character mode badge, followed by a one-line ellipsized title; this replaces a second metadata row and keeps the 52 dp card compact.
- Seven rapid taps anywhere across the full-width History heading, including its status indicators and padding, open a hidden `Устройство` menu with `Код подключения` and `Отправить логи`. The touch area is at least 48 dp high; the heading looks unchanged. Opening the menu alone makes no request. Diagnostic export requires selecting its action and reports success or failure with a brief toast. The pairing action requests a new one-time code, displays it prominently with its remaining lifetime, and hides it when expired. Loading and retryable errors have their own screen states; leaving the screen clears the code from in-memory UI state. Only a server owner's watch may issue codes; ordinary users receive an explicit access error. Back navigation uses the standard Wear swipe.
- A chat begins as `Новый чат` (or the Quick Chat default). The server queues one low-priority title job when its first user message is accepted. That job uses the cheapest configured text model and writes a two- or three-word topic title only once; answer generation always has priority and never waits for it.
- A normal tap on a history chat card opens it. Long press replaces that card with one compact red vector-trash `Удалить` action; a tap on it removes the card immediately without a confirmation dialog. There are no horizontal destructive gestures. The delete request is persisted locally and retried in the background until the server accepts it, so a temporary network failure never returns the card.
- Bubbles retain side breathing room with a compact 13 dp horizontal inset and 8 dp top / 6 dp bottom padding. Use `ButtonDefaults.IconSpacing` between bubbles rather than inflating message padding.
- Assistant messages show at most three lines in the feed. A completed response opens only after measured visual overflow; a live streamed response opens as soon as its first fragment appears, and the full reader continues updating with later fragments.
- Full answers render headings, emphasis, links, lists, quotes, code and common Markdown/TeX formulas as readable Wear-native blocks; raw Markdown markers and math delimiters must not be shown to the reader.
- TeX inside bold or italic text is rendered as math too. A short standalone `\\frac{...}{...}` uses a stacked numerator, horizontal rule and denominator on Wear; longer expressions fall back to a wrapping linear fraction. The stacked form has one spoken description with numerator and denominator.
- Full-answer blocks form one vertical reading flow without an outer card per block. Keep 12 dp horizontal clearance and 4 dp vertical clearance around each block, plus 40 dp of empty space after the final content so the last lines can scroll above the round edge; quotes, code, formulas and tables retain their own existing block styling.
- The main chat has no `TextField` or send button: one compact lower message action opens the focused editor. Voice input is intentionally absent from the main chat and lives in the focused editor.
- After opening a full answer and returning to chat, the lower editor action keeps its 28 dp visual and position but accepts taps within a 60 dp area. Once a new message is sent, its touch area returns to the normal size. The stop action during generation keeps its existing two-tap target and behavior.
- The user can use the microphone or tap the draft to open the system keyboard. Keyboard `Done` only stores the current text and returns to the preview; it never exits to chat. The upper primary check confirms editing, returns to the same chat, and submits a non-blank draft immediately. An empty draft simply returns to chat.
- Opening the editor and confirming a draft always return through the chat route, including during the swipe animation back from a full answer. A previous answer reader must not become visible when the next answer arrives.
- The full-screen editor is an edge-to-edge continuation of the screen background: no enclosing card, only text inside a diameter-derived circular safe area. It wraps the complete text and scrolls the whole content vertically without truncating the stored value.
- The full-screen preview keeps two small Wear M3 vector actions in its dedicated lower safe-area: clear and microphone. The microphone opens Wear OS's own recognition activity; a successful final transcript is appended to the captured draft and shown back on this same preview route. A tap on a word in the draft selects that whole word and opens the system keyboard, so the next typed text replaces only the mistaken word. Voice input never sends automatically. Confirmation is a separate 28 dp primary check near the safe upper-right edge, retaining a larger invisible touch target.
- While an answer is pending, running or streaming, the lower editor action keeps its size and position but shows a stop icon. Two taps within 700 ms request server cancellation; the existing answer text stays visible, then the normal editor action returns.
- Sending is optimistic on the watch: confirming a non-blank editor draft immediately clears it and stores the submitted text as a local pending draft. Restore it only when the send request itself fails or times out before acceptance; a slow accepted generation must not make the editor jump back.
- The watch keeps a durable message outbox with `queued`, `accepted`, `streaming`, `complete`, and `failed` stages. A completed stream is committed to the local conversation immediately; fetching the authoritative messages and generated chat title happens afterward in the background. On restart, an unfinished job resumes from its stored job ID and SSE cursor instead of making the user resend the message.

## 10. Voice, generation, and errors

- The system recognition activity returns only its final transcript to the editable draft; recognition never auto-sends or exposes an in-app recording/stop state.
- Before the first response fragment, the compact assistant bubble combines three softly staggered typing dots with one short, event-backed stage label. Delivery and local-first preparation distinguish `Отправляю запрос…`, `Запрос принят…`, `Подбираю материалы…`, and `Выбираю способ ответа…`. A reused chat source, deep search, page opening, material evaluation/extraction/save, and RESEARCH drafting/checking/refinement each have their own brief label only while that operation actually runs. Repeated searches, result reviews and page opens show their pass number from the second pass onward (`· 2`) so a continuing search is distinguishable from a stuck step. Search exhaustion/unavailability is stated honestly; the VPS fallback says `Резервный сервер отвечает…` and never claims to search. Router reasoning levels are not shown as actual provider effort until they control the provider call. The first response token replaces the indicator immediately, and internal protocol names or hidden model reasoning are never displayed.
- As soon as the answer POST returns an accepted job, show `Запрос принят…`; waiting for the first SSE event must never prolong `Отправляю запрос…`.
- Errors do not replace the draft or add retry buttons. A red dot on the menu is the quiet persistent signal; the normal send path remains available.
- The history screen's yellow fallback dot follows the public VPS status of the main API. It clears as soon as the VPS confirms recovery; a failed watch status request alone does not change the dot.

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

Concept-test verdict: the blue-on-cool-graphite conversation canvas, asymmetric message alignment, deliberate swipe navigation, and stable voice-first composer remain recognizably WristMind when the product name is hidden. The weakest constraint is horizontal space when send appears on the smallest watch; it is intentionally handled with platform-size touch targets and a flexible field rather than shrinking the controls below Wear guidance.

Before accepting a Wear UI change:

1. Build with JDK 21 and Java/Kotlin target 17.
2. Compile device and font-scale previews.
3. Test on a round 466×466 AVD, including empty, draft, listening, processing, error, and long-answer states.
4. Confirm the primary action is reachable with one finger and no control clips at the circular edge.
5. Confirm no business-state transition changed as part of a visual refactor.
# Устройства и обзор

После отзыва доступа устройство сразу исчезает из интерфейса. Панель с отозванным токеном открывает подключение по новому коду. На обзоре нет блока «Требует внимания».

## Диктовка в веб-чате

Микрофон рядом с полем сообщения открывает запись с индикатором уровня звука, таймером, отменой и подтверждением. Подтверждённая запись распознаётся через SpeechKit и дописывается в редактируемый черновик; отправка сообщения остаётся отдельным действием. На первом этапе запись ограничена 30 секундами. Во время записи и распознавания кнопка отправки скрыта; существующий черновик сохраняется.

Диктовка: круглая кнопка микрофона слева имеет область нажатия 44×44 px; переключатель исследования также высотой 44 px. Во время записи поле заменяется горизонтальной полосой с отменой слева, звуковой волной по реальному уровню микрофона, таймером и подтверждением справа. Черновик сохраняется.

## Веб-чат: мягкий интерфейс разговора

Поле сообщения следует предоставленному пользователем примеру ChatGPT: радиус 28 px, спокойная серая поверхность в тёмной теме, без синей подсветки рамки. Микрофон слева и исследование остаются собственными функциями WristMind; кнопки высотой 44 px, без отдельных контуров. Отправка и остановка — круглые кнопки со значками справа. Во время диктовки доступны отмена, волна реального звука, таймер и подтверждение. Метаданные модели, длительность, время сообщения пользователя и диагностика видны только в режиме разработчика. Источники и режим чата остаются доступны в обычном режиме. Читаемость ответа сохраняется: без отступа под аватаром и с мягким пузырём пользовательского сообщения. Светлая тема использует существующие токены; акцент исследования остаётся синим.

Уточнение по референсу: микрофон располагается справа, непосредственно перед круглой отправкой; исследование — слева. Фирменная палитра WristMind сохранена: поле использует графитовый `bg-surface-raised`, отправка и подтверждение диктовки — синий `accent`, микрофон — `accent-text`, звуковая волна — `accent`. Во время записи правый блок занимает всю ширину поля. Геометрия и отсутствие синего свечения сохранены.

Звуковая волна диктовки показывает историю реальной громкости, а не одновременно пульсирующие декоративные палочки. Новые отсчёты появляются справа, накопленные плавно уходят влево с шагом 6 px; старый край мягко исчезает. Хранится не более 64 отсчётов. Синий акцент сохранён, при `prefers-reduced-motion` сдвиг отображается без анимации.

Мобильный чат учитывает `visualViewport`: при экранной клавиатуре вся область разговора ограничивается реально видимой высотой, поле ввода остаётся над клавиатурой. Нижняя навигация скрывается, когда клавиатура перекрывает экран; после закрытия возвращается. При масштабировании страницы специальное позиционирование отключается.

Статусы «Микрофон…» и «Распознаём…» центрируются относительно всей полосы диктовки: справа резервируется ширина, равная кнопке отмены слева.

Ошибки диктовки отображаются отдельной строкой под кнопками внутри поля сообщения. Текст ошибки не участвует в горизонтальной раскладке действий и не сдвигает микрофон, исследование или отправку.

Звуковая волна рисуется на Canvas непрерывно через requestAnimationFrame, без пересоздания DOM на каждом отсчёте. Реальная громкость записывается в ограниченную историю каждые 100 ms, между отсчётами полоса плавно сдвигается. Если SpeechKit вернул пустое распознавание, поле возвращается в обычное состояние без сообщения «Речь не распознана»; существующий черновик сохраняется.

## Wear: потоковая диктовка SpeechKit

Текущая кнопка микрофона в редакторе открывает собственный экран записи WristMind. На круглом экране: «Говорите», синяя история реального уровня голоса, таймер до 30 секунд, две кнопки по 48 dp — отмена и подтверждение. После подтверждения показывается «Распознаём…», затем текст дописывается в существующий черновик. Самостоятельной отправки сообщения нет. Пустая расшифровка возвращает пользователя к черновику без ошибки. Уход с экрана/перевод приложения в фон прекращает запись и отменяет серверную сессию. Доступ к микрофону запрашивается штатным разрешением Android.

Кнопки экрана диктовки Wear — строгие круги 48×48 dp (`CircleShape`, `requiredSize`), чтобы ограничение родителя не превращало их в овалы. Подтверждение выделено голубой заливкой `colorScheme.primary` и контрастной галочкой `onPrimary`; отмена остаётся спокойной тональной кнопкой.

На слабой связи диктовка сохраняет тот же сценарий записи и черновика; транспорт применяет сжатие без потери PCM и объединяет накопившиеся пакеты. Визуальное поведение не меняется.

# Веб-панель: визуальный язык ChatGPT

Раздел описывает **административную панель**. Часы он не затрагивает: всё выше остаётся
авторитетным для Wear OS.

## Концепция

### Формулы в ответе

Выделенная формула `\\[...\\]` или `$$...$$` занимает собственную строку между фрагментами ответа, даже если разделители пришли вплотную к тексту. KaTeX показывает дробь `\\frac` числителем над горизонтальной чертой и знаменателем под ней. Короткая формула центрируется по ширине ответа; длинная прокручивается по горизонтали только внутри блока формулы, без видимой полосы прокрутки и без сдвига всей беседы. Строчные формулы остаются в потоке текста.

> Тихий рабочий стол: почти чёрный холст разговора, серый рельс и ещё более светлые
> поля; поверхности различаются **тоном, а не рамками**, кроме полей ввода; типографика
> держит иерархию; **синий** отмечает то, что действительно требует действия; снизу
> единственный «инструмент» — скруглённый composer.

Задача владельца — «подогнать дизайн всей панельки под дизайн ChatGPT». По ходу работы
выяснилось, что чистый монохром читается слишком плоско, поэтому акцентом остаётся
**синий**: он же есть и у ChatGPT — им подписаны ссылки и активный инструмент.

Источник значений — официальные токены [openai/apps-sdk-ui](https://github.com/openai/apps-sdk-ui).
Почти все «OpenAI Design System» в сети описывают интерфейс 2023 года (зелёный `#10a37f`,
Söhne, `#343541`); актуальная поверхность монохромная, зелёного в ней нет.

## Цвет (тёмная тема)

| Роль | Значение | Назначение |
| --- | --- | --- |
| `--bg-canvas` | `#0a0a0a` | холст **разговора**: беседа и колонка списка чатов |
| `--bg-shell` | `#141414` | каркас приложения: фон остальных страниц |
| `--bg-inset` | `#121212` | углублённые области: код, вставки |
| `--bg-sidebar` | `#1a1a1a` | рельс навигации, на тон светлее холста |
| `--bg-surface` | `#212121` | панели и карточки |
| `--bg-surface-raised` | `#2f2f2f` | composer, меню, диалоги, заливка полей |
| `--border-field` | `rgba(255,255,255,.3)` | контур полей ввода — единственная рамка, которая обязана читаться |
| `--text-primary` / `--text-secondary` | `#f2f2f2` / `#c8c8c8` | текст |
| `--accent` / `--accent-contrast` | `#2f6fe4` / `#ffffff` | основное действие |
| `--accent-text` | `#7ab8ff` | ссылки и активная подпись |

Отдельный `--bg-shell` появился не случайно: когда весь каркас красился в цвет холста
разговора, пустая полоса над заголовком каждой страницы читалась как чёрная планка. Чистый
чёрный принадлежит только чату; остальные страницы стоят на `--bg-shell`.

Светлая тема — `#ffffff` холст, `#f7f7f7` рельс, `#f0f0f0` поверхности, `#0d0d0d` текст,
`#2563eb` акцент. Возвышение выражается **ростом светлоты**: на тёмном тени почти не
читаются. Синий акцент подобран расчётом: белый текст на `#2f6fe4` даёт 4.65:1 (AA), а
более яркий синий эту планку не держит.

## Типографика

Подключён **системный стек**, как в ChatGPT:
`ui-sans-serif, -apple-system, system-ui, 'Segoe UI', Roboto, …`; моно — системный
`ui-monospace`. Веб-шрифты не загружаются вообще: из критического пути убраны две
блокирующие загрузки, CSS-бандл стал меньше примерно на 7 КБ.

Шкала: `--text-2xs: 11` → `--text-4xl: 32`, база **14 px**. Текст разговора — 16 px с
интерлиньяжем 1.7; таблицы и списки остаются плотными, иначе админка разъезжается.

## Формы, отступы, движение

Радиусы по шкале Apps SDK: 4 / 6 / 8 / 10 / 12 / 16 + full. Сетка 4 px. Движение —
150 ms и 200 ms с существующими кривыми; анимируются только `transform` и `opacity`.

## Компоненты

- **Шапка.** Верхней плашки нет: поле поиска, кнопка «Создать» с выпадающим меню и
  мини-логотип убраны по требованию владельца — ими не пользовались, а своё основное
  действие есть на каждой странице. Командная палитра остаётся доступна по горячей клавише.
- **Кнопки.** Основная — синяя. Вторичная — заливка `--bg-surface` без контура, на
  наведении `--bg-surface-raised`. Контурных кнопок в панели нет.
- **Поля и селекты.** Заливка `--bg-surface-raised` плюс видимый контур `--border-field`.
  Это осознанное исключение из «тон вместо рамок»: без контура поле на панели исчезает.
  Наведение и фокус усиливают контур, фокус дополнительно даёт мягкий ореол. Растягивание
  полей за угол запрещено (`textarea { resize: none }`).
- **Переключатель.** Во включённом состоянии — трек цвета акцента с контрастным ползунком;
  сплошная заливка без видимого ползунка недопустима.
- **Панели и карточки.** Разделяются тоном; рамка вокруг контейнера — то, что этот язык
  убирает. Исключение — список чатов на **мобильном экране**: он лежит на чёрном холсте, где
  плоская строка не видна до наведения, поэтому каждая беседа получила заливку `--bg-surface`
  и хайрлайн `--border-muted`; активная — `--bg-selected` с акцентной рамкой. В рельсе те же
  строки стоят на серой подложке `--bg-sidebar` и обходятся без заливки и рамок: покой —
  прозрачный фон с `--text-secondary`, наведение — `--bg-hover`, активная — `--bg-selected`
  с `--text-primary`.
- **Список режимов.** Один режим — одна компактная строка высотой примерно как строка
  чата: цветовая полоса режима, название (по нажатию открывается режим), переключатель
  «На часах» и меню действий. Модель, число источников и чатов на карточке не показываются —
  это содержимое страницы самого режима, а не списка.
- **Диалоги.** Приподнятая поверхность над затемнением, без собственного контура.
- **Приписывание ответа.** Ответ ассистента — обычный текст по колонке чтения (768 px) со
  знаком продукта; подписи с именем модели у сообщения нет.
- **Шапка беседы.** Заголовок чата и режим стоят **на одной строке**; название режима не
  переносится на вторую строку, а усекается внутри своего чипа.
- **Пустой чат — пустая страница.** Новый чат не показывает над полем ввода **ничего**:
  ни заглушки с режимом, ни подсказок, ни предупреждений. Режим называет шапка, способ
  ответа выбирается в поле ввода, поэтому в теле они не повторяются. Убраны как дублирующие:
  заглушка с названием режима и описанием, «Опции запроса» с плашкой «Авто», коробка-
  предупреждение об отсутствии источников и три подсказки.

## Рельс и список чатов

Панель следует информационной архитектуре ChatGPT: **список диалогов — содержимое самого
рельса**, а не отдельная колонка между рельсом и беседой. Беседа занимает всё оставшееся
место, и на десктопе у разговора больше нет второй шапки-страницы. Порядок рельса сверху вниз:
знак продукта, навигация (`Работа`, `Система`), секция `Чаты` со своим действием создания,
футер (предупреждение о сервисах, если оно есть).

- Секция `Чаты` показывается **только на маршрутах `/chats*`**; на остальных страницах рельс
  остаётся навигационным. Список идёт **после** пунктов навигации, поэтому положение пунктов
  одинаково на всех страницах.
- Список — **простой список**: ни поля поиска, ни фильтра по режиму. Порядок и хронологию несут
  только группы.
- Переключателя темы в рельсе нет: рельс занят навигацией. Тема переключается в `Настройках`,
  из командной палитры (`Ctrl/⌘+K`) и в мобильном листе «Ещё».
- Строка чата — **одна строка**: точка режима и название с усечением, отметка закрепления у
  правого края. Превью последнего сообщения убрано. Метка времени в рельсе скрыта — хронологию
  несут группы `Закреплённые / Сегодня / На этой неделе / Ранее`; на мобильном экране список
  шире, и время там показано.
- Действия строки (`⋯`: переименовать, закрепить, удалить) появляются при наведении и фокусе и
  **вытесняют отметку закрепления**, а не накладываются на неё. На мобильном экране действия
  видны всегда.
- Кнопка `Новый чат` в секции видна постоянно, а не только при наведении: это основное действие
  раздела.
- Блок быстрых ссылок на режимы из рельса убран: у режимов есть своя страница, выбор режима при
  создании чата и цветовая точка в каждой строке чата.
- Ниже 860 px рельс скрыт: список становится отдельным экраном со своей шапкой (`h1 Чаты`,
  кнопка `Новый`) и футером со счётчиками. Компонент списка в обоих местах один и тот же, поэтому
  группы, действия и пустые состояния совпадают.
- Заголовок страницы — `h1`: у открытой беседы это её название, у мобильного экрана списка —
  `Чаты`. Одновременно они не отображаются.
- Пустая беседа не повторяет список: блок «Недавние» удалён, остаётся только подсказка с
  действием `Новый чат`.

## База знаний

Страница источников — тоже **простой список**: поиска по названию, фильтра по режиму и
сортировки нет, вкладок статуса (`Все / Готовые / В обработке / Ошибки`) нет. Сводка под
заголовком (`13 всего · 11 готово · …`) остаётся: она сообщает те же числа, ничего не фильтруя.
Порядок — от новых к старым.

Таблица здесь — единственная, что стоит в панели без собственной шапки (`Panel flush` без
`PanelHeader`), а у заголовков колонок нет верхнего отступа. Поэтому таблица получает
собственный воздух сверху (`.tableTop`), иначе подписи колонок липнут к верхнему краю панели.

## Контраст

Проверено расчётом по формуле WCAG, обе темы отдельно. Проходят все пары: основной текст на
холсте 17.4:1, вторичный 11.6:1, самый тёмный токен (`--text-faint` `#a8a8a8`) — 6.0:1 на
приподнятой поверхности; белый на синем акценте 4.65:1; синий текст ссылки 9.4:1 на холсте.
Фокус-индикатор поля — `#b4b4b4`-класса светлота, около 7.8:1.

Известное отклонение: контур поля ввода не достигает 3:1 по non-text contrast (WCAG 1.4.11).
Поле опознаётся по заливке и подписи над ним; при требовании строгого соответствия контур
следует усилить.

## Что осталось

Структурная часть копии ChatGPT выполнена: список чатов перенесён **внутрь рельса** (см.
«Рельс и список чатов»), отдельной колонки 340 px больше нет. Остались иконки: панель
использует Lucide, тогда как скилл дизайна рекомендует выбрать набор осознанно.


### Источники чата: три категории (8 октября 2026)

- «Сохранённые материалы» — рабочие источники текущего чата; карточка позволяет проверить сохранённый текст.
- «Прочитанные страницы» — сервер получил непустой текст страницы/PDF и сохранил его в кэше чтения. Это не подтверждение релевантности и не добавление в рабочие материалы. Карточка: «Страница прочитана».
- «Найденные ссылки» — ссылка и поисковый фрагмент, без подтверждённого чтения. Карточка прямо сообщает, что бот страницу не прочитал.
- Категории взаимоисключающие: рабочий материал заменяет карточку того же URL; прочитанная страница исключается из найденных ссылок. Фильтры «Все», «Сохранённые», «Прочитанные», «Ссылки» имеют отдельные счётчики.
- Признак чтения приходит с API (`read_at`) по факту серверного кэша, а не из текста ответа или наличия сниппета. Индекс не передаёт полный текст страниц. Обновление после ответа использует существующую подписку панели.


### Компактная шапка чата (8 октября 2026)

По запросу пользователя: слева стрелка возврата (на мобильном экране), затем существующий `ModeDot` 8 px цвета режима перед однострочным названием чата; для Quick Chat нейтральный кружок. Название режима в шапке скрыто. Справа только кнопка источников: `Layers` 18 px и число, без слова «Источники» и без разделительной точки. Доступное имя кнопки сохраняет назначение и количество. Меню «…» из шапки удалено; управление чатом остаётся в списке чатов. Стрелка и кнопка источников имеют высоту 44 px. Длинное название сокращается многоточием внутри выделенной ширины; шапка не переносится на вторую строку.

## Уточнение 9 октября: ответы и источники панели

- Отдельные формулы компактны: вертикальный margin `space-3`, padding `space-2`; встроенные формулы остаются в строке, важные отдельные уравнения центрируются. Длинная формула прокручивается отдельно без видимой полосы.
- Абзацы с метками «Важно», «Ответ», «Ошибка», «Подсказка», «Решение» имеют общие padding `space-4 space-6` и radius `radius-sm`; базовый фон `bg-inset`, ответ `success-soft`, ошибка `danger-soft`, важно `warning-soft`. Текстовые метки обязательны: смысл не передаётся только цветом. Никаких HTML-команд для модели.
- Стриминг использует короткое постепенное появление с обновлением до 20 раз/сек, сохранением готовых блоков; при reduced-motion и завершении текст виден сразу.
- Фон бокового списка страниц источника непрерывен до низа содержимого. Прокручивается внутренний список с максимумом 620px; мобильный список остаётся горизонтальным.
- Диктовка начинает передачу во время записи; при сбое сохраняет возможность распознавания целого клипа. Пустая расшифровка показывает ошибку.
- Возможности клиентов разделены: интерактивные карточки и SVG-графики веба не переносятся в Wear; там график заменён названием и кратким выводом.

- При входе в чат Wear сразу показывается последняя реплика без анимации пролистывания всей истории. Позиция сохраняется при возврате из черновика/полного ответа; новое открытие через историю снова показывает низ.
- Инкрементальный разбор панели сохраняет завершённые независимые абзацы/формулы; сложный связанный Markdown использует полный разбор с сохранением неизменённых узлов.



- Диагностика ответа не отображается в чате даже в режиме разработчика. Режим редактирования промптов не управляет показом диагностической строки.

## Интерактивные математические графики — 9 октября 2026

- Существующий SVG-график встроен в ответ: поверхность `bg-surface`, radius `radius-md`, padding 10px 12px 4px; высота плоскости 280px на десктопе, 260px на телефоне. Слева формула KaTeX, справа тихие кнопки уменьшения/увеличения масштаба, исходного вида и раскрытия. Нет постоянного ползунка, счётчика точек, множителя ×1 и повторного summary.
- Область построения имеет одинаковые боковые отступы 48px. Сетка `border-muted`, шаг 1/2/5×10ⁿ; оси `text-secondary` с opacity .65, штрихи и обозначения x/y; подписи 11 экранных px. Кривые 2px; последовательность цветов `accent-text`, `success-text`, `warning-text`, `danger-text`, `text-primary`, `text-secondary`.
- Колёсико масштабирует относительно курсора, перетаскивание перемещает область, touch поддерживает pan/pinch. Hover показывает координаты ближайшей по y функции при текущем x, нажатие закрепляет их. Сброс восстанавливает исходную область и снимает выбор; клавиатура поддерживает стрелки, +/− и Escape.
- Расширенный график использует существующий Modal xl; плоскость до 520px/58vh (52vh на телефоне). Кнопки справа. Для нескольких функций — кастомные отметки 18px в цвет линии, скрытый native checkbox с понятным именем и focus-visible; текстовых инструкций управления внутри карточки нет.
- Старый JSON title/summary/points сохранён. Для функций — необязательный массив functions с безопасной арифметикой; никаких HTML/JavaScript/eval. Протокол и часовой рендерер не заменяются. Частичный chart показывает статус, некорректный — понятную ошибку.
- По расчёту контраст подписей: dark 9.62:1, light 7.78:1; осей 4.89/3.28; первых четырёх кривых минимум 7.11/5.20. Отдельная проверка сенсорных жестов на физическом устройстве ещё нужна.

- Стриминг панели: синий прямоугольный caret заменён рядом из трёх нейтральных точек 4px, gap 4px, зона 18px. Цвет text-secondary; плавная смена opacity с задержками, без прыжков и мигания текста; reduced-motion — статичные точки. Статус доступен как «Ответ поступает».
- Для старого chart можно восстановить явно указанную в title формулу y=…, если безопасная арифметика совпадает со всеми точками. Только в этом случае линия пересчитывается за исходным диапазоном; математическая прямая продолжается до края видимой плоскости.

- Уточнение управления: точка привязывается к численно найденным пересечениям осей и видимых функций в радиусе 12 экранных px; метка поясняет вид пересечения. Закрепление разрешено только на пересечениях. На сенсорном экране удержание 450ms включает режим ведения точки пальцем; отпускание закрепляет пересечение. Другой drag сохраняет перемещение области, второй палец переключает на pinch.
- Ожидание ответа: развёрнутая ProcessingTimeline и служебная стадия в шапке не показываются. Одна нейтральная строка «Думаю» или «Ищу информацию» с тремя точками; при приходе текста остаётся только индикатор стриминга.

- На телефоне заголовок компактного графика занимает отдельную строку, кнопки выравниваются справа ниже; внутренний отступ карточки 10px. Строчные формулы имеют собственную скрытую горизонтальную прокрутку при переполнении; вложенные списки сохраняют умеренный отступ 18/16px.
- JSON графика без ограждения chart или в блоке json распознаётся по конверту title/summary/points/functions. Незавершённый конверт показывает статус формирования, некорректный завершённый — понятную ошибку; обычный JSON остаётся текстом/кодом.

- Поле ввода чата доступно для набора следующего запроса во время генерации. Черновик сохраняется после завершения/остановки ответа; отправка доступна после завершения, во время генерации кнопка останавливает ответ.


### Информационные блоки сообщений (Callouts)

Концепция: спокойные примечания внутри ответа — обычный текст остаётся главным, отдельный акцент задаётся тонкой рамкой, маленькой иконкой и короткой меткой. Шрифт, отступы, радиусы и цвета берутся из текущих токенов WristMind; фон прозрачный, без теней, полос сбоку и анимации карточки.

- Явный синтаксис: `> [Важно] Необязательный заголовок`, затем строки тела с `>`. Аналогично `[Подсказка]`, `[Ошибка]`, `[Пример]`, `[Ответ]`, `[Информация]`. Пустая строка без `>` завершает блок. Обычные цитаты и прежние семантические абзацы остаются без изменения.
- Рамка border-default 1px, radius-md; padding space-5/space-6, на телефоне space-4/space-5. Иконка существующей библиотеки Lucide 16px. Метка text-sm semibold, основной текст — обычная типографика ответа. Тип передаётся меткой/иконкой, не только цветом.
- Внутри переиспользуется безопасное дерево Markdown/KaTeX, включая списки, ссылки, таблицы и код. HTML модели остаётся инертным текстом. Длинные формулы имеют собственную скрытую прокрутку. Вложенные блоки модель не должна создавать.
- На часах разметка уже читается как цитата с русской меткой и текстом; отдельный интерактивный рендерер не нужен. Изменений Android нет.
- При стриминге завершённые дочерние блоки сохраняют identity и memo-компоненты; незакрытая цитата остаётся читаемой до конца ответа. Нет отдельной анимации, автосворачивания или собственной логики прокрутки карточки.

- Тип Callout и необязательный заголовок разделяются точкой · и gap space-3. Внутри карточки line-height leading-normal, между абзацами space-3, между пунктами списка space-2. Для объяснений выше 220px есть явная кнопка «Свернуть объяснение»/«Развернуть объяснение» с aria-expanded/aria-controls. Короткий блок раскрыт; длинный блок по умолчанию свёрнут после завершения ответа, с кнопкой раскрытия сразу под заголовком. Во время генерации сворачивание недоступно, содержимое не удаляется из дерева при сворачивании.

- Диктовка веб-панели во время записи: X отменяет запись без изменения черновика; квадрат останавливает и вставляет расшифровку в черновик; стрелка вверх завершает, распознаёт и отправляет сообщение вместе с набранным текстом. Во время запуска микрофона/распознавания доступна отмена. Автоматическое завершение по лимиту 29 секунд только вставляет текст, не отправляет. Кнопки 44px, ясные aria-label/title; мобильные интервалы space-3 сохраняют место для волны и таймера.

- Переход к последнему сообщению: круглая кнопка 36px со стрелкой вниз 16px без видимого текста и тени; зона нажатия расширена до 44px. Назначение сохраняется в aria-label/title, фокус видим.

- Голосовая панель: отмена слева, волна/таймер в центре, остановка и отправка справа. Квадрат остановки в тонком круглом контуре; отправка — круг с text-primary фоном и bg-canvas стрелкой. Активные кнопки нейтральные, без синего заполнения.

- Кнопка раскрытия/сворачивания Callout остаётся последним элементом внизу карточки. Для заметности — на всю ширину, bg-surface, border-strong, radius-sm, текст text-primary и шеврон 16px; высота минимум 36px, на телефоне 44px.


### Chat-only web application · 9 October 2026

- Product/app profile B3. `/talk` is a dedicated conversation surface, `/talk/history` mobile history, `/talk/{id}` shared server conversations. `/main` and the administration routes remain intact.
- Concept: one conversation workspace shared with the watch; WristMind's canonical mark, platform sans typography, existing monochrome tokens and Lucide family. No new palette, font or component library.
- Desktop: 260px quiet history rail, 768px maximum composer/reading column; mobile: 44px history/new-chat actions, no administrative bottom bar. Reuse the visual viewport keyboard handling and safe areas.
- New conversation: directly type the first request; choose the immutable mode before creation. Ordinary chat is the default. Existing Composer, Conversation, Markdown, KaTeX, callouts, graphs and voice controls are reused.
- Drafts are session-local by chat ID; failed sends restore text without replacing a subsequently typed draft. Offline feedback is explicit; API/private messages are never stored by the service worker.
- PWA starts at `/talk`; native install prompt where supported, otherwise Android/Safari installation instructions. Cached public shell is not a promise of offline AI or offline history.
- Adversarial review: replaced an oversized full-width mode selector with a constrained 240px secondary control. Shared history row type enlarged to 16px on this surface.

- Уточнение пользователя: `/talk` не показывает выбор режима; любые новые разговоры здесь создаются только через Quick Chat. Существующие общие диалоги сохраняют свой неизменяемый режим. Клавиша C открывает новый быстрый разговор без диалога выбора режима.

- Уточнение стартового мобильного экрана: только центральный заголовок «Чем могу помочь?» и Composer у нижнего края. Логотип и поясняющий слоган удалены; при открытой клавиатуре заголовок скрывается. Установка и переход в панель находятся в истории (mobile) / нижней части rail (desktop), не рядом с вводом.

- В мобильной панели переход в `/talk` находится первым пунктом меню «Ещё»: «Приложение чатов». На desktop доступен из sidebar.
- Мобильная история `/talk`: боковая панель слева (до 340px, оставляет минимум 48px затемнённого чата), поверх сохранённой переписки. Использует существующий доступный Drawer: focus trap, Escape, крестик и нажатие на фон. Содержит новый быстрый чат, поиск по названиям, общую историю и нижние вспомогательные действия. Выбор диалога закрывает панель; новые диалоги остаются Quick Chat. Остальные Drawer сохраняют прежнюю сторону/поведение.

- Уточнение боковой истории: поиска нет. «Новый чат» — полная строка высотой минимум 48px, с иконкой 20px слева, текстом 16px и нейтральным фоном; hover/pressed/focus-visible.

- Голосовой ввод панели: запуск на pointerdown (касание/нажатие), click остаётся для клавиатуры/assistive technology; ref защищает от двойного старта. Перед вызовом audio API синхронно показываются состояние «Включаем…» и полоса с нулевой амплитудой; запись и очередь сервера запускаются параллельно. Полоса реального звука не имитируется. После отправки на mobile фокус textarea снимается для закрытия клавиатуры; desktop сохраняет фокус. Stop диктовки оставляет текст для редактирования.

### Wear: информационные блоки и дроби, 10 октября 2026

- Последовательность цитат с меткой `[Важно]`, `[Подсказка]`, `[Ошибка]`, `[Пример]`, `[Ответ]` или `[Информация]` образует один нативный блок. Заголовок без скобок, дополнительное название отделяется точкой. Нейтральная поверхность, тонкий outline, 8dp горизонтального / 6dp вертикального padding и 4dp между частями; никаких отдельных синих карточек для метки и каждой строки.
- Markdown, списки и выделенные формулы внутри блока используют существующий Wear-рендерер. Обычные цитаты и код сохраняются; незавершённый заголовок допустим во время стриминга.
- Одиночные выделенные `\frac`, `\dfrac`, `\tfrac` не ограничиваются длиной числителя/знаменателя. Длинные части переносятся в доступной ширине; длинные префикс и результат стоят до/после дроби. Однозначная отдельная запись `(числитель)/(знаменатель)` также получает горизонтальную черту. Строчные дроби остаются компактными; вложенные/несколько дробей пока используют читаемый текстовый fallback.

### Управление чатами на touch-экранах, 10 октября 2026

- Обе веб-поверхности используют единое меню строки: переименование, закрепление/снятие закрепления и soft-delete. На узких/touch-экранах три точки постоянно видимы с областью нажатия 44px; место справа зарезервировано и длинный заголовок сокращается внутри доступной ширины. Список не может расширять боковую панель.
- Закреплённые чаты находятся в отдельной верхней группе; флаг сохраняется сервером и не меняет название. Ошибка сохранения показывается пользователю. Переименование ограничено 120 символами, повторная отправка блокируется, Enter во время IME-композиции не отправляет форму.
- Escape закрывает верхний диалог/меню, сохраняя открытую историю под ним.


## Настройки провайдеров и моделей — 10 октября 2026

Использовать общий ProviderSettings: провайдер и скрытый ключ, затем поиск/ручной ID модели и проверка. Списки выбора показывают только добавленные включённые модели. Один вертикальный поток; поля и кнопки 44px, одинаковые рамки и типографика. Название подключения — необязательное раскрываемое поле. Длинные имена переносятся; действия на телефоне переходят на следующую строку. Сохраняются существующие однотонные поверхности, Lucide, фокус и светлая/тёмная темы. Ошибки находятся рядом с формой; каталог доступен с клавиатуры как список кнопок.

Мастер /setup: колонка до 480px по центру экрана, фиксированная верхняя позиция заголовка, три текстовых шага без отдельного меню. Поля имеют общую левую/правую границу; основное действие занимает свободную ширину ряда, второстепенное «Назад» остаётся компактным. Длинная форма прокручивается целиком, на мобильном ввод 16px предотвращает автоматическое увеличение. Готовность и ошибки обозначаются текстом, а не только цветом.


## Self-hosting: обслуживание, 11 октября 2026

Обновление, резервное копирование и восстановление доступны только из терминала через wristmind. В панели нет кнопок обновления и управления Docker. На время обслуживания API отвечает 503 с Retry-After; здоровье сервиса остаётся доступно. Пользовательский runtime рассчитан на один сервер, домен необязателен.

### Настройки ИИ — 11 октября 2026

Главный раздел «Возможности» показывает задачу пользователя: подключить сервис, выбрать модель для ответов, подключить дополнительные функции. Два соседних раздела — «Провайдеры» и «Модели»; три вкладки одинаковой ширины, подписи центрированы, высота 44px. Статус готовности функции отделён от переключателя разрешения. Термины Vision/embeddings объясняются через понимание изображений и поиск по смыслу; мощность и технические подробности раскрываются отдельно. Используются существующие тёмная/светлая тема и токены; без новой библиотеки. Удаление подключения требует существующего диалога подтверждения и защищает действующие зависимости. Концепция: настройки как последовательность понятных задач, а не перечень API-параметров. Главная выявленная слабость — дублирующий выбор модели — устранена переносом выбора в единый основной раздел. Основа: GOV.UK Task list и NN/g Progressive disclosure.

### Понятные базовые функции и улучшения

«Чтение документов» и «Ответы по вашим документам» показывают локальную базовую функцию отдельно от необязательных улучшений. Vision и embeddings находятся в раскрываемых секциях с примером пользы, требованием отдельной модели и объяснением передачи данных внешнему сервису. При отсутствии дополнительных моделей не показывать пустой селектор модели с названием базового режима. Добавление улучшения остаётся в «Возможностях»: шаг 1 — сервис, шаг 2 — модель выбранного назначения, возвращение к функции после сохранения. Не заставлять пользователя искать нужную роль в общем списке моделей. Заголовок нового шага получает фокус. Для начала общения достаточно сервиса и одной модели; инструкция встроена в основной экран.

## Настройки ИИ: локально или API

Необязательные улучшения раскрываются компактными секциями с шевроном, скруглением и спокойным фоном. Для модели предлагаются два явных пути: API и локальный сервер. Локальная установка в SelfHost объясняется тремя шагами и копируемой терминальной командой; открытие панели не запускает скачивание. Демо обозначается постоянно, поле ключа видно с объяснением, почему оно отключено.

## Раскрывающиеся пояснения в настройках

Общий стиль для инструкции, необязательных улучшений и оценки мощности: заголовок высотой от 48 px, спокойный фон bg-surface-raised, radius-md, шеврон справа. Раскрытое содержимое имеет одинаковый внутренний отступ и обычный фон панели. Инструкции разбиты на пронумерованные шаги с коротким названием и пояснением. Сохранены нативные details/summary, клавиатура и reduced-motion. Локальный путь установленных сервисов не показывает поле API-ключа; адрес и модель подставляются заранее.

Списки выбора используют существующий Menu с вариантом select: ширина поля в пределах экрана, строки от 44 px, галочка справа, спокойное выделение и прокрутка длинного списка. Обычные контекстные меню сохраняют компактный размер. Контраст текста на фоне поля: тёмная тема 6.31–11.96:1, светлая 6.13–17.83:1. Общий стиль WristMind сохранён; исправлена прежняя слабость — широкое поле открывало узкое меню. Эти правила и значения входят в существующий DESIGN_SYSTEM.md и применяются к следующим изменениям интерфейса.

### Уточнение локального пути — 11 октября 2026

Локальная установка ограничена поиском по смыслу (EmbeddingGemma) для RAG. Оцифровка/OCR и поиск по словам уже локальные. Vision, голосовые и чатовые модели устанавливать локально этим мастером нельзя; соответствующие кнопки убраны. Команда SelfHost сама скачивает, проверяет и назначает модель; после инструкции панель возвращается в настройки без форм провайдера/выбора модели. Это уточнение заменяет предыдущие описания универсальной локальной установки. Основные настройки синхронизированы между обеими копиями.

### Автоматический веб-поиск — 11 октября 2026

Новая SelfHost-установка активирует профиль search, генерирует секрет SearXNG и задаёт внутренний URL автоматически. Для существующей установки команда `wristmind web-search --install-dir /opt/wristmind` сохраняет остальные настройки/секреты, запускает сервис, проверяет JSON-поиск из API и включает только web_search. Неудача восстанавливает исходный .env; внешний настроенный поисковый URL не заменяется. В панели отсутствуют поля ключа/URL и ручные профили: раскрывающаяся инструкция предлагает одну команду. Docker-сервис не публикует порт. Реальная серверная приёмка ещё ожидается.


## SelfHost companion setup (stage 7)

The companion remains infrastructure UI without a second chat surface. Use the existing graphite/Signal Blue palette, flat backgrounds and Material 3 fields with at least 48dp action targets. The setup wizard shows one task per screen, explains the distinction between website enrollment and watch ADB pairing, and separates pairing/connect ports. Compact progress describes the current operation; failures stay on the current step with retry. Explain ADB authority honestly and recommend disabling debugging after installation. A completion state requires an acknowledgement from the intended watch after server authentication, not merely sending a configuration packet.


### SelfHost: единая точка терминальной настройки

Все пользовательские инструкции сервера и подсказки панели ведут к install.sh и именованному пункту меню. Не показывать отдельные команды с фиксированным каталогом /opt/wristmind. Каталог выбирается при открытии меню, порт/демо — при новой установке; интерфейс веба не выполняет shell-команды сам.


### Терминальное меню SelfHost

Компактный заголовок WristMind / SELFHOST, тонкие разделители и последовательные номера. Разделы: начало работы, доступ и обслуживание, дополнительные возможности. ANSI-палитра: синий бренд/номера/приглашение, зелёный установка/готовность/backup, жёлтый обслуживание/незавершённость/восстановление, красный занятый каталог/удаление; вторичный текст серый. Цвет дополняет подписи, не заменяет их. При перенаправлении stdout, TERM=dumb или заданном NO_COLOR ANSI отключён. Экран не очищается: результаты операций остаются в истории терминала. Состояние установки не выдаётся за проверку здоровья контейнеров.


### Self-host: проверка установки

Проверка использует те же секции и палитру, что терминальное меню: зелёный — готово, красный — блокирующая ошибка, жёлтый — рекомендация. CPU/RAM оцениваются без запрета базовой установки; ограниченный профиль явно обозначен. Голосовой API не требует локальной модели. Текст оценки переносится по ширине терминала; NO_COLOR и вывод в файл остаются без ANSI.


### Self-host: ожидание сборки

Длительные Docker-операции показывают строку с текущим этапом и прошедшим временем. В терминале строка обновляется раз в секунду; в журналируемом выводе — раз в 15 секунд. Процент и ETA не выдумываются. Вывод Docker хранится в защищённом install.log, на экран попадают только фиксированные названия этапов.


### Self-host: первый вход по IP

Пункт первого входа при локальном адресе сначала определяет IP автоматически и включает HTTP-доступ; ручной ввод запрашивается только при неудаче на выбранном порту. Затем выдаёт ссылку с реальным настроенным адресом. Домен/HTTPS остаются необязательными отдельными вариантами доступа. Рядом с настройкой HTTP кратко обозначаются отсутствие шифрования и микрофона браузера.


### Self-host: независимые дополнительные функции

Голосовой API не выключается при применении рекомендаций мощности. Настройка Vision доступна даже при выключенном чтении документов; DeepSeek выбирается только для текстовых ответов. Способ веб-поиска выбирается отдельно: SearXNG на сервере либо Yandex Search API, Brave, Tavily. Форма внешнего поиска запрашивает ключ и, для Яндекса, folder ID; сохранённые ключи не показываются. Рекомендации локальной мощности не меняют переключатель внешнего поиска.


### Статусы терминальных операций

Длительные операции показывают название текущего действия, меняющийся индикатор и прошедшее время. Скачивание пакета показывает фактически полученные МБ и общий объём, если он известен. Проверка архивов/SHA256, Docker load/pull, резервные копии, восстановление, запуск сервисов, health, DNS и определение IP имеют индикатор ожидания. После завершения отображается успех либо ошибка; проценты и оставшееся время не выдумываются. В терминале строка обновляется на месте; в логах — периодическими строками. Аргументы Docker и секреты не попадают в статусы.

Состояние выключенного владельцем веб-поиска не добавляется автоматически в текст ответа или его нижнюю приписку.

### Восстановление чата при возврате (13 октября 2026)

При потере потока уже принятого сообщения сохраняем текущий текст ответа и автоматически проверяем серверное задание. Возврат на вкладку не требует ручного обновления или повторной отправки. В поле ввода остаётся только неотправленный черновик; ошибка формирования уже принятого ответа не возвращает туда вопрос.

### SelfHost: сессия и расписание обновлений (13 октября 2026)

Повторный парольный вход из того же браузера не умножает устройства. Подписанная browser-cookie идентифицирует запись после успешной проверки пароля, но сама не даёт доступа. Активные cookie-сессии продлеваются, технические/провайдерские ошибки не показывают форму входа без подтверждения недействительности сессии. Ночное обновление включается только в терминальном меню с явным временем и часовым поясом, без веб-кнопок обновления.
