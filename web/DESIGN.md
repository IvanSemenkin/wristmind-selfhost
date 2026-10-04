# WristMind Web Control Center

## Product goal

Give one owner a clear operational surface for configuring WristMind, managing mode-bound chats and knowledge, and seeing device/server health. The primary action in the first slice is adding a document to exactly one mode with an explicit per-document processing method.

## Information architecture

- Overview: confirmed system state and recent processing activity.
- Chats: conversations whose mode is immutable after creation.
- Modes: prompt, model, color, icon, and mode-specific knowledge summary.
- Knowledge: mode-scoped sources, upload queue, OCR/Vision selection, failures, and deletion.
- Settings: global prompt, providers, devices, connection, and diagnostics.

## Visual direction

Dense analyst workspace with a calm hardware-console character. Near-black green surfaces, one mint accent, fine borders, compact controls, and monospaced operational details. The memorable idea is that mode isolation is visible everywhere: the active mode colors the context line and every source row names its owner.

## Layout

- Desktop: persistent 240px sidebar, compact top status bar, bounded main workspace.
- Tablet: narrow icon rail and two-column content only where useful.
- Mobile: top identity strip, single-column content, persistent bottom navigation, full-width dialogs.

## Component tree

```text
WristMindControlPanel
  AppSidebar
  MobileTopBar
  MainWorkspace
    WorkspaceHeader
    KnowledgePage
      ModeSelector
      KnowledgeToolbar
      KnowledgeSummary
      KnowledgeSourcesTable
      KnowledgeSourcesMobileList
      UploadKnowledgeDialog
        ModeField
        ProcessingMethodPicker
        FileDropzone
  MobileNavigation
```

## State coverage

- Populated sources with ready, processing, and failed rows.
- Empty mode with a direct upload action.
- Loading keeps the table/list shape stable.
- Failed source gives a human-readable error and retry action.
- Upload is disabled until mode, processing method, and file are present.
- Keyboard focus is visible on navigation, rows, fields, and actions.
- Long filenames wrap on mobile and truncate with a title on desktop.

## Critical self-review

| Risk | Correction |
| --- | --- |
| Generic dashboard made of metric cards | Use one summary strip and a source table as the main working surface. |
| Mode isolation is only implied | Show the selected mode in the header, filter, upload dialog, and every source record. |
| OCR/Vision becomes a global toggle | Keep it inside every upload dialog and persist it on each source row. |
| Desktop table is squeezed onto mobile | Replace it with purpose-built mobile source records and bottom navigation. |
| Decorative mint overwhelms content | Reserve mint for selection, readiness, focus, and the primary action. |

## Detail views extension

- Product goal: inspect exactly what entered a mode's context, safely re-run extraction, and configure each mode without leaving the control surface.
- Information architecture: source list → source detail; mode list → mode settings; new chat → mode choice → persisted chat.
- Layout: desktop uses a narrow metadata rail beside a full-width inspector; mobile collapses to one column with wrapped actions.
- Components: `SourceDetailView`, `DeleteSourceDialog`, `ModeDetailView`, `ChatDraftView`.
- States: loading, empty extraction, processing, failed extraction, pagination, destructive confirmation, save success/error, disabled reprocess, and mobile overflow.
- Visual direction: preserve the dense dark control-room system; use mint only for active/ready/save states and red only for confirmed destructive actions.

## Conversation workspace extension

- Product goal: make every created chat immediately usable for reading history and sending questions without leaving the control panel.
- Component tree: `ChatsPage` → `ChatList` / `ChatDraftView` / `ChatDetailView` → `ChatHeader`, `MessageTimeline`, `Composer`.
- Interaction: the entire chat row and source row/card are primary click targets; all interactive controls use a pointer cursor and retain visible keyboard focus.
- State coverage: initial loading, empty chat, queued/context/generating phases, live answer deltas, stream failure, retry by sending again, and long scrollable answers.
- Critical risks: prevent duplicate submits, keep the immutable mode visible, avoid covering the composer with mobile navigation, and reload the persisted message after a completed or interrupted stream.

## Chat sources extension

- Product goal: make a chat's own materials inspectable without mixing them into the mode knowledge base. "База знаний" stays mode-scoped uploads; "Источники чата" exists only inside one conversation.
- Information architecture: chat → Источники чата → Рабочие / Найденные; one answer → Источники этого ответа.
- Entry points: a compact `Источники · N` button in the chat header (hidden at N = 0) and the existing per-answer `Источники · N` trigger under a completed answer.
- Components: `ChatSourcesPanel` (shared `Drawer`; desktop right drawer, mobile bottom sheet), `useChatSources`, pure `lib/chatSources.ts`.
- Interaction: the whole working/referenced card is the click target and opens the origin URL in a new tab; `Все` / `Рабочие` / `Найденные` filters stay inside the panel; per-answer mode offers a visible "Все источники чата" toggle.
- Visual direction: the same compact source cards as the per-answer panel; `Рабочий` badge for working materials; letter monogram instead of any third-party favicon service; extracted working content is never rendered.
- Deduplication: one unique list by origin URL; a Working Source always wins over a Referenced entry with the same URL.
