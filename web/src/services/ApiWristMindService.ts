import type { Session } from '@/session';
import { WristMindError } from './errors';
import { dedupeWebSources, domainFromUrl, extractLegacySources } from '@/lib/webSources';
import { normalizeChatSources } from '@/lib/chatSources';
import type {
  BootstrapResult,
  WristMindEvent,
  WristMindEventListener,
  WristMindService,
} from './types';
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
  MessageSource,
  MessageLocalContext,
  MessageTimings,
  MessageWebSource,
  Mode,
  ModeCreateInput,
  ModeUpdateInput,
  Model,
  OverviewStats,
  PairingCode,
  SendMessageInput,
  Settings,
  SourceContent,
  SourceChunk,
  SourceUploadInput,
  SourceUploadResult,
  SystemHealth,
} from '@/types';

type ApiMode = Omit<Mode, 'color' | 'icon'> & { color: string; icon: string };
type ApiJob = { id: string; status: string; result: Record<string, unknown>; error: string | null };
type ApiMessage = Omit<Message, 'status' | 'usage' | 'timings' | 'sources' | 'phases'> & {
  status: string;
  usage: Record<string, unknown>;
  timings: Record<string, unknown>;
};
function mapSettings(value: any): Settings {
  return {
    developer_mode: value.developer_mode ?? false,
    global_system_prompt: value.global_system_prompt ?? '',
    source_intent_prompt: value.source_intent_prompt ?? '',
    source_candidate_prompt: value.source_candidate_prompt ?? '',
    history_limit: value.history_message_limit ?? 12,
    default_model_id: value.default_model_id ?? '',
    stream_responses: value.stream_responses ?? true,
    retention_days: value.retention_days ?? 90,
  };
}

const MODE_COLORS: Record<string, Mode['color']> = {
  '#65F5C2': 'teal',
  '#3D8BFD': 'blue',
  '#56A8F5': 'cyan',
  '#34C98A': 'emerald',
  '#E0A33C': 'amber',
  '#EC5F5F': 'rose',
};

function modeColor(value: string): Mode['color'] {
  const direct = MODE_COLORS[value.toUpperCase()];
  if (direct) return direct;
  const match = value.match(/^#([0-9a-f]{6})$/i);
  if (!match) return 'blue';
  const rgb = Number.parseInt(match[1], 16);
  const r = (rgb >> 16) & 255;
  const g = (rgb >> 8) & 255;
  const b = rgb & 255;
  if (g > r * 1.25 && g > b * 1.1) return 'emerald';
  if (b > r * 1.25) return 'blue';
  if (r > b * 1.25 && g > b * 1.1) return 'amber';
  return 'violet';
}

function modeHex(value: Mode['color']): string {
  const colors: Record<Mode['color'], string> = {
    blue: '#3D8BFD', cyan: '#56A8F5', teal: '#65F5C2', emerald: '#34C98A',
    lime: '#9CCC65', amber: '#E0A33C', orange: '#F08A4B', rose: '#EC5F5F',
    pink: '#E878A8', violet: '#9A7BFF',
  };
  return colors[value];
}

function phase(value: string): MessagePhase | null {
  return ['queued', 'context', 'search_query', 'searching', 'reviewing_sources', 'opening_source', 'generating', 'research_drafting', 'research_checking', 'research_refining'].includes(value)
    ? value as MessagePhase
    : null;
}

function apiError(status: number, detail: string): WristMindError {
  const code = status === 401 ? 'unauthorized' : status === 404 ? 'not_found' : status === 409 ? 'conflict' : status === 422 ? 'invalid' : 'server';
  return new WristMindError(detail, { code, status });
}

/**
 * Normalise structured web sources, skipping malformed entries (no URL) and
 * filling in a safe display title. Presentation shaping only.
 */
function mapWebSources(value: unknown): MessageWebSource[] {
  if (!Array.isArray(value)) return [];
  const mapped: MessageWebSource[] = [];
  value.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return;
    const record = raw as Record<string, unknown>;
    const url = typeof record.url === 'string' ? record.url.trim() : '';
    if (!url) return;
    const title =
      typeof record.title === 'string' && record.title.trim()
        ? record.title.trim()
        : domainFromUrl(url) || url;
    const retrieved = typeof record.retrieved_at === 'string' ? record.retrieved_at : undefined;
    mapped.push({
      id: typeof record.id === 'string' && record.id ? record.id : `web-${index}-${url}`,
      title,
      url,
      ...(retrieved ? { retrieved_at: retrieved } : {}),
    });
  });
  return dedupeWebSources(mapped);
}

/** Keep only the local-context fields the console understands, tolerantly. */
function mapLocalContext(value: unknown): MessageLocalContext | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  return {
    ...record,
    working_sources: typeof record.working_sources === 'number' ? record.working_sources : null,
    working_titles: Array.isArray(record.working_titles)
      ? record.working_titles.filter((title): title is string => typeof title === 'string')
      : [],
  };
}

const LEGACY_PAGE_MARKER = /^##\s*Страница\s+(\d+)\s*$/gmi;

/**
 * Early OCR imports stored one continuous document, with page headings mixed
 * into retrieval chunks. Reconstruct their reading pages for the viewer until
 * the source is reprocessed; current imports have page ranges from the API.
 */
function splitLegacyPdfPages(chunks: SourceChunk[], pageCount: number) {
  if (!pageCount) return null;
  const text = chunks.map((chunk) => chunk.text).join('\n\n');
  const markers = [...text.matchAll(LEGACY_PAGE_MARKER)].map((match) => ({
    page: Number(match[1]),
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
  }));
  if (markers.length < pageCount || new Set(markers.map((marker) => marker.page)).size !== pageCount) return null;
  if (!Array.from({ length: pageCount }, (_, index) => index + 1).every((page) => markers.some((marker) => marker.page === page))) return null;

  const displayChunks: SourceChunk[] = [];
  const pages = markers.map((marker, index) => {
    const next = markers[index + 1];
    const pageText = text.slice(marker.end, next?.start).trim();
    displayChunks.push({
      id: `legacy-page-${marker.page}`,
      index,
      page: marker.page - 1,
      text: pageText,
      tokens: Math.max(1, Math.ceil(pageText.length / 4)),
    });
    return { index: marker.page - 1, text: pageText, chars: pageText.length };
  });
  return { pages, chunks: displayChunks };
}

export class ApiWristMindService implements WristMindService {
  private readonly listeners = new Set<WristMindEventListener>();
  private localPairingCodes: PairingCode[] = [];
  private pendingPairingRequest: { id: string; createdAt: number } | null = null;
  private pairingCreatePromise: Promise<PairingCode> | null = null;

  constructor(private readonly session: Session, private readonly onInvalidToken?: () => void) {}

  subscribe = (listener: WristMindEventListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private emit(event: WristMindEvent): void {
    for (const listener of this.listeners) listener(event);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.session.token) headers.set('Authorization', `Bearer ${this.session.token}`);
    if (!(init.body instanceof FormData) && init.body !== undefined) headers.set('Content-Type', 'application/json');
    let response: Response;
    try {
      response = await fetch(`${this.session.baseUrl.replace(/\/+$/, '')}${path}`, { ...init, headers, cache: 'no-store' });
    } catch {
      throw new WristMindError('Сервер недоступен. Проверьте адрес и соединение.', { code: 'network', status: 0 });
    }
    const contentType = response.headers.get('content-type') ?? '';
    if (!response.ok) {
      const payload = contentType.includes('json') ? await response.json().catch(() => null) as { detail?: string } | null : null;
      if (response.status === 401 && payload?.detail === 'Invalid device token') this.onInvalidToken?.();
      throw apiError(response.status, payload?.detail ?? `Ошибка сервера ${response.status}`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  private mapMode(value: ApiMode): Mode {
    return { ...value, color: modeColor(value.color), icon: value.icon || null, deleted_at: value.deleted_at ?? null };
  }

  private mapChat(value: any): Chat {
    return { ...value, mode_id: value.mode_id ?? null, mode_name: value.mode_name ?? null, deleted_at: value.deleted_at ?? null, pinned: false };
  }

  /**
   * Keep the whole diagnostics object. Only the two headline timings are
   * normalised to `number | null`; every other key is preserved verbatim so
   * the console can render whatever the backend records, old or new.
   */
  private mapTimings(value: Record<string, unknown> | null | undefined): MessageTimings | null {
    if (!value || typeof value !== 'object') return null;
    return {
      ...value,
      total_ms: typeof value.total_ms === 'number' ? value.total_ms : null,
      first_token_ms: typeof value.first_token_ms === 'number' ? value.first_token_ms : null,
      local_context: mapLocalContext(value.local_context),
    };
  }

  private mapMessage(value: ApiMessage): Message {
    const current = phase(value.status);
    // The backend still appends a legacy Markdown source list to the answer
    // text. Strip it while mapping so it can never render as ordinary prose,
    // and keep its links as a fallback for messages without structured data.
    const legacy = extractLegacySources(typeof value.content === 'string' ? value.content : '');
    const rawSources = Array.isArray((value as any).sources) ? (value as any).sources : [];
    // Public-web references carry a `url`; knowledge-base citations carry a
    // `source_id`/`chunk_index`. Keep them apart so each renders honestly.
    const citations: MessageSource[] = [];
    const structured: MessageWebSource[] = [];
    for (const item of rawSources) {
      if (item && typeof item === 'object' && typeof item.url === 'string' && item.url.length > 0) {
        structured.push(item as MessageWebSource);
      } else {
        citations.push(item as MessageSource);
      }
    }
    const wireSources = mapWebSources(structured);
    return {
      ...value,
      content: legacy.content,
      web_sources: wireSources.length > 0 ? wireSources : legacy.sources,
      status: current ?? (value.status === 'failed' ? 'error' : value.status === 'streaming' ? 'generating' : 'complete'),
      usage: {
        prompt_tokens: typeof value.usage?.prompt_tokens === 'number' ? value.usage.prompt_tokens : null,
        completion_tokens: typeof value.usage?.completion_tokens === 'number' ? value.usage.completion_tokens : null,
        total_tokens: typeof value.usage?.total_tokens === 'number' ? value.usage.total_tokens : null,
      },
      timings: this.mapTimings(value.timings),
      sources: citations,
      phases: Array.isArray((value as any).phases) ? (value as any).phases : current ? [current] : [],
    };
  }

  async bootstrap(): Promise<BootstrapResult> {
    const [modes, chats, sources, devices, models, settings, stats, health] = await Promise.all([
      this.modes.list(), this.chats.list(), this.knowledge.list(), this.devices.list(),
      this.models.list(), this.settings.get(), this.stats.overview(), this.system.health(),
    ]);
    return { modes, chats, sources, devices, pairingCodes: await this.pairing.list(), models, settings, stats, health };
  }

  modes = {
    list: async (): Promise<Mode[]> => (await this.request<ApiMode[]>('/v1/modes')).map((item) => this.mapMode(item)),
    get: async (id: string): Promise<Mode> => this.mapMode(await this.request<ApiMode>(`/v1/modes/${encodeURIComponent(id)}`)),
    create: async (input: ModeCreateInput): Promise<Mode> => this.mapMode(await this.request<ApiMode>('/v1/modes', { method: 'POST', body: JSON.stringify({ ...input, color: modeHex(input.color) }) })),
    update: async (id: string, input: ModeUpdateInput): Promise<Mode> => this.mapMode(await this.request<ApiMode>(`/v1/modes/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ ...input, ...(input.color ? { color: modeHex(input.color) } : {}) }) })),
    remove: async (id: string): Promise<void> => { await this.request<void>(`/v1/modes/${encodeURIComponent(id)}`, { method: 'DELETE' }); },
  };

  chats = {
    list: async (): Promise<Chat[]> => (await this.request<any[]>('/v1/chats')).map((item) => this.mapChat(item)),
    get: async (id: string): Promise<Chat> => (await this.chats.list()).find((item) => item.id === id) ?? (() => { throw new WristMindError('Чат не найден', { code: 'not_found', status: 404 }); })(),
    create: async (input: { mode_id: string | null; title?: string }): Promise<Chat> => {
      const value = input.mode_id
        ? await this.request<any>('/v1/chats', { method: 'POST', body: JSON.stringify({ mode_id: input.mode_id, title: input.title ?? 'Новый чат', client_request_id: crypto.randomUUID() }) })
        : await this.request<any>('/v1/chats/quick', { method: 'POST', body: JSON.stringify({ client_request_id: crypto.randomUUID() }) });
      return this.mapChat(value);
    },
    update: async (id: string, input: { title?: string; pinned?: boolean }): Promise<Chat> => {
      const value = await this.request<any>(`/v1/chats/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ title: input.title ?? 'Новый чат' }) });
      return this.mapChat(value);
    },
    remove: async (id: string): Promise<void> => { await this.request<void>(`/v1/chats/${encodeURIComponent(id)}`, { method: 'DELETE' }); },
    messages: async (chatId: string): Promise<Message[]> => (await this.request<ApiMessage[]>(`/v1/chats/${encodeURIComponent(chatId)}/messages`)).map((item) => this.mapMessage(item)),
    sources: async (chatId: string): Promise<ChatSources> =>
      normalizeChatSources(
        await this.request<unknown>(`/v1/chats/${encodeURIComponent(chatId)}/sources`),
      ),
    workingSourceText: async (chatId: string, sourceId: string): Promise<ChatWorkingSourceText> =>
      this.request<ChatWorkingSourceText>(
        `/v1/chats/${encodeURIComponent(chatId)}/sources/${encodeURIComponent(sourceId)}/text`,
      ),
    send: async (input: SendMessageInput, handlers?: ChatStreamHandlers): Promise<Message> => this.sendMessage(input, handlers),
  };

  private async sendMessage(input: SendMessageInput, handlers?: ChatStreamHandlers): Promise<Message> {
    const job = await this.request<ApiJob>(`/v1/chats/${encodeURIComponent(input.chat_id)}/messages`, {
      method: 'POST',
      headers: { 'X-WristMind-Client-Sent-Ms': `${Date.now()}` },
      body: JSON.stringify({
        client_request_id: input.client_message_id ?? crypto.randomUUID(),
        text: input.content,
        // RESEARCH is the only mode the console sends; the explicit web flags
        // remain in the contract but are no longer a user-facing choice.
        research_mode: input.research_mode === true,
        web_search: input.web_search === true,
        web_research: input.web_research === true,
      }),
    });
    let streamed = '';
    const response = await fetch(`${this.session.baseUrl.replace(/\/+$/, '')}/v1/jobs/${encodeURIComponent(job.id)}/events`, { headers: { Authorization: `Bearer ${this.session.token}`, Accept: 'text/event-stream' } });
    if (!response.ok || !response.body) throw apiError(response.status, 'Не удалось открыть поток ответа');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const consume = (block: string) => {
      let event = 'message';
      const data: string[] = [];
      for (const line of block.split('\n')) { if (line.startsWith('event:')) event = line.slice(6).trim(); if (line.startsWith('data:')) data.push(line.slice(5).trimStart()); }
      if (!data.length) return;
      let payload: any = {}; try { payload = JSON.parse(data.join('\n')); } catch { payload = { value: data.join('\n') }; }
      if (event === 'state') { const current = phase(payload.state); if (current) handlers?.onPhase?.('', current); }
      if (event === 'delta' && typeof payload.text === 'string') { streamed += payload.text; handlers?.onDelta?.('', payload.text); }
      if (event === 'error') handlers?.onError?.('', payload.detail ?? 'Не удалось сформировать ответ');
    };
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) { consume(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); boundary = buffer.indexOf('\n\n'); }
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    const messages = await this.chats.messages(input.chat_id);
    const final = [...messages].reverse().find((item) => item.role === 'assistant' && item.status !== 'generating') ?? {
      id: `local-${job.id}`, chat_id: input.chat_id, role: 'assistant' as const, content: streamed, status: 'complete' as const, provider: null, model_id: null, usage: null, timings: null, sources: [], phases: [], created_at: new Date().toISOString(),
    };
    handlers?.onFinal?.(final);
    return final;
  }

  knowledge = {
    list: async (modeId?: string): Promise<KnowledgeSource[]> => {
      const query = modeId ? `?mode_id=${encodeURIComponent(modeId)}` : '';
      return (await this.request<any[]>(`/v1/knowledge${query}`)).map((item) => this.mapSource(item));
    },
    get: async (id: string): Promise<KnowledgeSource> => this.mapSource(await this.request<any>(`/v1/knowledge/${encodeURIComponent(id)}`)),
    content: async (id: string): Promise<SourceContent> => {
      const value = await this.request<any>(`/v1/knowledge/${encodeURIComponent(id)}?chunk_offset=0&chunk_limit=100`);
      const chunks = (value.chunks ?? []).map((chunk: any) => ({
        id: chunk.id,
        index: chunk.ordinal,
        page: Math.max(0, (chunk.page_from ?? 1) - 1),
        text: chunk.content,
        tokens: chunk.token_count,
      }));
      const legacyPages = splitLegacyPdfPages(chunks, value.page_count ?? 0);
      if (legacyPages) return { source_id: id, ...legacyPages };
      const grouped = new Map<number, string[]>();
      for (const chunk of chunks) {
        grouped.set(chunk.page, [...(grouped.get(chunk.page) ?? []), chunk.text]);
      }
      const pageCount = Math.max(value.page_count ?? 0, ...chunks.map((chunk: any) => chunk.page + 1), 0);
      const pages = Array.from({ length: pageCount }, (_, index) => {
        const text = (grouped.get(index) ?? []).join('\n\n');
        return { index, text, chars: text.length };
      });
      return { source_id: id, pages, chunks };
    },
    upload: async (input: SourceUploadInput): Promise<SourceUploadResult> => {
      const body = new FormData(); body.set('mode_id', input.mode_id); body.set('processing_mode', input.processing_mode); body.set('client_request_id', crypto.randomUUID()); body.set('title', input.title); body.set('file', input.file as File, input.file.name);
      const job = await this.request<ApiJob>('/v1/knowledge', { method: 'POST', body });
      const sources = await this.knowledge.list(input.mode_id);
      const source = [...sources].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))[0];
      if (!source) throw new WristMindError('Источник не найден после загрузки', { code: 'server' });
      void this.pollSource(source.id, input.mode_id);
      return { source, job_id: job.id };
    },
    reprocess: async (id: string): Promise<void> => {
      const job = await this.request<ApiJob>(`/v1/knowledge/${encodeURIComponent(id)}/reprocess`, { method: 'POST', body: JSON.stringify({ client_request_id: crypto.randomUUID() }) });
      void this.pollSource(id, undefined, job.id);
    },
    remove: async (id: string): Promise<void> => { await this.request<void>(`/v1/knowledge/${encodeURIComponent(id)}`, { method: 'DELETE' }); },
  };

  private mapSource(value: any): KnowledgeSource {
    return { ...value, status: value.status === 'failed' ? 'error' : value.status === 'queued' ? 'uploading' : value.status, updated_at: value.created_at };
  }

  private async pollSource(sourceId: string, modeId?: string, _jobId?: string): Promise<void> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        const source = this.mapSource(await this.request<any>(`/v1/knowledge/${encodeURIComponent(sourceId)}`));
        this.emit({ type: 'source.updated', source });
        if (source.status === 'ready' || source.status === 'error') return;
      } catch { return; }
      void modeId;
    }
  }

  private async issuePairingCode(targetKind: DeviceKind | null): Promise<PairingCode> {
    const now = Date.now();
    const pending = this.pendingPairingRequest && now - this.pendingPairingRequest.createdAt < 10 * 60_000
      ? this.pendingPairingRequest
      : { id: crypto.randomUUID(), createdAt: now };
    this.pendingPairingRequest = pending;
    let lastError: unknown;

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 12_000);
      try {
        const value = await this.request<{ code: string; expires_at: string }>('/v1/devices/pairing-codes', {
          method: 'POST',
          body: JSON.stringify({ client_request_id: pending.id }),
          signal: controller.signal,
        });
        const code: PairingCode = {
          code: value.code,
          target_kind: targetKind,
          created_at: new Date().toISOString(),
          expires_at: value.expires_at,
          claimed_at: null,
        };
        this.localPairingCodes = [code, ...this.localPairingCodes.filter((item) => item.code !== code.code)];
        this.pendingPairingRequest = null;
        return code;
      } catch (error) {
        lastError = error;
        if (!(error instanceof WristMindError) || error.code !== 'network' || attempt === 2) throw error;
        await new Promise((resolve) => window.setTimeout(resolve, 600 * 2 ** attempt));
      } finally {
        window.clearTimeout(timeout);
      }
    }
    throw lastError;
  }

  devices = {
    list: async (): Promise<Device[]> => this.request<Device[]>('/v1/devices'),
    revoke: async (id: string): Promise<void> => { await this.request<void>(`/v1/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }); },
    remove: async (id: string): Promise<void> => { await this.request<void>(`/v1/devices/${encodeURIComponent(id)}/record`, { method: 'DELETE' }); },
  };

  pairing = {
    list: async (): Promise<PairingCode[]> => [...this.localPairingCodes],
    create: async (targetKind: DeviceKind | null): Promise<PairingCode> => {
      if (this.pairingCreatePromise) return this.pairingCreatePromise;
      this.pairingCreatePromise = this.issuePairingCode(targetKind).finally(() => {
        this.pairingCreatePromise = null;
      });
      return this.pairingCreatePromise;
    },
    revoke: async (code: string): Promise<void> => { this.localPairingCodes = this.localPairingCodes.filter((item) => item.code !== code); },
  };

  models = {
    list: async (): Promise<Model[]> => (await this.request<any[]>('/v1/models')).map((item) => ({ id: item.id, name: item.label, provider: item.provider, context_window: 0, description: '', capabilities: [] })),
  };

  settings = {
    get: async (): Promise<Settings> => {
      const value = await this.request<any>('/v1/settings');
      return mapSettings(value);
    },
    update: async (patch: Partial<Settings>): Promise<Settings> => {
      const value = await this.request<any>('/v1/settings', {
        method: 'PUT',
        body: JSON.stringify({
          developer_mode: patch.developer_mode,
          global_system_prompt: patch.global_system_prompt,
          source_intent_prompt: patch.source_intent_prompt,
          source_candidate_prompt: patch.source_candidate_prompt,
          history_message_limit: patch.history_limit,
          default_model_id: patch.default_model_id,
          stream_responses: patch.stream_responses,
          retention_days: patch.retention_days,
        }),
      });
      return mapSettings(value);
    },
  };

  stats = {
    overview: async (): Promise<OverviewStats> => {
      const utcOffsetMinutes = -new Date().getTimezoneOffset();
      const value = await this.request<any>(`/v1/dashboard/stats?utc_offset_minutes=${utcOffsetMinutes}`);
      const count = (input: unknown) =>
        typeof input === 'number' && Number.isFinite(input) && input >= 0 ? input : 0;
      return {
        total_ai_requests: count(value.total_ai_requests),
        modes_total: 0,
        modes_hidden_on_watch: 0,
        chats_total: 0,
        sources_total: 0,
        sources_ready: 0,
        sources_processing: 0,
        sources_error: 0,
        requests_today: count(value.requests_today),
        requests_yesterday: count(value.requests_yesterday),
        error_rate_today: count(value.error_rate_today),
        activity: Array.isArray(value.activity)
          ? value.activity
              .filter((point: any) => point && typeof point.bucket === 'string' && Number.isFinite(Date.parse(point.bucket)))
              .map((point: any) => ({
                bucket: point.bucket as string,
                requests: count(point.requests),
                errors: count(point.errors),
              }))
          : [],
        usage: Array.isArray(value.usage)
          ? value.usage
              .filter((entry: any) => entry && typeof entry.mode_id === 'string')
              .map((entry: any) => ({
                mode_id: entry.mode_id as string,
                requests: count(entry.requests),
                tokens: count(entry.tokens),
              }))
          : [],
      };
    },
  };

  system = {
    health: async (): Promise<SystemHealth> => {
      // The API is one path with two possible carriers: the local backend, and
      // the external VPS fallback that answers only when the local backend is
      // unreachable. This mirrors how the watch decides its green/yellow status,
      // so the console and the watch never disagree about the current mode.
      const local = await this.probeLocalBackend();
      if (local.ok) {
        return {
          services: [
            {
              id: 'api',
              label: 'API шлюз',
              status: 'operational',
              detail: 'Отвечает основной сервер',
              latency_ms: local.latency_ms,
              last_seen_at: new Date().toISOString(),
            },
          ],
          api_path: 'local',
          version: local.version,
          generated_at: new Date().toISOString(),
        };
      }

      const fallback = await this.probeFallback();
      return {
        services: [
          {
            id: 'api',
            label: 'API шлюз',
            status: fallback.ready ? 'degraded' : 'down',
            detail: fallback.ready
              ? 'Отвечает резервный сервер'
              : 'Не отвечают ни основной, ни резервный сервер',
            latency_ms: fallback.latency_ms,
            last_seen_at: new Date().toISOString(),
          },
        ],
        api_path: fallback.ready ? 'fallback' : 'none',
        version: null,
        generated_at: new Date().toISOString(),
      };
    },
    resetDemoData: async (): Promise<void> => { throw new WristMindError('Сброс демонстрационных данных недоступен для production API', { code: 'invalid' }); },
  };

  /** Reachability and latency of the local backend behind the public origin. */
  private async probeLocalBackend(): Promise<{
    ok: boolean;
    latency_ms: number | null;
    version: string | null;
  }> {
    const started = performance.now();
    try {
      const value = await this.request<any>('/health');
      return {
        ok: value?.status === 'ok',
        latency_ms: Math.round(performance.now() - started),
        version: value?.version ?? null,
      };
    } catch {
      return { ok: false, latency_ms: null, version: null };
    }
  }

  /**
   * Probe the external fallback service. It answers on the same public origin
   * as the panel, and it is the path a watch uses when the local backend cannot
   * be reached at all.
   */
  private async probeFallback(): Promise<{
    ready: boolean;
    latency_ms: number | null;
  }> {
    const started = performance.now();
    try {
      const response = await fetch('/fallback/health', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      const latency = Math.round(performance.now() - started);
      if (!response.ok) return { ready: false, latency_ms: latency };
      const body = await response.json().catch(() => ({}));
      return { ready: body?.status === 'ok', latency_ms: latency };
    } catch {
      return { ready: false, latency_ms: null };
    }
  }
}

export function createApiService(session: Session, onInvalidToken?: () => void): WristMindService {
  return new ApiWristMindService(session, onInvalidToken);
}

export async function enrollWebSession(baseUrl: string, method: 'code' | 'secret', credential: string): Promise<Session> {
  const root = baseUrl.trim().replace(/\/+$/, '');
  const response = await fetch(`${root}${method === 'code' ? '/v1/devices/admin/enroll-by-code' : '/v1/devices/admin/enroll'}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(method === 'secret' ? { 'X-WristMind-Bootstrap': credential } : {}),
    },
    body: JSON.stringify(method === 'code' ? { name: 'WristMind Web', kind: 'WEB', code: credential } : { name: 'WristMind Web', kind: 'WEB' }),
  });
  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('json') ? await response.json().catch(() => null) as any : null;
  if (!response.ok) throw apiError(response.status, payload?.detail ?? `Ошибка подключения (${response.status})`);
  return { baseUrl: root, token: payload.token, deviceId: payload.device_id, isAdmin: true };
}
