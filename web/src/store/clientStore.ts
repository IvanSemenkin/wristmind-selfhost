import {
  describeError,
  WristMindError,
} from '@/services/errors';
import {
  ACCOUNT_EVENT,
  type AccountEvent,
  type BootstrapResult,
  type WristMindEvent,
  type WristMindService,
} from '@/services/types';
import type { Session } from '@/session';
import type {
  Chat,
  ChatUpdateInput,
  Device,
  DeviceKind,
  KnowledgeSource,
  Message,
  Mode,
  ModeCreateInput,
  ModeUpdateInput,
  Model,
  OverviewStats,
  PairingCode,
  ProcessingMode,
  SendMessageInput,
  Settings,
  SourceContent,
  SystemHealth,
} from '@/types';
import { expectedPipeline } from '@/types';
import { createId } from '@/lib/id';

/* =============================================================================
   Client-side cache.

   The store is the only thing the UI reads. It owns:
     - the normalised snapshot exposed through `useSyncExternalStore`;
     - optimistic writes and their reconciliation with the service;
     - the merge of server-initiated events into the cache.

   It knows nothing about React, the router or mock data — it talks to the
   `WristMindService` interface only.
   ========================================================================== */

export type StoreStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface AppSnapshot {
  status: StoreStatus;
  error: string | null;
  session: Session;
  modes: Mode[];
  chats: Chat[];
  /** Messages per chat, in chronological order. */
  messages: Record<string, Message[]>;
  sources: KnowledgeSource[];
  /** Extracted content per source, loaded on demand. */
  sourceContent: Record<string, SourceContent>;
  devices: Device[];
  pairingCodes: PairingCode[];
  models: Model[];
  settings: Settings | null;
  stats: OverviewStats | null;
  health: SystemHealth | null;
  /** Bumped on every mutation; convenient as an effect dependency. */
  revision: number;
  /** Source index invalidation, independent of streamed message text. */
  chatSourcesRevision: number;
}

const EMPTY_MESSAGES: Message[] = [];

/** One refetch per slice per burst, however many events the burst contains. */
const REFRESH_DEBOUNCE_MS = 150;
/** Freshness cadence while the live stream is not connected. */
const FALLBACK_POLL_MS = 5_000;

export interface SendMessageRequest {
  chat_id: string;
  content: string;
  /**
   * The single request mode: false is AUTO (the Router decides retrieval),
   * true is RESEARCH (deeper checking and refinement, never a forced web).
   */
  research_mode?: boolean;
  signal?: AbortSignal;
}

export interface UploadSourceRequest {
  mode_id: string;
  title: string;
  file: File | { name: string; size: number; type: string };
  processing_mode: ProcessingMode;
}

export class WristMindClientStore {
  private snapshot: AppSnapshot;
  private listeners = new Set<() => void>();
  private unsubscribeService: (() => void) | null = null;
  /** Guards against a duplicate bootstrap (StrictMode double-mounts effects). */
  private bootstrapPromise: Promise<void> | null = null;
  private overviewRefreshPromise: Promise<void> | null = null;

  /** Live account feed: unsubscribe handle and the last applied cursor. */
  private unsubscribeEvents: (() => void) | null = null;
  private eventCursor = 0;
  private refreshTimer: number | null = null;
  private pollTimer: number | null = null;
  private visibilityHook: (() => void) | null = null;

  /**
   * Chats whose answer this tab is generating. A server snapshot must never
   * overwrite a live optimistic turn, so these are excluded from refetches
   * until the local stream has finished.
   */
  private readonly streamingChats = new Set<string>();
  private readonly openedChats = new Set<string>();
  private readonly messageLoads = new Map<string, Promise<void>>();

  /** Slices awaiting a refetch; filled by events, drained by `flushRefresh`. */
  private readonly dirty = {
    chats: false,
    modes: false,
    sources: false,
    devices: false,
    pairing: false,
    settings: false,
    overview: false,
    messages: new Set<string>(),
  };

  /** Exposed so views can recognise the device this panel runs on. */
  readonly session: Session;

  constructor(
    private readonly service: WristMindService,
    session: Session,
  ) {
    this.session = session;
    this.snapshot = {
      status: 'idle',
      error: null,
      session,
      modes: [],
      chats: [],
      messages: {},
      sources: [],
      sourceContent: {},
      devices: [],
      pairingCodes: [],
      models: [],
      settings: null,
      stats: null,
      health: null,
      revision: 0,
      chatSourcesRevision: 0,
    };
  }

  /* -- reactivity ---------------------------------------------------------- */

  getSnapshot = (): AppSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private commit(patch: Partial<AppSnapshot>): void {
    this.snapshot = {
      ...this.snapshot,
      ...patch,
      revision: this.snapshot.revision + 1,
    };
    for (const listener of this.listeners) listener();
  }

  private setStatus(status: StoreStatus, error: string | null = null): void {
    this.commit({ status, error });
  }

  /* -- bootstrap ----------------------------------------------------------- */

  async bootstrap(force = false): Promise<void> {
    if (!force && this.snapshot.status === 'ready') return;
    if (this.bootstrapPromise) return this.bootstrapPromise;
    this.bootstrapPromise = this.runBootstrap().finally(() => {
      this.bootstrapPromise = null;
    });
    return this.bootstrapPromise;
  }

  private async runBootstrap(): Promise<void> {
    this.setStatus('loading');
    try {
      const result = await this.loadAll();
      this.commit({
        status: 'ready',
        error: null,
        modes: result.modes,
        chats: result.chats,
        sources: result.sources,
        devices: result.devices,
        pairingCodes: result.pairingCodes,
        models: result.models,
        settings: result.settings,
        stats: result.stats,
        health: result.health,
      });
      this.unsubscribeService?.();
      this.unsubscribeService = this.service.subscribe(this.handleEvent);
      this.connectEvents();
    } catch (error) {
      this.setStatus('error', describeError(error, 'Не удалось загрузить панель'));
    }
  }

  private async loadAll(): Promise<BootstrapResult> {
    if (this.service.bootstrap) return this.service.bootstrap();
    const [modes, chats, sources, devices, pairingCodes, models, settings, stats, health] =
      await Promise.all([
        this.service.modes.list(),
        this.service.chats.list(),
        this.service.knowledge.list(),
        this.service.devices.list(),
        this.service.pairing.list(),
        this.service.models.list(),
        this.service.settings.get(),
        this.service.stats.overview(),
        this.service.system.health(),
      ]);
    return { modes, chats, sources, devices, pairingCodes, models, settings, stats, health };
  }

  /** Reloads a single chat's messages, used when opening a dialog. */
  loadMessages(chatId: string): Promise<void> {
    this.openedChats.add(chatId);
    if (this.snapshot.messages[chatId] !== undefined) return Promise.resolve();
    const pending = this.messageLoads.get(chatId);
    if (pending) return pending;
    const load = this.fetchMessages(chatId).finally(() => this.messageLoads.delete(chatId));
    this.messageLoads.set(chatId, load);
    return load;
  }

  private async fetchMessages(chatId: string): Promise<void> {
    const before = this.snapshot.messages[chatId];
    try {
      const messages = await this.service.chats.messages(chatId);
      // A local turn or a newer fetch may have changed this history meanwhile.
      if (this.streamingChats.has(chatId) || this.snapshot.messages[chatId] !== before) return;
      if (!this.snapshot.chats.some(chat => chat.id === chatId)) return;
      this.commit({ messages: { ...this.snapshot.messages, [chatId]: messages },
        chatSourcesRevision: this.snapshot.chatSourcesRevision + 1 });
    } catch {
      // A failed load is not an empty history. Keep it retryable on reopen,
      // account events, or return from offline/background mode.
    }
  }

  async loadSourceContent(sourceId: string): Promise<void> {
    if (this.snapshot.sourceContent[sourceId]) return;
    try {
      const content = await this.service.knowledge.content(sourceId);
      this.commit({
        sourceContent: { ...this.snapshot.sourceContent, [sourceId]: content },
      });
    } catch {
      this.commit({
        sourceContent: {
          ...this.snapshot.sourceContent,
          [sourceId]: { source_id: sourceId, pages: [], chunks: [] },
        },
      });
    }
  }

  private async refreshStats(): Promise<void> {
    try {
      const stats = await this.service.stats.overview();
      this.commit({ stats });
    } catch {
      /* stats are advisory; a failure must not break the action */
    }
  }

  /** Refresh the overview without replacing the whole page with a loading state. */
  refreshOverview(): Promise<void> {
    if (this.snapshot.status !== 'ready') return Promise.resolve();
    if (this.overviewRefreshPromise) return this.overviewRefreshPromise;
    this.overviewRefreshPromise = Promise.all([
      this.service.modes.list(),
      this.service.chats.list(),
      this.service.knowledge.list(),
      this.service.devices.list(),
      this.service.stats.overview(),
      this.service.system.health(),
    ]).then(([modes, chats, sources, devices, stats, health]) => {
      this.commit({ modes, chats, sources, devices, stats, health });
    }).finally(() => {
      this.overviewRefreshPromise = null;
    });
    return this.overviewRefreshPromise;
  }

  /* -- server-initiated events -------------------------------------------- */

  private handleEvent = (event: WristMindEvent): void => {
    switch (event.type) {
      case 'mode.updated':
        this.commit({
          modes: this.upsert(this.snapshot.modes, event.mode, (m) => m.id === event.mode.id),
        });
        break;
      case 'mode.removed':
        this.commit({
          modes: this.snapshot.modes.filter((m) => m.id !== event.mode_id),
          sources: this.snapshot.sources.filter((s) => s.mode_id !== event.mode_id),
          chats: this.snapshot.chats.filter((c) => c.mode_id !== event.mode_id),
        });
        break;
      case 'chat.updated':
        this.commit({
          chats: this.upsert(this.snapshot.chats, event.chat, (c) => c.id === event.chat.id),
        });
        break;
      case 'chat.removed': {
        const messages = { ...this.snapshot.messages };
        delete messages[event.chat_id];
        this.commit({
          chats: this.snapshot.chats.filter((c) => c.id !== event.chat_id),
          messages,
        });
        break;
      }
      case 'message.updated':
        this.patchMessages(event.message.chat_id, (list) =>
          this.upsert(list, event.message, (m) => m.id === event.message.id),
        );
        break;
      case 'source.updated':
        this.commit({
          sources: this.upsert(this.snapshot.sources, event.source, (s) => s.id === event.source.id),
        });
        break;
      case 'source.removed': {
        const content = { ...this.snapshot.sourceContent };
        delete content[event.source_id];
        this.commit({
          sources: this.snapshot.sources.filter((s) => s.id !== event.source_id),
          sourceContent: content,
        });
        break;
      }
      case 'device.updated':
        this.commit({
          devices: this.upsert(this.snapshot.devices, event.device, (d) => d.id === event.device.id),
        });
        break;
      case 'device.removed':
        this.commit({ devices: this.snapshot.devices.filter((d) => d.id !== event.device_id) });
        break;
      case 'pairing.updated':
        this.commit({
          pairingCodes: this.upsert(
            this.snapshot.pairingCodes,
            event.code,
            (c) => c.code === event.code.code,
          ),
        });
        break;
      case 'pairing.removed':
        this.commit({ pairingCodes: this.snapshot.pairingCodes.filter((c) => c.code !== event.code) });
        break;
    }
  };

  private upsert<T>(list: T[], item: T, match: (existing: T) => boolean): T[] {
    const index = list.findIndex(match);
    if (index === -1) return [item, ...list];
    const next = [...list];
    next[index] = item;
    return next;
  }

  /* -- live account feed --------------------------------------------------- */

  /**
   * Subscribes to the server's change stream.
   *
   * The stream carries identifiers, not entities: each event marks a slice
   * dirty and the slice is refetched once per burst. That keeps a single source
   * of truth — the API — and means a payload that was already superseded on the
   * server cannot overwrite newer local state.
   */
  private connectEvents(): void {
    this.disconnectEvents();
    this.startVisibilityWatch();
    if (!this.service.subscribeAccountEvents) {
      // No stream in this implementation: polling is the only freshness path.
      this.startPolling();
      return;
    }
    this.unsubscribeEvents = this.service.subscribeAccountEvents(this.eventCursor, {
      onEvent: (event) => {
        this.eventCursor = Math.max(this.eventCursor, event.id);
        this.handleAccountEvent(event);
      },
      onResync: () => {
        // The cursor fell behind the retention window, so some changes were
        // never delivered. Reload once from the tail instead of trusting a
        // cache that is known to be incomplete.
        this.eventCursor = 0;
        void this.bootstrap(true);
      },
      onStatusChange: (connected) => {
        if (connected) this.stopPolling();
        else this.startPolling();
      },
    });
  }

  private disconnectEvents(): void {
    this.unsubscribeEvents?.();
    this.unsubscribeEvents = null;
    this.stopPolling();
  }

  private startVisibilityWatch(): void {
    if (this.visibilityHook) return;
    this.visibilityHook = () => {
      if (document.visibilityState === 'hidden') return;
      // A background tab is throttled, so whatever it shows is stale by the
      // time it is looked at again. Treat every return as a cache miss.
      this.dirty.chats = true;
      this.dirty.overview = true;
      for (const chatId of this.openedChats) {
        this.dirty.messages.add(chatId);
      }
      void this.flushRefresh();
    };
    document.addEventListener('visibilitychange', this.visibilityHook);
    window.addEventListener('online', this.visibilityHook);
  }

  private handleAccountEvent(event: AccountEvent): void {
    const chatId = typeof event.data.chat_id === 'string' ? event.data.chat_id : null;
    switch (event.type) {
      case ACCOUNT_EVENT.chatCreated:
      case ACCOUNT_EVENT.chatUpdated:
        this.dirty.chats = true;
        this.dirty.overview = true;
        if (chatId) this.dirty.messages.add(chatId);
        break;
      case ACCOUNT_EVENT.chatDeleted:
        if (chatId) {
          const messages = { ...this.snapshot.messages };
          delete messages[chatId];
          this.commit({
            chats: this.snapshot.chats.filter((chat) => chat.id !== chatId),
            messages,
          });
        }
        this.dirty.chats = true;
        this.dirty.overview = true;
        break;
      case ACCOUNT_EVENT.messageCreated:
      case ACCOUNT_EVENT.messageUpdated:
        if (chatId) this.dirty.messages.add(chatId);
        // A new turn changes title and ordering of the chat it belongs to.
        this.dirty.chats = true;
        break;
      case ACCOUNT_EVENT.modeUpdated:
      case ACCOUNT_EVENT.modeRemoved:
        this.dirty.modes = true;
        this.dirty.sources = true;
        this.dirty.chats = true;
        this.dirty.overview = true;
        break;
      case ACCOUNT_EVENT.sourceUpdated:
      case ACCOUNT_EVENT.sourceRemoved:
        this.dirty.sources = true;
        this.dirty.overview = true;
        if (chatId) this.dirty.messages.add(chatId);
        break;
      case ACCOUNT_EVENT.deviceUpdated:
      case ACCOUNT_EVENT.deviceRemoved:
        this.dirty.devices = true;
        this.dirty.overview = true;
        break;
      case ACCOUNT_EVENT.settingsUpdated:
        this.dirty.settings = true;
        this.dirty.modes = true;
        break;
      case ACCOUNT_EVENT.pairingUpdated:
        this.dirty.pairing = true;
        break;
      default:
        this.dirty.overview = true;
    }
    this.scheduleRefresh();
  }

  private scheduleRefresh(): void {
    if (this.refreshTimer !== null) return;
    this.refreshTimer = window.setTimeout(() => {
      this.refreshTimer = null;
      void this.flushRefresh();
    }, REFRESH_DEBOUNCE_MS);
  }

  private async flushRefresh(): Promise<void> {
    if (this.snapshot.status !== 'ready') return;
    const pending = { ...this.dirty, messages: new Set(this.dirty.messages) };
    this.dirty.chats = false;
    this.dirty.modes = false;
    this.dirty.sources = false;
    this.dirty.devices = false;
    this.dirty.pairing = false;
    this.dirty.settings = false;
    this.dirty.overview = false;
    this.dirty.messages.clear();

    const work: Promise<void>[] = [];
    if (pending.chats) work.push(this.reloadChats());
    if (pending.modes) work.push(this.reloadModes());
    if (pending.sources) work.push(this.reloadSources());
    if (pending.devices) work.push(this.reloadDevices());
    if (pending.pairing) work.push(this.reloadPairing());
    if (pending.settings) work.push(this.reloadSettings());
    if (pending.overview) work.push(this.reloadOverview());
    for (const chatId of pending.messages) work.push(this.reloadMessages(chatId));
    await Promise.all(work);
  }

  /* -- polling fallback ---------------------------------------------------- */

  private startPolling(): void {
    if (this.pollTimer !== null) return;
    this.pollTimer = window.setInterval(() => {
      void this.pollFallback();
    }, FALLBACK_POLL_MS);
  }

  private stopPolling(): void {
    if (this.pollTimer === null) return;
    window.clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  /**
   * Freshness without a stream: refetch the lists and every chat history this
   * session has already opened. Chats this tab is streaming itself are skipped
   * so the fallback cannot fight the local optimistic turn.
   */
  private async pollFallback(): Promise<void> {
    if (this.snapshot.status !== 'ready') return;
    this.dirty.chats = true;
    for (const chatId of this.openedChats) {
      if (!this.streamingChats.has(chatId)) this.dirty.messages.add(chatId);
    }
    await this.flushRefresh();
  }

  /* -- targeted refetches -------------------------------------------------- */

  private async reloadChats(): Promise<void> {
    try {
      this.commit({ chats: await this.service.chats.list() });
    } catch {
      /* a failed refresh keeps the cached list */
    }
  }

  private async reloadModes(): Promise<void> {
    try {
      this.commit({ modes: await this.service.modes.list() });
    } catch {
      /* keep the cached modes */
    }
  }

  private async reloadSources(): Promise<void> {
    try {
      this.commit({ sources: await this.service.knowledge.list(),
        chatSourcesRevision: this.snapshot.chatSourcesRevision + 1 });
    } catch {
      /* keep the cached sources */
    }
  }

  private async reloadDevices(): Promise<void> {
    try {
      this.commit({ devices: await this.service.devices.list() });
    } catch {
      /* keep the cached devices */
    }
  }

  private async reloadPairing(): Promise<void> {
    try {
      this.commit({ pairingCodes: await this.service.pairing.list() });
    } catch {
      /* keep the cached codes */
    }
  }

  private async reloadSettings(): Promise<void> {
    try {
      const [settings, models] = await Promise.all([this.service.settings.get(), this.service.models.list()]);
      this.commit({ settings, models });
    } catch {
      /* keep the cached settings */
    }
  }

  private async reloadOverview(): Promise<void> {
    try {
      const stats = await this.service.stats.overview();
      this.commit({ stats });
    } catch {
      /* stats are advisory */
    }
    try {
      const health = await this.service.system.health();
      this.commit({ health });
    } catch {
      /* health is advisory */
    }
  }

  /**
   * Refetches one chat's history. Skipped entirely for chats this tab is
   * streaming, and for chats that were never opened in this session: an event
   * announcing a chat is not a reason to download its history.
   */
  private async reloadMessages(chatId: string): Promise<void> {
    if (this.streamingChats.has(chatId) || !this.openedChats.has(chatId)) return;
    if (this.snapshot.messages[chatId] === undefined) { await this.loadMessages(chatId); return; }
    await this.fetchMessages(chatId);
  }

  /* -- message helpers ----------------------------------------------------- */

  private patchMessages(chatId: string, updater: (list: Message[]) => Message[]): void {
    const current = this.snapshot.messages[chatId] ?? EMPTY_MESSAGES;
    this.commit({ messages: { ...this.snapshot.messages, [chatId]: updater(current) } });
  }

  private patchMessage(chatId: string, messageId: string, patch: (message: Message) => Message): void {
    this.patchMessages(chatId, (list) =>
      list.map((message) => (message.id === messageId ? patch(message) : message)),
    );
  }

  /* ======================================================================== */
  /* Modes                                                                    */
  /* ======================================================================== */

  async createMode(input: ModeCreateInput): Promise<Mode> {
    const mode = await this.service.modes.create(input);
    // The service also publishes `mode.updated`, so the write is idempotent.
    this.commit({ modes: this.upsert(this.snapshot.modes, mode, (m) => m.id === mode.id) });
    void this.refreshStats();
    return mode;
  }

  async updateMode(id: string, input: ModeUpdateInput): Promise<Mode> {
    const mode = await this.service.modes.update(id, input);
    this.commit({ modes: this.snapshot.modes.map((m) => (m.id === id ? mode : m)) });
    return mode;
  }

  async deleteMode(id: string): Promise<void> {
    await this.service.modes.remove(id);
    const messages = { ...this.snapshot.messages };
    for (const chat of this.snapshot.chats.filter((c) => c.mode_id === id)) {
      delete messages[chat.id];
    }
    this.commit({
      modes: this.snapshot.modes.filter((m) => m.id !== id),
      chats: this.snapshot.chats.filter((c) => c.mode_id !== id),
      sources: this.snapshot.sources.filter((s) => s.mode_id !== id),
      messages,
    });
    void this.refreshStats();
  }

  /* ======================================================================== */
  /* Chats                                                                    */
  /* ======================================================================== */

  async createChat(modeId: string | null, title?: string): Promise<Chat> {
    const chat = await this.service.chats.create({ mode_id: modeId, title });
    this.commit({
      chats: this.upsert(this.snapshot.chats, chat, (c) => c.id === chat.id),
      messages: { ...this.snapshot.messages, [chat.id]: this.snapshot.messages[chat.id] ?? [] },
    });
    return chat;
  }

  async updateChat(id: string, patch: ChatUpdateInput): Promise<Chat> {
    const chat = await this.service.chats.update(id, patch);
    this.commit({ chats: this.snapshot.chats.map((c) => (c.id === id ? chat : c)) });
    return chat;
  }

  async deleteChat(id: string): Promise<void> {
    await this.service.chats.remove(id);
    const messages = { ...this.snapshot.messages };
    delete messages[id];
    this.commit({
      chats: this.snapshot.chats.filter((c) => c.id !== id),
      messages,
    });
  }

  /**
   * Sends a message and keeps the UI in sync with the stream:
   * the user message and a temporary assistant message appear immediately,
   * phases and text deltas update that placeholder, and the final message
   * replaces it when the stream ends.
   */
  async sendMessage(request: SendMessageRequest): Promise<Message | null> {
    const { chat_id: chatId } = request;
    if (this.streamingChats.has(chatId)) throw new WristMindError('В этом чате уже формируется ответ', { code: 'conflict' });
    // While this tab owns the stream, server events for this chat must not
    // replace the optimistic turn or its live text.
    this.streamingChats.add(chatId);
    const chat = this.snapshot.chats.find((c) => c.id === chatId);
    const mode = this.snapshot.modes.find((m) => m.id === chat?.mode_id);
    const defaultModel = this.snapshot.settings?.default_model_id ?? null;
    const now = new Date().toISOString();

    const clientMessageId = createId('msg_local');
    const clientAssistantId = createId('msg_local');

    const optimisticUser: Message = {
      id: clientMessageId,
      chat_id: chatId,
      role: 'user',
      content: request.content,
      status: 'complete',
      provider: null,
      model_id: null,
      usage: null,
      timings: null,
      sources: [],
      phases: [],
      created_at: now,
    };

    // The client renders the whole pipeline at once; the stream then walks it.
    // Only the mode is known up front: in AUTO the Router decides retrieval, so
    // no search phase may be pre-rendered.
    const plannedPhases = expectedPipeline({
      research_mode: request.research_mode,
    });

    const temporaryAssistant: Message = {
      id: clientAssistantId,
      chat_id: chatId,
      role: 'assistant',
      content: '',
      status: 'queued',
      provider: null,
      model_id: mode?.response_model_id ?? defaultModel,
      usage: null,
      timings: null,
      sources: [],
      phases: plannedPhases,
      created_at: now,
    };

    this.patchMessages(chatId, (list) => [...list, optimisticUser, temporaryAssistant]);

    const payload: SendMessageInput = {
      chat_id: chatId,
      content: request.content,
      // The console never forces the web: AUTO lets the Router decide, and
      // RESEARCH only asks for deeper checking.
      research_mode: request.research_mode === true,
      web_search: false,
      web_research: false,
      client_message_id: clientMessageId,
      client_assistant_id: clientAssistantId,
      signal: request.signal,
    };

    try {
      const final = await this.service.chats.send(payload, {
        onPhase: (_messageId, phase) =>
          this.patchMessage(chatId, clientAssistantId, (message) => ({
            ...message,
            status: phase,
            phases: message.phases.includes(phase) ? message.phases : [...message.phases, phase],
          })),
        onDelta: (_messageId, delta) =>
          this.patchMessage(chatId, clientAssistantId, (message) => ({
            ...message,
            content: message.content + delta,
          })),
        onFinal: (message) => {
          // The backend may assign its own id to the final message; the
          // placeholder is replaced by `replaces_client_id` or by id.
          this.patchMessages(chatId, (list) => {
            const withoutPlaceholder = list.filter(
              (m) => m.id !== clientAssistantId && m.id !== message.id,
            );
            return [...withoutPlaceholder, message];
          });
          this.commit({ chatSourcesRevision: this.snapshot.chatSourcesRevision + 1 });
        },
        onError: (messageId, message) =>
          this.patchMessage(chatId, clientAssistantId, (current) => ({
            ...current,
            id: messageId || current.id,
            status: 'error',
            content: current.content || message,
          })),
      });
      return final;
    } catch (error) {
      const aborted = error instanceof WristMindError && error.code === 'aborted';
      this.patchMessage(chatId, clientAssistantId, (message) => ({
        ...message,
        status: aborted ? 'cancelled' : 'error',
        content:
          message.content ||
          (aborted
            ? '(генерация остановлена)'
            : describeError(error, 'Не удалось получить ответ')),
      }));
      if (!aborted) throw error;
      return null;
    } finally {
      this.streamingChats.delete(chatId);
      // Events received during streaming were deliberately skipped. Reconcile
      // once afterwards so optimistic ids and the real server turn converge.
      this.openedChats.add(chatId);
      this.dirty.messages.add(chatId);
      this.dirty.chats = true;
      this.scheduleRefresh();
    }
  }

  /* ======================================================================== */
  /* Knowledge base                                                           */
  /* ======================================================================== */

  async uploadSource(request: UploadSourceRequest): Promise<KnowledgeSource> {
    const result = await this.service.knowledge.upload({
      mode_id: request.mode_id,
      title: request.title,
      file: request.file,
      processing_mode: request.processing_mode,
    });
    this.commit({
      sources: this.upsert(this.snapshot.sources, result.source, (s) => s.id === result.source.id),
    });
    // Status transitions arrive through the service event feed.
    return result.source;
  }

  async reprocessSource(id: string): Promise<void> {
    await this.service.knowledge.reprocess(id);
    const fresh = await this.service.knowledge.get(id);
    this.commit({
      sources: this.snapshot.sources.map((s) => (s.id === id ? fresh : s)),
      sourceContent: Object.fromEntries(
        Object.entries(this.snapshot.sourceContent).filter(([key]) => key !== id),
      ),
    });
  }

  async deleteSource(id: string): Promise<void> {
    await this.service.knowledge.remove(id);
    const content = { ...this.snapshot.sourceContent };
    delete content[id];
    this.commit({
      sources: this.snapshot.sources.filter((s) => s.id !== id),
      sourceContent: content,
    });
    void this.refreshStats();
  }

  /* ======================================================================== */
  /* Devices & pairing                                                        */
  /* ======================================================================== */

  async createPairingCode(targetKind: DeviceKind | null): Promise<PairingCode> {
    const code = await this.service.pairing.create(targetKind);
    this.commit({
      pairingCodes: this.upsert(this.snapshot.pairingCodes, code, (c) => c.code === code.code),
    });
    return code;
  }

  async revokePairingCode(code: string): Promise<void> {
    await this.service.pairing.revoke(code);
    this.commit({ pairingCodes: this.snapshot.pairingCodes.filter((c) => c.code !== code) });
  }

  async revokeDevice(id: string): Promise<void> {
    await this.service.devices.revoke(id);
    this.commit({ devices: this.snapshot.devices.filter((device) => device.id !== id) });
    // Health may change when a gateway device is revoked.
    void this.service.system
      .health()
      .then((health) => this.commit({ health }))
      .catch(() => undefined);
  }

  async removeDevice(id: string): Promise<void> {
    await this.service.devices.remove(id);
    this.commit({ devices: this.snapshot.devices.filter((device) => device.id !== id) });
  }

  /* ======================================================================== */
  /* Settings & system                                                        */
  /* ======================================================================== */

  async updateSettings(patch: Partial<Settings>): Promise<Settings> {
    const settings = await this.service.settings.update(patch);
    this.commit({ settings });
    return settings;
  }

  async resetDemoData(): Promise<void> {
    await this.service.system.resetDemoData();
    await this.bootstrap(true);
  }

  dispose(): void {
    this.unsubscribeService?.();
    this.unsubscribeService = null;
    this.disconnectEvents();
    if (this.refreshTimer !== null) {
      window.clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    if (this.visibilityHook) {
      document.removeEventListener('visibilitychange', this.visibilityHook);
      window.removeEventListener('online', this.visibilityHook);
      this.visibilityHook = null;
    }
    this.listeners.clear();
  }
}
