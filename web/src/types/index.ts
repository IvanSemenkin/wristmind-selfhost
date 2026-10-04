/* =============================================================================
   WristMind domain contract.

   This barrel is the single place the console imports types from. Everything
   here mirrors the backend payloads one-to-one, so an `ApiWristMindService`
   can be dropped in without touching pages or components.
   ========================================================================== */

export type {
  ApiErrorBody,
  DeletedAt,
  IsoDateTime,
  JobStatus,
  Page,
  PageQuery,
} from './common';

export {
  DEFAULT_MODE_COLOR,
  MODE_COLORS,
  normalizeModeColor,
} from './mode';
export type { Mode, ModeColor, ModeCreateInput, ModeUpdateInput } from './mode';

export { expectedPipeline, isMessagePhase, MESSAGE_PHASE_LABELS, MESSAGE_PHASES } from './chat';
export type {
  Chat,
  ChatCreateInput,
  ChatReferencedSource,
  ChatSources,
  ChatStreamHandlers,
  ChatUpdateInput,
  ChatWorkingSource,
  ChatWorkingSourceText,
  Message,
  MessageIntents,
  MessageLocalContext,
  MessagePhase,
  MessageRequestAnchor,
  MessageResearch,
  MessageRole,
  MessageRoute,
  MessageSource,
  MessageStatus,
  MessageTimings,
  MessageUsage,
  MessageWebSearch,
  MessageWebSource,
  MessageWorkingSource,
  ReasoningLevel,
  RequestAnchorMode,
  RetrievalRoute,
  RetrievalTaskType,
  RouterSource,
  SendMessageInput,
} from './chat';

export {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_MEDIA_TYPES,
  PROCESSING_MODE_LABELS,
  PROCESSING_MODES,
  sourceKind,
} from './knowledge';
export type {
  KnowledgeSource,
  ProcessingMode,
  SourceChunk,
  SourceContent,
  SourceKind,
  SourcePage,
  SourceUploadInput,
  SourceUploadResult,
} from './knowledge';

export {
  DEVICE_KINDS,
  DEVICE_KIND_LABELS,
  PAIRING_CODE_LENGTH,
  PAIRING_CODE_TTL_MS,
  devicePresence,
  isPairingCodeActive,
} from './device';
export type { Device, DeviceKind, DevicePresence, PairingCode } from './device';

export { findModel, MODEL_CAPABILITY_LABELS } from './model';
export type { Model, ModelCapability } from './model';

export type {
  ActivityPoint,
  ApiPath,
  OverviewStats,
  ServiceHealth,
  ServiceStatus,
  Settings,
  SystemHealth,
  UsageBreakdown,
} from './settings';
