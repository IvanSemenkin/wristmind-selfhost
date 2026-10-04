import type { IsoDateTime } from '@/types';

/* =============================================================================
   Deterministic helpers for the mock dataset.

   Seeded pseudo-randomness keeps generated fixtures stable between reloads so
   screenshots, charts and tests do not shift on every refresh.
   ========================================================================== */

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Fixtures are generated once per module load, relative to "now". */
export const NOW = Date.now();
export const MINUTE = 60_000;
export const HOUR = 3_600_000;
export const DAY = 24 * HOUR;

export const ago = (ms: number): IsoDateTime => new Date(NOW - ms).toISOString();
export const ahead = (ms: number): IsoDateTime => new Date(NOW + ms).toISOString();
