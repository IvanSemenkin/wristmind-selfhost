/* =============================================================================
   Service errors.

   Transport failures are normalised into one type so the UI can show a useful
   message regardless of whether it is talking to the mock or to HTTP.
   ========================================================================== */

export type WristMindErrorCode =
  | 'not_found'
  | 'conflict'
  | 'invalid'
  | 'unauthorized'
  | 'network'
  | 'server'
  | 'aborted'
  | 'unknown';

export class WristMindError extends Error {
  readonly code: WristMindErrorCode;
  readonly status: number | null;
  readonly details: Record<string, unknown> | undefined;

  constructor(
    message: string,
    options: {
      code?: WristMindErrorCode;
      status?: number | null;
      details?: Record<string, unknown>;
      cause?: unknown;
    } = {},
  ) {
    super(message);
    this.name = 'WristMindError';
    this.code = options.code ?? 'unknown';
    this.status = options.status ?? null;
    this.details = options.details;
    if (options.cause !== undefined) this.cause = options.cause;
  }
}

export function isAbortError(error: unknown): boolean {
  return (
    error instanceof WristMindError
      ? error.code === 'aborted'
      : error instanceof DOMException && error.name === 'AbortError'
  );
}

/** Turns any thrown value into a message safe to render in a toast. */
export function describeError(error: unknown, fallback = 'Не удалось выполнить запрос'): string {
  if (error instanceof WristMindError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
