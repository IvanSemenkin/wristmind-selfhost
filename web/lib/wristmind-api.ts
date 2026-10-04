export type ApiSession = {
  baseUrl: string;
  token: string;
  deviceId: string;
  isAdmin?: boolean;
};

export type ApiUser = { id: string; name: string; role: string; created_at: string; is_admin?: boolean };

export type ApiMode = {
  id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  system_prompt: string;
  response_model_id: string;
  hidden_on_watch: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type ApiKnowledgeSource = {
  id: string;
  mode_id: string;
  title: string;
  filename: string;
  media_type: string;
  processing_mode: 'OCR' | 'VISION';
  status: string;
  page_count: number;
  chunk_count: number;
  token_count: number;
  error: string | null;
  created_at: string;
};

export type ApiKnowledgeChunk = {
  id: string;
  ordinal: number;
  page_from: number | null;
  page_to: number | null;
  kind: string;
  content: string;
  token_count: number;
};

export type ApiKnowledgeSourceDetail = ApiKnowledgeSource & {
  chunks: ApiKnowledgeChunk[];
  chunk_offset: number;
  chunk_limit: number;
  has_more: boolean;
};

export type ApiChat = {
  id: string;
  mode_id: string;
  mode_name: string;
  mode_deleted: boolean;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ApiMessage = {
  id: string;
  chat_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  status: string;
  provider: string | null;
  model_id: string | null;
  usage: Record<string, unknown>;
  timings: Record<string, unknown>;
  created_at: string;
};

export type ApiJob = {
  id: string;
  kind: string;
  status: string;
  client_request_id: string;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type JobStreamEvent = {
  event: string;
  data: Record<string, unknown>;
};

export type ApiDevice = {
  id: string;
  name: string;
  kind: string;
  is_admin: boolean;
  user_id: string | null;
  created_at: string;
  last_seen_at: string;
  revoked_at: string | null;
};

export type ApiModel = { id: string; label: string; provider: string };
export type DashboardData = {
  modes: ApiMode[];
  knowledge: ApiKnowledgeSource[];
  chats: ApiChat[];
  devices: ApiDevice[];
  models: ApiModel[];
  globalPrompt: string;
  historyMessageLimit: number;
  totalAiRequests: number;
  currentUser: ApiUser;
};

export class WristMindApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export class WristMindApi {
  private readonly root: string;

  constructor(
    baseUrl: string,
    private readonly token?: string,
  ) {
    this.root = normalizeBaseUrl(baseUrl);
  }

  async health() {
    return this.request<{ status: string; version: string }>('/health');
  }

  async enrollWeb(bootstrapSecret: string): Promise<ApiSession> {
    const response = await this.request<{ device_id: string; token: string; is_admin: boolean }>(
      '/v1/devices/admin/enroll',
      {
        method: 'POST',
        headers: { 'X-WristMind-Bootstrap': bootstrapSecret },
        body: JSON.stringify({ name: 'WristMind Web', kind: 'WEB' }),
      },
    );
    return { baseUrl: this.root, token: response.token, deviceId: response.device_id, isAdmin: true };
  }

  async enrollWebWithPairingCode(code: string): Promise<ApiSession> {
    const response = await this.request<{ device_id: string; token: string; is_admin: boolean }>(
      '/v1/devices/admin/enroll-by-code',
      {
        method: 'POST',
        body: JSON.stringify({ name: 'WristMind Web', kind: 'WEB', code }),
      },
    );
    return { baseUrl: this.root, token: response.token, deviceId: response.device_id, isAdmin: response.is_admin };
  }

  async dashboard(): Promise<DashboardData> {
    const currentUser = await this.request<ApiUser>('/v1/me');
    const [modes, knowledge, chats] = await Promise.all([
      this.request<ApiMode[]>('/v1/modes'),
      this.request<ApiKnowledgeSource[]>('/v1/knowledge'),
      this.request<ApiChat[]>('/v1/chats'),
    ]);
    const adminData: [ApiDevice[], ApiModel[], { global_system_prompt: string; history_message_limit: number }, { total_ai_requests: number }] = currentUser.is_admin ? await Promise.all([
      this.request<ApiDevice[]>('/v1/devices'),
      this.request<ApiModel[]>('/v1/models'),
      this.request<{ global_system_prompt: string; history_message_limit: number }>('/v1/settings'),
      this.request<{ total_ai_requests: number }>('/v1/dashboard/stats'),
    ]) : [[], [], { global_system_prompt: '', history_message_limit: 12 }, { total_ai_requests: 0 }];
    const [devices, models, settings, stats] = adminData;
    return {
      modes,
      knowledge,
      chats,
      devices,
      models,
      globalPrompt: settings.global_system_prompt,
      historyMessageLimit: settings.history_message_limit,
      totalAiRequests: Number.isFinite(stats.total_ai_requests) ? stats.total_ai_requests : 0,
      currentUser,
    };
  }

  async deleteDevice(deviceId: string) {
    return this.request<void>(`/v1/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
  }

  async uploadKnowledge(input: {
    modeId: string;
    processingMode: 'OCR' | 'VISION';
    title: string;
    file: File;
  }) {
    const body = new FormData();
    body.set('mode_id', input.modeId);
    body.set('processing_mode', input.processingMode);
    body.set('client_request_id', crypto.randomUUID());
    body.set('title', input.title);
    body.set('file', input.file, input.file.name);
    return this.request<{ id: string; status: string }>('/v1/knowledge', { method: 'POST', body });
  }

  async deleteKnowledge(sourceId: string) {
    await this.request<void>(`/v1/knowledge/${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
  }

  async knowledgeSource(sourceId: string, chunkOffset = 0) {
    const query = new URLSearchParams({ chunk_offset: `${chunkOffset}`, chunk_limit: '50' });
    return this.request<ApiKnowledgeSourceDetail>(
      `/v1/knowledge/${encodeURIComponent(sourceId)}?${query}`,
    );
  }

  async reprocessKnowledge(sourceId: string) {
    return this.request<{ id: string; status: string }>(
      `/v1/knowledge/${encodeURIComponent(sourceId)}/reprocess`,
      {
        method: 'POST',
        body: JSON.stringify({ client_request_id: crypto.randomUUID() }),
      },
    );
  }

  async createMode(input: {
    name: string;
    description?: string;
    color: string;
    systemPrompt: string;
    modelId: string;
  }) {
    return this.request<ApiMode>('/v1/modes', {
      method: 'POST',
      body: JSON.stringify({
        name: input.name,
        description: input.description ?? '',
        color: input.color,
        icon: 'spark',
        system_prompt: input.systemPrompt,
        response_model_id: input.modelId,
      }),
    });
  }

  async updateMode(modeId: string, input: {
    name: string;
    description: string;
    color: string;
    systemPrompt: string;
    modelId: string;
  }) {
    return this.request<ApiMode>(`/v1/modes/${encodeURIComponent(modeId)}`, {
      method: 'PATCH',
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        color: input.color,
        system_prompt: input.systemPrompt,
        response_model_id: input.modelId,
      }),
    });
  }

  async setModeHiddenOnWatch(modeId: string, hidden: boolean) {
    return this.request<ApiMode>(`/v1/modes/${encodeURIComponent(modeId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ hidden_on_watch: hidden }),
    });
  }

  async deleteMode(modeId: string) {
    await this.request<void>(`/v1/modes/${encodeURIComponent(modeId)}`, { method: 'DELETE' });
  }

  async createChat(modeId: string, title = 'Новый чат') {
    return this.request<ApiChat>('/v1/chats', {
      method: 'POST',
      body: JSON.stringify({ mode_id: modeId, title }),
    });
  }

  async createQuickChat() {
    return this.request<ApiChat>('/v1/chats/quick', { method: 'POST' });
  }

  async messages(chatId: string) {
    return this.request<ApiMessage[]>(`/v1/chats/${encodeURIComponent(chatId)}/messages`);
  }

  async sendMessage(chatId: string, text: string) {
    return this.request<ApiJob>(`/v1/chats/${encodeURIComponent(chatId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ client_request_id: crypto.randomUUID(), text }),
    });
  }

  async streamJob(
    jobId: string,
    onEvent: (event: JobStreamEvent) => void,
    signal?: AbortSignal,
  ) {
    const headers = new Headers({
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
    });
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);

    let response: Response;
    try {
      response = await fetch(`${this.root}/v1/jobs/${encodeURIComponent(jobId)}/events`, {
        headers,
        signal,
        cache: 'no-store',
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      throw new WristMindApiError('Поток ответа прерван. Проверьте соединение с сервером.', 0);
    }
    if (!response.ok || !response.body) {
      throw new WristMindApiError(`Не удалось открыть поток ответа (${response.status})`, response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const emitBlock = (block: string) => {
      let eventName = 'message';
      const dataLines: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) return;
      const raw = dataLines.join('\n');
      let data: Record<string, unknown> = { value: raw };
      try { data = JSON.parse(raw) as Record<string, unknown>; } catch { /* plain SSE payload */ }
      onEvent({ event: eventName, data });
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        emitBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
      if (done) break;
    }
    if (buffer.trim()) emitBlock(buffer);
  }

  async deleteChat(chatId: string) {
    await this.request<void>(`/v1/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' });
  }

  async updateGlobalPrompt(prompt: string) {
    return this.updateSettings({ global_system_prompt: prompt });
  }

  async updateSettings(input: { global_system_prompt?: string; history_message_limit?: number }) {
    return this.request<{ global_system_prompt: string; history_message_limit: number }>('/v1/settings', {
      method: 'PUT',
      body: JSON.stringify(input),
    });
  }

  async createPairingCode() {
    return this.request<{ code: string; expires_at: string }>('/v1/devices/pairing-codes', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (!(init.body instanceof FormData) && init.body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);

    const isSafeRead = !init.method || init.method.toUpperCase() === 'GET';
    let response: Response | null = null;
    for (let attempt = 0; attempt < (isSafeRead ? 2 : 1); attempt += 1) {
      try {
        response = await fetch(`${this.root}${path}`, {
          ...init,
          headers,
          cache: isSafeRead ? 'no-store' : init.cache,
        });
        break;
      } catch {
        if (attempt === 0 && isSafeRead) {
          await new Promise((resolve) => window.setTimeout(resolve, 500));
          continue;
        }
      }
    }
    if (!response) throw new WristMindApiError('Сервер недоступен. Проверьте адрес, сеть и HTTPS.', 0);
    const contentType = response.headers.get('content-type') ?? '';
    if (!response.ok) {
      const payload = contentType.includes('application/json')
        ? await response.json().catch(() => null) as { detail?: string } | null
        : null;
      throw new WristMindApiError(payload?.detail || `Ошибка сервера ${response.status}`, response.status);
    }
    if (response.status === 204) return undefined as T;
    if (!contentType.includes('application/json')) {
      throw new WristMindApiError(
        'По этому адресу отвечает не API WristMind. Проверьте адрес сервера или его reverse proxy.',
        502,
      );
    }
    return response.json() as Promise<T>;
  }
}

export function normalizeBaseUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(trimmed)) {
    throw new WristMindApiError('Адрес должен начинаться с http:// или https://', 0);
  }
  return trimmed;
}
