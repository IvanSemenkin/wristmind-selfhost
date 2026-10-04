/* =============================================================================
   Shared primitives for the WristMind API contract.

   Field names mirror the backend exactly (snake_case), so a real HTTP adapter
   can return payloads without a translation layer.
   ========================================================================== */

/** ISO-8601 timestamp with timezone, e.g. `2025-09-27T14:03:11.482Z`. */
export type IsoDateTime = string;

/** Soft-delete marker: `null` while the entity is alive. */
export type DeletedAt = IsoDateTime | null;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PageQuery {
  limit?: number;
  offset?: number;
}

/** Uniform shape for anything that can be in progress. */
export type JobStatus = 'uploading' | 'processing' | 'ready' | 'error';

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
