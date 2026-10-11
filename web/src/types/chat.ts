import type { DeletedAt, IsoDateTime } from './common';

/* =============================================================================
   Chat & Message
   ========================================================================== */

export interface Chat {
  id: string;
  /** `null` for a Quick Chat, which is not bound to any mode. */
  mode_id: string | null;
  /** Denormalised by the backend so lists render without joining modes. */
  mode_name: string | null;
  /** True when the owning mode was deleted; the chat history is preserved. */
  mode_deleted: boolean;
  title: string;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  deleted_at: DeletedAt;
  /**
   * Console-side flag: pinned chats sort to the top. The backend may or may not
   * persist it; the UI treats the value as authoritative for the session.
   */
  pinned?: boolean;
}

export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * Generation states emitted by the backend while an answer is produced.
 * The console renders these as the processing timeline.
 */
export const MESSAGE_PHASES = [
  'queued',
  'context',
  'search_query',
  'searching',
  'reviewing_sources',
  'opening_source',
  'generating',
  'research_drafting',
  'research_checking',
  'research_refining',
] as const;

export type MessagePhase = (typeof MESSAGE_PHASES)[number];

/**
 * Lifecycle status of a message. While an answer is in flight the status is
 * itself the current phase, which is exactly what the stream reports.
 */
export type MessageStatus = MessagePhase | 'complete' | 'error' | 'cancelled';

export function isMessagePhase(status: MessageStatus): status is MessagePhase {
  return (MESSAGE_PHASES as readonly string[]).includes(status);
}

/**
 * Phases a request is expected to go through, given the mode it is sent with.
 * The client uses this to render the timeline immediately; the stream then
 * confirms each phase as it actually happens.
 *
 * There are only two modes: AUTO, where the backend Router decides on its own
 * whether the web is needed, and RESEARCH, which adds deeper checking. The
 * console therefore never pre-renders search phases just because a button was
 * pressed — the Router, not the user, chooses retrieval.
 */
export function expectedPipeline(options: { research_mode?: boolean }): MessagePhase[] {
  if (options.research_mode) {
    return ['queued', 'context', 'research_drafting', 'research_checking', 'research_refining'];
  }
  return ['queued', 'context', 'generating'];
}

/** Human labels for each phase, kept next to the contract they describe. */
export const MESSAGE_PHASE_LABELS: Record<MessagePhase, { label: string; description: string }> = {
  queued: {
    label: 'Запрос принят',
    description: 'Сообщение получено и поставлено в очередь обработки.',
  },
  context: {
    label: 'Подготовка контекста',
    description: 'Собираем системный промпт и последние сообщения диалога.',
  },
  search_query: {
    label: 'Уточнение поискового запроса',
    description: 'Переформулируем вопрос для поиска по базе знаний.',
  },
  searching: {
    label: 'Поиск источников',
    description: 'Ищем релевантные фрагменты в базе знаний режима.',
  },
  reviewing_sources: {
    label: 'Проверка источников',
    description: 'Отсеиваем слабые совпадения и проверяем актуальность.',
  },
  opening_source: {
    label: 'Чтение источника',
    description: 'Загружаем полный контекст найденных страниц.',
  },
  generating: {
    label: 'Формирование ответа',
    description: 'Модель составляет ответ и расставляет ссылки на источники.',
  },
  research_drafting: {
    label: 'Подготовка решения',
    description: 'Готовим полный ответ с учётом доступных материалов.',
  },
  research_checking: {
    label: 'Проверка ответа',
    description: 'Проверяем факты и требования задачи.',
  },
  research_refining: {
    label: 'Улучшение ответа',
    description: 'Уточняем ответ по результатам проверки.',
  },
};

/** A retrieved fragment that backs part of an answer. */
export interface MessageSource {
  id: string;
  source_id: string;
  source_title: string;
  chunk_index: number;
  page: number;
  snippet: string;
  /** 0…1 relevance reported by the retrieval pipeline. */
  relevance: number;
}

/**
 * A public-web page referenced by an answer. This is an audit record, not RAG
 * content, so it is kept apart from {@link MessageSource}. On the wire it
 * arrives inside the message's `sources` array; the mapper separates the two
 * shapes by presence of `url`.
 */
export interface MessageWebSource {
  /** Always present once mapped: malformed records are dropped. */
  id: string;
  title: string;
  url: string;
  retrieved_at?: string;
  /** Optional extras the backend may add later; never required. */
  snippet?: string | null;
  summary?: string | null;
  [key: string]: unknown;
}

export type RetrievalRoute = 'none' | 'chat_sources' | 'web' | 'deep_web';
export type ReasoningLevel = 'low' | 'medium' | 'high';
export type RetrievalTaskType =
  | 'definition'
  | 'current_fact'
  | 'write_from_source'
  | 'comparison'
  | 'calculation'
  | 'other';
export type RouterSource = 'model' | 'retry' | 'fallback';
export type RequestAnchorMode = 'model' | 'deterministic';

/** Which pipeline the router picked for this answer. */
export interface MessageRoute {
  retrieval?: RetrievalRoute;
  reasoning?: ReasoningLevel;
  verification?: boolean;
  freshness_required?: boolean;
  task_type?: RetrievalTaskType;
  [key: string]: unknown;
}

/** Normalised restatement of the request. Never contains hidden prompts. */
export interface MessageRequestAnchor {
  mode?: RequestAnchorMode;
  subject?: string;
  task?: string;
  constraints?: string[];
  unknowns?: string[];
  [key: string]: unknown;
}

export interface MessageResearch {
  requested?: boolean;
  skipped?: string | null;
  review_rounds?: number;
  revisions?: number;
  timed_out?: boolean;
  [key: string]: unknown;
}

export interface MessageWebSearch {
  requested?: boolean;
  sources?: number;
  steps?: number;
  searches?: number;
  opened_pages?: number;
  queries?: string[];
  saved?: boolean;
  saved_source_id?: string | null;
  [key: string]: unknown;
}

/** Signals read from the user's request; unknown keys are tolerated. */
export interface MessageIntents {
  wants_deep_search?: boolean;
  wants_multi_source_check?: boolean;
  wants_primary_source?: boolean;
  wants_more_reasoning?: boolean;
  wants_no_web?: boolean;
  wants_fast_answer?: boolean;
  wants_source_saved_for_chat?: boolean;
  wants_existing_source_reused?: boolean;
  wants_verification?: boolean;
  [key: string]: unknown;
}

/** Optional per-message Working Source detail; not emitted yet. */
export interface MessageWorkingSource {
  title?: string;
  url?: string;
  created?: boolean;
  reused?: boolean;
  provenance?: string;
  extraction_status?: string;
  [key: string]: unknown;
}

export interface MessageLocalContext {
  working_sources: number | null;
  /** Titles of the Working Sources available for this answer. */
  working_titles: string[];
  /** `full` | `full_sources` | `hybrid` | `none` — how the context was assembled. */
  knowledge_strategy?: string | null;
  /** Tokens actually handed to the model, out of everything available. */
  context_tokens?: number | null;
  source_tokens?: number | null;
  /** Working Sources passed whole rather than sampled by relevance. */
  full_source_count?: number | null;
  full_source_tokens?: number | null;
  /** Older alias kept for forward compatibility. */
  working_used?: string[];
  working_source_details?: MessageWorkingSource[];
  knowledge_used?: boolean;
  previous_references?: number;
  [key: string]: unknown;
}

export interface MessageUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
}

/**
 * Operational diagnostics recorded while an answer was produced. Every nested
 * field is optional and unknown keys are preserved, so old messages (only
 * `total_ms`/`first_token_ms`) and future backend additions both map cleanly.
 */
export interface MessageTimings {
  total_ms: number | null;
  first_token_ms: number | null;
  route?: MessageRoute;
  request_anchor?: MessageRequestAnchor;
  research?: MessageResearch;
  web_search?: MessageWebSearch;
  intents?: MessageIntents;
  router_source?: RouterSource;
  local_context?: MessageLocalContext | null;
  /** Per-stage timings; most are not emitted by the backend yet. */
  router_ms?: number;
  anchor_ms?: number;
  local_retrieval_ms?: number;
  web_search_ms?: number;
  open_ms?: number;
  generation_ms?: number;
  review_ms?: number;
  refine_ms?: number;
  /** Forward compatibility: the raw object may carry more keys. */
  [key: string]: unknown;
}

export interface Message {
  id: string;
  chat_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  provider: string | null;
  model_id: string | null;
  usage: MessageUsage | null;
  timings: MessageTimings | null;
  /** Retrieval attribution; empty when the answer came from the model alone. */
  sources: MessageSource[];
  /** Referenced public-web sources for this answer, when the backend has them. */
  web_sources?: MessageWebSource[];
  /**
   * Ordered pipeline recorded for this answer. Lets a reloaded history render
   * the same timeline the stream produced.
   */
  phases: MessagePhase[];
  /**
   * Identifier of the temporary message this record replaced. The backend may
   * assign a different id to the final message, so the client matches on this.
   */
  replaces_client_id?: string | null;
  created_at: IsoDateTime;
}

/**
 * A Working Source attached to one chat: material the backend extracted and
 * keeps in the chat's local context. It is deliberately separate from the
 * mode's knowledge base — it exists only for this conversation.
 *
 * The extracted content is never sent to the console; only this metadata is.
 */
export interface ChatWorkingSource {
  id: string;
  title: string;
  /** The page the material was taken from; may be absent. */
  origin_url: string | null;
  origin_title: string | null;
  /** Backend processing status, e.g. `ready`; kept as an opaque string. */
  status: string | null;
  created_at: IsoDateTime | null;
}

export interface ChatWorkingSourceText {
  id: string;
  title: string;
  status: string;
  content: string;
  character_count: number;
}

/** A public-web page referenced inside one chat. */
export interface ChatReferencedSource {
  id: string;
  title: string;
  url: string;
  snippet: string | null;
  retrieved_at: IsoDateTime | null;
  /** The assistant message the reference belongs to, when known. */
  message_id: string | null;
  /** Present only when the server has actually extracted page text. */
  read_at?: IsoDateTime | null;
  character_count?: number;
}

/**
 * The `GET /v1/chats/{chat_id}/sources` payload. The backend already drops
 * referenced entries whose `url` equals a working source's `origin_url`; the UI
 * deduplicates again so it never shows the same page twice.
 */
export interface ChatSources {
  working: ChatWorkingSource[];
  referenced: ChatReferencedSource[];
}

export interface ChatCreateInput {
  /** `null` creates a Quick Chat. */
  mode_id: string | null;
  title?: string;
}

export interface ChatUpdateInput {
  title?: string;
  /** Persisted chat preference, shared by both web surfaces. */
  pinned?: boolean;
}

/** Options the backend already accepts for a completion request. */
export interface SendMessageInput {
  chat_id: string;
  content: string;
  /**
   * RESEARCH mode: deeper checking and refinement. It never forces the web —
   * the Router still decides retrieval. The console sends only this flag.
   */
  research_mode?: boolean;
  /**
   * Explicit web flags. The backend still accepts them, but the console no
   * longer offers this choice: in AUTO the Router decides.
   */
  web_search?: boolean;
  web_research?: boolean;
  /** Client-generated id of the optimistic user message. */
  client_message_id?: string;
  /** Client-generated id of the temporary assistant message. */
  client_assistant_id?: string;
  signal?: AbortSignal;
}

/** Events a streaming implementation reports while producing an answer. */
export interface ChatStreamHandlers {
  /** The temporary assistant message has been created and is visible. */
  onAssistantCreated?: (message: Message) => void;
  /** The pipeline advanced to a new phase. */
  onPhase?: (messageId: string, phase: MessagePhase) => void;
  /** A chunk of answer text arrived. */
  onDelta?: (messageId: string, delta: string) => void;
  /** The final message replaces the temporary one. */
  onFinal?: (message: Message) => void;
  onError?: (messageId: string, message: string) => void;
}
