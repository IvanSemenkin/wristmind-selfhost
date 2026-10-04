import { composeAnswer, deriveChatTitle, type AnswerCandidate } from './answers';
import {
  buildContent,
  buildHealth,
  buildOverviewStats,
  SEED_CHATS,
  SEED_DEVICES,
  SEED_MESSAGES,
  SEED_MODELS,
  SEED_MODES,
  SEED_PAIRING_CODES,
  SEED_SETTINGS,
  SEED_SOURCE_CONTENT,
  SEED_SOURCES,
  type SourceSpec,
} from './fixtures';
import { WristMindError } from '@/services/errors';
import type {
  BootstrapResult,
  WristMindEvent,
  WristMindEventListener,
  WristMindService,
} from '@/services/types';
import type { Session } from '@/session';
import type {
  Chat,
  ChatSources,
  ChatWorkingSourceText,
  ChatStreamHandlers,
  Device,
  DeviceKind,
  KnowledgeSource,
  Message,
  MessagePhase,
  Mode,
  ModeCreateInput,
  ModeUpdateInput,
  PairingCode,
  SendMessageInput,
  Settings,
  SourceContent,
  SourceUploadInput,
  SourceUploadResult,
} from '@/types';
import { expectedPipeline, PAIRING_CODE_LENGTH, PAIRING_CODE_TTL_MS } from '@/types';
import { createId } from '@/lib/id';

/* =============================================================================
   In-memory implementation of `WristMindService`.

   Behaves like the real backend: every call is async with latency, ingest runs
   as a background job that publishes change events, and completions stream
   phase-by-phase with incremental text.

   This file is the ONLY place that knows the console runs without a server.
   Replacing it with an HTTP adapter changes nothing above the service seam.
   ========================================================================== */

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** Latency profile per call type, so the console feels like a networked app. */
const LATENCY = {
  read: 220,
  write: 320,
  bootstrap: 520,
  content: 380,
} as const;

const PHASE_TIMING: Record<MessagePhase, number> = {
  queued: 200,
  context: 420,
  search_query: 340,
  searching: 700,
  reviewing_sources: 520,
  opening_source: 560,
  generating: 300,
  research_drafting: 360,
  research_checking: 440,
  research_refining: 380,
};

interface MockState {
  modes: Mode[];
  chats: Chat[];
  messages: Record<string, Message[]>;
  sources: KnowledgeSource[];
  sourceContent: Record<string, SourceContent>;
  devices: Device[];
  pairingCodes: PairingCode[];
  settings: Settings;
}

function initialState(): MockState {
  return {
    modes: SEED_MODES.map((mode) => ({ ...mode })),
    chats: SEED_CHATS.map((chat) => ({ ...chat })),
    messages: Object.fromEntries(
      Object.entries(SEED_MESSAGES).map(([chatId, list]) => [chatId, list.map((m) => ({ ...m }))]),
    ),
    sources: SEED_SOURCES.map((source) => ({ ...source })),
    sourceContent: Object.fromEntries(
      Object.entries(SEED_SOURCE_CONTENT).map(([id, content]) => [
        id,
        { ...content, pages: [...content.pages], chunks: [...content.chunks] },
      ]),
    ),
    devices: SEED_DEVICES.map((device) => ({ ...device })),
    pairingCodes: SEED_PAIRING_CODES.map((code) => ({ ...code })),
    settings: { ...SEED_SETTINGS },
  };
}

export class MockWristMindService implements WristMindService {
  private state: MockState = initialState();
  private listeners = new Set<WristMindEventListener>();

  /** Bumped on reset so background jobs from the previous dataset abort. */
  private epoch = 0;

  constructor(private readonly session: Session) {}

  /* -- change feed --------------------------------------------------------- */

  subscribe = (listener: WristMindEventListener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private emit(event: WristMindEvent): void {
    for (const listener of this.listeners) listener(event);
  }

  /* -- helpers ------------------------------------------------------------- */

  private now(): string {
    return new Date().toISOString();
  }

  private requireMode(id: string): Mode {
    const mode = this.state.modes.find((item) => item.id === id && item.deleted_at === null);
    if (!mode) throw new WristMindError(`Режим ${id} не найден`, { code: 'not_found' });
    return mode;
  }

  private requireChat(id: string): Chat {
    const chat = this.state.chats.find((item) => item.id === id);
    if (!chat) throw new WristMindError(`Чат ${id} не найден`, { code: 'not_found' });
    return chat;
  }

  private requireSource(id: string): KnowledgeSource {
    const source = this.state.sources.find((item) => item.id === id);
    if (!source) throw new WristMindError(`Источник ${id} не найден`, { code: 'not_found' });
    return source;
  }

  private async loadAll(): Promise<BootstrapResult> {
    const [modes, chats, sources, devices, pairingCodes, models, settings, stats, health] =
      await Promise.all([
        this.modes.list(),
        this.chats.list(),
        this.knowledge.list(),
        this.devices.list(),
        this.pairing.list(),
        this.models.list(),
        this.settings.get(),
        this.stats.overview(),
        this.system.health(),
      ]);
    return { modes, chats, sources, devices, pairingCodes, models, settings, stats, health };
  }

  async bootstrap(): Promise<BootstrapResult> {
    await delay(LATENCY.bootstrap);
    return this.loadAll();
  }

  /* -- modes --------------------------------------------------------------- */

  modes = {
    list: async (): Promise<Mode[]> => {
      await delay(LATENCY.read);
      return this.state.modes
        .filter((mode) => mode.deleted_at === null)
        .map((mode) => ({ ...mode }));
    },

    get: async (id: string): Promise<Mode> => {
      await delay(LATENCY.read);
      return { ...this.requireMode(id) };
    },

    create: async (input: ModeCreateInput): Promise<Mode> => {
      await delay(LATENCY.write);
      const stamp = this.now();
      const mode: Mode = {
        id: createId('mode'),
        name: input.name,
        description: input.description,
        color: input.color,
        icon: input.icon ?? null,
        telegram_emoji_id: input.telegram_emoji_id ?? null,
        system_prompt: input.system_prompt,
        response_model_id: input.response_model_id,
        hidden_on_watch: input.hidden_on_watch,
        created_at: stamp,
        updated_at: stamp,
        deleted_at: null,
      };
      this.state.modes = [...this.state.modes, mode];
      this.emit({ type: 'mode.updated', mode });
      return { ...mode };
    },

    update: async (id: string, input: ModeUpdateInput): Promise<Mode> => {
      await delay(LATENCY.write);
      const existing = this.requireMode(id);
      const updated: Mode = { ...existing, ...input, updated_at: this.now() };
      this.state.modes = this.state.modes.map((mode) => (mode.id === id ? updated : mode));
      this.emit({ type: 'mode.updated', mode: { ...updated } });
      return { ...updated };
    },

    remove: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      this.requireMode(id);
      const stamp = this.now();
      // Soft delete on the server; the console drops the mode and its data.
      this.state.modes = this.state.modes.map((mode) =>
        mode.id === id ? { ...mode, deleted_at: stamp, updated_at: stamp } : mode,
      );
      const chatIds = new Set(
        this.state.chats.filter((chat) => chat.mode_id === id).map((chat) => chat.id),
      );
      this.state.chats = this.state.chats.filter((chat) => chat.mode_id !== id);
      this.state.sources = this.state.sources.filter((source) => source.mode_id !== id);
      const messages = { ...this.state.messages };
      for (const chatId of chatIds) delete messages[chatId];
      this.state.messages = messages;
      this.emit({ type: 'mode.removed', mode_id: id });
      for (const chatId of chatIds) this.emit({ type: 'chat.removed', chat_id: chatId });
    },
  };

  /* -- chats --------------------------------------------------------------- */

  chats = {
    list: async (): Promise<Chat[]> => {
      await delay(LATENCY.read);
      return this.state.chats.map((chat) => this.withModeState(chat));
    },

    get: async (id: string): Promise<Chat> => {
      await delay(LATENCY.read);
      return this.withModeState(this.requireChat(id));
    },

    create: async (input: { mode_id: string | null; title?: string }): Promise<Chat> => {
      await delay(LATENCY.write);
      const mode = input.mode_id ? this.requireMode(input.mode_id) : null;
      const stamp = this.now();
      const chat: Chat = {
        id: createId('chat'),
        mode_id: mode?.id ?? null,
        mode_name: mode?.name ?? null,
        mode_deleted: false,
        title: input.title?.trim() || (mode ? 'Новый диалог' : 'Быстрый чат'),
        created_at: stamp,
        updated_at: stamp,
        deleted_at: null,
        pinned: false,
      };
      this.state.chats = [chat, ...this.state.chats];
      this.state.messages = { ...this.state.messages, [chat.id]: [] };
      this.emit({ type: 'chat.updated', chat: { ...chat } });
      return { ...chat };
    },

    update: async (id: string, input: { title?: string; pinned?: boolean }): Promise<Chat> => {
      await delay(LATENCY.write);
      const existing = this.requireChat(id);
      const updated: Chat = { ...existing, ...input, updated_at: this.now() };
      this.state.chats = this.state.chats.map((chat) => (chat.id === id ? updated : chat));
      this.emit({ type: 'chat.updated', chat: { ...updated } });
      return { ...updated };
    },

    remove: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      this.requireChat(id);
      this.state.chats = this.state.chats.filter((chat) => chat.id !== id);
      const messages = { ...this.state.messages };
      delete messages[id];
      this.state.messages = messages;
      this.emit({ type: 'chat.removed', chat_id: id });
    },

    messages: async (chatId: string): Promise<Message[]> => {
      await delay(LATENCY.read);
      return (this.state.messages[chatId] ?? []).map((message) => ({ ...message }));
    },

    // The mock has no server-side extraction, so the chat index is derived from
    // the same per-message metadata the real backend records.
    sources: async (chatId: string): Promise<ChatSources> => {
      await delay(LATENCY.read);
      this.requireChat(chatId);
      const referenced: ChatSources['referenced'] = [];
      const working: ChatSources['working'] = [];
      const seenUrls = new Set<string>();
      const seenTitles = new Set<string>();
      for (const message of this.state.messages[chatId] ?? []) {
        for (const source of message.web_sources ?? []) {
          const url = typeof source.url === 'string' ? source.url.trim() : '';
          if (!url || seenUrls.has(url)) continue;
          seenUrls.add(url);
          referenced.push({
            id: source.id,
            title: source.title,
            url,
            snippet: typeof source.snippet === 'string' ? source.snippet : null,
            retrieved_at: source.retrieved_at ?? null,
            message_id: message.id,
          });
        }
        for (const title of message.timings?.local_context?.working_titles ?? []) {
          if (!title || seenTitles.has(title)) continue;
          seenTitles.add(title);
          working.push({
            id: `working-${title}`,
            title,
            origin_url: null,
            origin_title: null,
            status: 'ready',
            created_at: message.created_at,
          });
        }
      }
      return { working, referenced };
    },

    workingSourceText: async (chatId: string, _sourceId: string): Promise<ChatWorkingSourceText> => {
      this.requireChat(chatId);
      throw new Error('Текст доступен только для материалов, сохранённых на сервере');
    },

    send: async (input: SendMessageInput, handlers?: ChatStreamHandlers): Promise<Message> => {
      const chat = this.requireChat(input.chat_id);
      const mode = chat.mode_id ? this.state.modes.find((m) => m.id === chat.mode_id) ?? null : null;
      const epoch = this.epoch;
      const startedAt = performance.now();

      const assistantId = createId('msg');
      const phases = expectedPipeline({
        research_mode: input.research_mode,
      });

      // The server records the user message; the console already rendered an
      // optimistic copy under a client-generated id.
      const userMessage: Message = {
        id: input.client_message_id ?? createId('msg'),
        chat_id: chat.id,
        role: 'user',
        content: input.content,
        status: 'complete',
        provider: null,
        model_id: null,
        usage: null,
        timings: null,
        sources: [],
        phases: [],
        created_at: this.now(),
      };

      const assistant: Message = {
        id: assistantId,
        chat_id: chat.id,
        role: 'assistant',
        content: '',
        status: 'queued',
        provider: null,
        model_id: mode?.response_model_id ?? this.state.settings.default_model_id,
        usage: null,
        timings: null,
        sources: [],
        phases: [],
        created_at: this.now(),
      };

      this.state.messages = {
        ...this.state.messages,
        [chat.id]: [...(this.state.messages[chat.id] ?? []), userMessage],
      };

      const isAborted = () => epoch !== this.epoch || input.signal?.aborted === true;

      const finish = (patch: Partial<Message>): Message => {
        const final: Message = {
          ...assistant,
          ...patch,
          phases: phases as MessagePhase[],
          replaces_client_id: input.client_assistant_id ?? null,
          timings: {
            total_ms: Math.round(performance.now() - startedAt),
            first_token_ms: patch.content ? 240 : null,
          },
        };
        this.state.messages = {
          ...this.state.messages,
          [chat.id]: [...(this.state.messages[chat.id] ?? []), final],
        };
        this.state.chats = this.state.chats.map((item) =>
          item.id === chat.id ? { ...item, updated_at: final.created_at } : item,
        );
        return final;
      };

      // Retitle on the first user turn, exactly like the real backend does.
      const isFirstTurn = (this.state.messages[chat.id] ?? []).filter((m) => m.role === 'user').length === 1;
      if (isFirstTurn && ['Новый диалог', 'Быстрый чат', ''].includes(chat.title.trim())) {
        const retitled: Chat = {
          ...chat,
          title: deriveChatTitle(input.content),
          updated_at: this.now(),
        };
        this.state.chats = this.state.chats.map((item) => (item.id === chat.id ? retitled : item));
        this.emit({ type: 'chat.updated', chat: { ...retitled } });
      }

      const searchBoost = input.research_mode ? 1.7 : 1;

      for (const phase of phases) {
        assistant.status = phase;
        handlers?.onPhase?.(assistantId, phase);
        const base = PHASE_TIMING[phase] ?? 300;
        const scaled = phase === 'searching' || phase === 'reviewing_sources' ? base * searchBoost : base;
        await delay(scaled);
        if (isAborted()) {
          const final = finish({
            content: '(генерация остановлена)',
            status: 'cancelled',
          });
          handlers?.onFinal?.(final);
          return final;
        }
      }

      const candidates: AnswerCandidate[] = this.state.sources
        .filter((source) => source.mode_id === mode?.id && source.status === 'ready')
        .map((source) => ({
          source,
          chunks: this.state.sourceContent[source.id]?.chunks ?? [],
        }))
        .filter((candidate) => candidate.chunks.length > 0);

      const answer = composeAnswer({
        question: input.content,
        mode,
        candidates,
        web_search: input.web_search === true,
        web_research: input.research_mode === true,
      });

      assistant.model_id = answer.model_id ?? assistant.model_id;
      assistant.provider =
        SEED_MODELS.find((model) => model.id === assistant.model_id)?.provider ?? null;
      assistant.sources = answer.sources;

      const chunks = answer.content.match(/[\s\S]{1,7}/g) ?? [];
      let streamed = '';
      for (const chunk of chunks) {
        await delay(12);
        if (isAborted()) break;
        streamed += chunk;
        handlers?.onDelta?.(assistantId, chunk);
      }

      const aborted = isAborted();
      const final = finish({
        content: aborted ? `${streamed}\n\n(генерация остановлена)` : answer.content,
        status: aborted ? 'cancelled' : 'complete',
        sources: answer.sources,
      });

      handlers?.onFinal?.(final);
      return final;
    },
  };

  private withModeState(chat: Chat): Chat {
    const mode = chat.mode_id
      ? this.state.modes.find((item) => item.id === chat.mode_id)
      : undefined;
    return {
      ...chat,
      mode_name: chat.mode_id ? (mode?.name ?? chat.mode_name) : null,
      mode_deleted: Boolean(chat.mode_id) && (!mode || mode.deleted_at !== null),
    };
  }

  /* -- knowledge base ------------------------------------------------------ */

  knowledge = {
    list: async (modeId?: string): Promise<KnowledgeSource[]> => {
      await delay(LATENCY.read);
      return this.state.sources
        .filter((source) => (modeId ? source.mode_id === modeId : true))
        .map((source) => ({ ...source }));
    },

    get: async (id: string): Promise<KnowledgeSource> => {
      await delay(LATENCY.read);
      return { ...this.requireSource(id) };
    },

    content: async (id: string): Promise<SourceContent> => {
      await delay(LATENCY.content);
      this.requireSource(id);
      return (
        this.state.sourceContent[id] ?? { source_id: id, pages: [], chunks: [] }
      );
    },

    upload: async (input: SourceUploadInput): Promise<SourceUploadResult> => {
      await delay(LATENCY.write);
      const mode = this.requireMode(input.mode_id);
      const filename = input.file.name;
      const mediaType = input.file.type || (filename.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/jpeg');

      const source: KnowledgeSource = {
        id: createId('src'),
        mode_id: mode.id,
        title: input.title.trim() || filename,
        filename,
        media_type: mediaType,
        processing_mode: input.processing_mode,
        status: 'uploading',
        page_count: 0,
        chunk_count: 0,
        token_count: 0,
        error: null,
        created_at: this.now(),
        updated_at: this.now(),
        progress: 0,
        stage: 'Загрузка файла',
      };

      this.state.sources = [source, ...this.state.sources];
      this.emit({ type: 'source.updated', source: { ...source } });

      const jobId = createId('job');
      void this.runIngestJob(source.id, {
        filename,
        mediaType,
        title: source.title,
        processing_mode: source.processing_mode,
      });
      return { source: { ...source }, job_id: jobId };
    },

    reprocess: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      const source = this.requireSource(id);
      this.state.sourceContent = Object.fromEntries(
        Object.entries(this.state.sourceContent).filter(([key]) => key !== id),
      );
      const reset: KnowledgeSource = {
        ...source,
        status: 'uploading',
        page_count: 0,
        chunk_count: 0,
        token_count: 0,
        error: null,
        progress: 0,
        stage: 'Постановка в очередь',
        updated_at: this.now(),
      };
      this.state.sources = this.state.sources.map((item) => (item.id === id ? reset : item));
      this.emit({ type: 'source.updated', source: { ...reset } });
      void this.runIngestJob(id, {
        filename: source.filename,
        mediaType: source.media_type,
        title: source.title,
        processing_mode: source.processing_mode,
      });
    },

    remove: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      this.requireSource(id);
      this.state.sources = this.state.sources.filter((source) => source.id !== id);
      this.state.sourceContent = Object.fromEntries(
        Object.entries(this.state.sourceContent).filter(([key]) => key !== id),
      );
      this.emit({ type: 'source.removed', source_id: id });
    },
  };

  /**
   * Background ingest job. Publishes `source.updated` on every transition, which
   * is how the list refreshes without a page reload — the same contract an HTTP
   * adapter would satisfy with SSE or polling.
   */
  private async runIngestJob(
    sourceId: string,
    input: { filename: string; mediaType: string; title: string; processing_mode: 'OCR' | 'VISION' },
  ): Promise<void> {
    const epoch = this.epoch;
    const steps: Array<{ progress: number; stage: string; status: KnowledgeSource['status'] }> = [
      { progress: 0.08, stage: 'Определение структуры документа', status: 'uploading' },
      { progress: 0.24, stage: input.processing_mode === 'VISION' ? 'Vision-анализ страниц' : 'Распознавание текста (OCR)', status: 'processing' },
      { progress: 0.52, stage: input.processing_mode === 'VISION' ? 'Разбор таблиц и подписей' : 'Извлечение текстового слоя', status: 'processing' },
      { progress: 0.74, stage: 'Разбиение на фрагменты', status: 'processing' },
      { progress: 0.9, stage: 'Векторизация и индексация', status: 'processing' },
    ];

    const alive = () => epoch === this.epoch && this.state.sources.some((item) => item.id === sourceId);

    for (const step of steps) {
      await delay(520);
      if (!alive()) return;
      const current = this.state.sources.find((item) => item.id === sourceId);
      if (!current) return;
      const patched: KnowledgeSource = {
        ...current,
        status: step.status,
        progress: step.progress,
        stage: step.stage,
        updated_at: this.now(),
      };
      this.state.sources = this.state.sources.map((item) =>
        item.id === sourceId ? patched : item,
      );
      this.emit({ type: 'source.updated', source: { ...patched } });
    }

    await delay(520);
    if (!alive()) return;

    const kind = input.mediaType.startsWith('image/') ? 'image' : 'pdf';
    const spec: SourceSpec = {
      id: sourceId,
      mode_id: this.state.sources.find((item) => item.id === sourceId)?.mode_id ?? '',
      title: input.title,
      filename: input.filename,
      kind,
      processing_mode: input.processing_mode,
      status: 'ready',
      ageHours: 0,
      pageCount: kind === 'image' ? 1 : 4 + Math.floor(Math.random() * 15),
      openingPages: [
        `${input.title}\n\nДокумент загружен в базу знаний режима. Текст распознан, разбит на фрагменты и проиндексирован для поиска.`,
        `Метод обработки: ${input.processing_mode === 'VISION' ? 'Vision-анализ изображения' : 'OCR-распознавание текста'}.\n\nИсходный файл: ${input.filename}.`,
      ],
      sentences: GENERIC_SENTENCES,
    };

    const content = buildContent(spec);
    const tokenCount = content.chunks.reduce((sum, chunk) => sum + chunk.tokens, 0);

    this.state.sourceContent = { ...this.state.sourceContent, [sourceId]: content };
    const current = this.state.sources.find((item) => item.id === sourceId);
    if (!current) return;
    const ready: KnowledgeSource = {
      ...current,
      status: 'ready',
      progress: 1,
      stage: null,
      error: null,
      page_count: content.pages.length,
      chunk_count: content.chunks.length,
      token_count: tokenCount,
      updated_at: this.now(),
    };
    this.state.sources = this.state.sources.map((item) => (item.id === sourceId ? ready : item));
    this.emit({ type: 'source.updated', source: { ...ready } });
  }

  /* -- devices & pairing --------------------------------------------------- */

  devices = {
    list: async (): Promise<Device[]> => {
      await delay(LATENCY.read);
      return this.state.devices.map((device) => ({ ...device }));
    },

    revoke: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      const device = this.state.devices.find((item) => item.id === id);
      if (!device) throw new WristMindError(`Устройство ${id} не найдено`, { code: 'not_found' });
      if (device.id === this.session.deviceId) {
        throw new WristMindError('Нельзя отозвать текущую панель', { code: 'conflict' });
      }
      const updated = { ...device, revoked_at: this.now() };
      this.state.devices = this.state.devices.map((item) => item.id === id ? updated : item);
      this.emit({ type: 'device.updated', device: updated });
    },
    remove: async (id: string): Promise<void> => {
      await delay(LATENCY.write);
      const device = this.state.devices.find((item) => item.id === id);
      if (!device) throw new WristMindError(`Устройство ${id} не найдено`, { code: 'not_found' });
      if (!device.revoked_at) throw new WristMindError('Сначала отзовите доступ', { code: 'conflict' });
      this.state.devices = this.state.devices.filter((item) => item.id !== id);
      this.emit({ type: 'device.removed', device_id: id });
    },
  };

  pairing = {
    list: async (): Promise<PairingCode[]> => {
      await delay(LATENCY.read);
      return this.state.pairingCodes.map((code) => ({ ...code }));
    },

    create: async (targetKind: DeviceKind | null): Promise<PairingCode> => {
      await delay(LATENCY.write);
      const code: PairingCode = {
        code: String(Math.floor(10 ** (PAIRING_CODE_LENGTH - 1) + Math.random() * 9 * 10 ** (PAIRING_CODE_LENGTH - 1))),
        target_kind: targetKind,
        created_at: this.now(),
        expires_at: new Date(Date.now() + PAIRING_CODE_TTL_MS).toISOString(),
        claimed_at: null,
      };
      this.state.pairingCodes = [code, ...this.state.pairingCodes];
      this.emit({ type: 'pairing.updated', code: { ...code } });
      return { ...code };
    },

    revoke: async (code: string): Promise<void> => {
      await delay(LATENCY.read);
      this.state.pairingCodes = this.state.pairingCodes.filter((item) => item.code !== code);
      this.emit({ type: 'pairing.removed', code });
    },
  };

  /* -- models, settings, stats, system ------------------------------------- */

  models = {
    list: async () => {
      await delay(LATENCY.read);
      return SEED_MODELS.map((model) => ({ ...model }));
    },
  };

  settings = {
    get: async (): Promise<Settings> => {
      await delay(LATENCY.read);
      return { ...this.state.settings };
    },

    update: async (patch: Partial<Settings>): Promise<Settings> => {
      await delay(LATENCY.write);
      this.state.settings = { ...this.state.settings, ...patch };
      return { ...this.state.settings };
    },
  };

  stats = {
    overview: async () => {
      const modes = this.state.modes.filter((mode) => mode.deleted_at === null);
      const sources = this.state.sources;
      return buildOverviewStats({
        modes_total: modes.length,
        modes_hidden_on_watch: modes.filter((mode) => mode.hidden_on_watch).length,
        chats_total: this.state.chats.length,
        sources_total: sources.length,
        sources_ready: sources.filter((source) => source.status === 'ready').length,
        sources_processing: sources.filter(
          (source) => source.status === 'processing' || source.status === 'uploading',
        ).length,
        sources_error: sources.filter((source) => source.status === 'error').length,
      });
    },
  };

  system = {
    health: async () => {
      await delay(LATENCY.read);
      return buildHealth(
        this.state.modes.filter((mode) => mode.deleted_at === null).length,
        this.state.sources.length,
      );
    },

    resetDemoData: async (): Promise<void> => {
      await delay(LATENCY.write);
      this.epoch += 1;
      this.state = initialState();
      // Re-publish everything so the cache reloads from a clean dataset.
      for (const mode of this.state.modes) this.emit({ type: 'mode.updated', mode: { ...mode } });
      for (const chat of this.state.chats) this.emit({ type: 'chat.updated', chat: { ...chat } });
      for (const source of this.state.sources) {
        this.emit({ type: 'source.updated', source: { ...source } });
      }
    },
  };
}

const GENERIC_SENTENCES = [
  'Раздел описывает порядок действий и требования к исполнителю.',
  'Все отклонения от регламента фиксируются в журнале изменений.',
  'Ответственный за выполнение этапа назначается до начала работ.',
  'Контрольные точки вынесены в отдельную таблицу с указанием сроков.',
  'При возникновении нештатной ситуации действие приостанавливается до выяснения причин.',
  'Документ подлежит пересмотру не реже одного раза в год.',
  'Ссылки на смежные документы приведены в конце раздела.',
  'Термины употребляются в значениях, определённых в глоссарии.',
  'Числовые параметры указаны для типовой конфигурации и могут отличаться на стендах.',
  'Перед применением убедитесь, что версия документа соответствует вашей версии системы.',
];
