import type { SpeechPacket, SpeechResult } from '@/lib/streamingDictation';
import type {
  Chat,
  ChatCreateInput,
  ChatSources,
  ChatWorkingSourceText,
  ChatStreamHandlers,
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
  SendMessageInput,
  Settings,
  SourceContent,
  SourceUploadInput,
  SourceUploadResult,
  SystemHealth,
} from '@/types';

/* =============================================================================
   The single seam between the console and WristMind.

   Everything here is async and transport-agnostic: no React, no router, no
   component state. `MockWristMindService` implements it today; an
   `ApiWristMindService` over the real HTTP API implements it later, and no
   page or component has to change.
   ========================================================================== */

/** Server-initiated changes, delivered by polling, SSE or a socket. */
export type WristMindEvent =
  | { type: 'mode.updated'; mode: Mode }
  | { type: 'mode.removed'; mode_id: string }
  | { type: 'chat.updated'; chat: Chat }
  | { type: 'chat.removed'; chat_id: string }
  | { type: 'message.updated'; message: Message }
  | { type: 'source.updated'; source: KnowledgeSource }
  | { type: 'source.removed'; source_id: string }
  | { type: 'device.updated'; device: Device }
  | { type: 'device.removed'; device_id: string }
  | { type: 'pairing.updated'; code: PairingCode }
  | { type: 'pairing.removed'; code: string };

export type WristMindEventListener = (event: WristMindEvent) => void;

/* =============================================================================
   Live account feed (`GET /v1/events`).

   The local `WristMindEvent` bus above carries whole entities because this
   process produced them. The server feed deliberately does not: it names what
   changed, and the store refetches that slice. A payload that was already
   superseded on the server can therefore never overwrite newer local state.
   ========================================================================== */

export interface AccountEvent {
  id: number;
  type: string;
  data: Record<string, unknown>;
}

export interface AccountEventHandlers {
  onEvent(event: AccountEvent): void;
  /** The cursor fell behind the retention window: reload everything once. */
  onResync?(): void;
  onStatusChange?(connected: boolean): void;
}

export const ACCOUNT_EVENT = {
  chatCreated: 'chat.created',
  chatUpdated: 'chat.updated',
  chatDeleted: 'chat.deleted',
  messageCreated: 'message.created',
  messageUpdated: 'message.updated',
  modeUpdated: 'mode.updated',
  modeRemoved: 'mode.removed',
  sourceUpdated: 'source.updated',
  sourceRemoved: 'source.removed',
  deviceUpdated: 'device.updated',
  deviceRemoved: 'device.removed',
  settingsUpdated: 'settings.updated',
  pairingUpdated: 'pairing.updated',
  resync: 'resync',
} as const;

export interface ModesService {
  list(): Promise<Mode[]>;
  get(id: string): Promise<Mode>;
  create(input: ModeCreateInput): Promise<Mode>;
  update(id: string, input: ModeUpdateInput): Promise<Mode>;
  /** Soft delete: the mode is hidden and its data is detached. */
  remove(id: string): Promise<void>;
}

export interface ChatsService {
  list(): Promise<Chat[]>;
  get(id: string): Promise<Chat>;
  create(input: ChatCreateInput): Promise<Chat>;
  update(id: string, input: ChatUpdateInput): Promise<Chat>;
  remove(id: string): Promise<void>;
  messages(chatId: string): Promise<Message[]>;
  /**
   * Working and referenced sources scoped to exactly one chat. Read-only: the
   * message history never carries the full chat-level index.
   */
  sources(chatId: string): Promise<ChatSources>;
  /** Full saved text, fetched only when the owner opens a Working Source. */
  workingSourceText(chatId: string, sourceId: string): Promise<ChatWorkingSourceText>;
  /**
   * Starts a completion and reports progress through `handlers`:
   * temporary assistant message → phases → text deltas → final message.
   */
  send(input: SendMessageInput, handlers?: ChatStreamHandlers): Promise<Message>;
}

export interface KnowledgeService {
  list(modeId?: string): Promise<KnowledgeSource[]>;
  get(id: string): Promise<KnowledgeSource>;
  /** Extracted pages and chunks; loaded only when a source is opened. */
  content(id: string): Promise<SourceContent>;
  /** Returns a background job; watch `subscribe` for status changes. */
  upload(input: SourceUploadInput): Promise<SourceUploadResult>;
  reprocess(id: string): Promise<void>;
  remove(id: string): Promise<void>;
}

export interface DevicesService {
  list(): Promise<Device[]>;
  revoke(id: string): Promise<void>;
  remove(id: string): Promise<void>;
}

export interface PairingService {
  list(): Promise<PairingCode[]>;
  create(targetKind: DeviceKind | null): Promise<PairingCode>;
  revoke(code: string): Promise<void>;
}

export interface ModelsService {
  list(): Promise<Model[]>;
}

export interface SettingsService {
  get(): Promise<Settings>;
  update(patch: Partial<Settings>): Promise<Settings>;
}

export interface StatsService {
  overview(): Promise<OverviewStats>;
}

export interface SystemService {
  health(): Promise<SystemHealth>;
  /** Prototype helper: restores the demo dataset. */
  resetDemoData(): Promise<void>;
}

export interface WristMindService {
  speechStream?(packet: SpeechPacket, signal: AbortSignal): Promise<SpeechResult>;
  transcribeAudio?(audio: Blob, signal: AbortSignal): Promise<string>;
  readonly modes: ModesService;
  readonly chats: ChatsService;
  readonly knowledge: KnowledgeService;
  readonly devices: DevicesService;
  readonly pairing: PairingService;
  readonly models: ModelsService;
  readonly settings: SettingsService;
  readonly stats: StatsService;
  readonly system: SystemService;
  /** Server-initiated change feed. Returns an unsubscribe function. */
  subscribe(listener: WristMindEventListener): () => void;
  /**
   * Live account feed over SSE, resumable from `after`. Optional: an
   * implementation without a stream simply omits it and the store keeps
   * refreshing through its polling fallback.
   */
  subscribeAccountEvents?(after: number, handlers: AccountEventHandlers): () => void;
  /**
   * Optional single round-trip warm-up. Implementations that need several
   * requests simply omit it and the store falls back to parallel `list()` calls.
   */
  bootstrap?(): Promise<BootstrapResult>;
}

/** Loads every dataset the console needs for a first paint. */
export interface BootstrapResult {
  modes: Mode[];
  chats: Chat[];
  sources: KnowledgeSource[];
  devices: Device[];
  pairingCodes: PairingCode[];
  models: Model[];
  settings: Settings;
  stats: OverviewStats;
  health: SystemHealth;
}
