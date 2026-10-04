/* =============================================================================
   Settings & statistics
   ========================================================================== */

export interface Settings {
  developer_mode: boolean;
  /** Applies to every mode; a mode's own prompt is appended after it. */
  global_system_prompt: string;
  /** Determines whether a request needs a reusable source for later turns. */
  source_intent_prompt: string;
  /** Verifies that an opened page is the requested reusable material. */
  source_candidate_prompt: string;
  /** How many trailing messages are sent to the model as conversation context. */
  history_limit: number;
  default_model_id: string;
  stream_responses: boolean;
  /** Days before chat history is pruned; 0 keeps it indefinitely. */
  retention_days: number;
}

/* -------------------------------------------------------------------------- */
/* Statistics                                                                 */
/* -------------------------------------------------------------------------- */

export interface ActivityPoint {
  /** Bucket start, ISO-8601. */
  bucket: string;
  requests: number;
  errors: number;
}

export interface UsageBreakdown {
  mode_id: string;
  requests: number;
  tokens: number;
}

export interface OverviewStats {
  /** All accepted ANSWER jobs, including chats that were later deleted. */
  total_ai_requests: number;
  modes_total: number;
  modes_hidden_on_watch: number;
  chats_total: number;
  sources_total: number;
  sources_ready: number;
  sources_processing: number;
  sources_error: number;
  requests_today: number;
  requests_yesterday: number;
  error_rate_today: number;
  activity: ActivityPoint[];
  usage: UsageBreakdown[];
}

/* -------------------------------------------------------------------------- */
/* System health                                                              */
/* -------------------------------------------------------------------------- */

export type ServiceStatus = 'operational' | 'degraded' | 'down';

/**
 * Which path currently serves the assistant. `local` is the normal state: the
 * local backend answers. `fallback` is the reserved state: the local backend is
 * unreachable and the external VPS answers instead. The watch shows the same
 * distinction as a yellow dot next to the green one.
 */
export type ApiPath = 'local' | 'fallback' | 'none';

export interface ServiceHealth {
  id: 'api' | 'phone' | 'watch' | 'ingest';
  label: string;
  status: ServiceStatus;
  detail: string;
  latency_ms: number | null;
  last_seen_at: string;
}

export interface SystemHealth {
  services: ServiceHealth[];
  /** Path that answered this probe. */
  api_path: ApiPath;
  /** Server build the console is talking to. */
  version: string | null;
  generated_at: string;
}
