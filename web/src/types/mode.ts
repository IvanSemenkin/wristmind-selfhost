import type { DeletedAt, IsoDateTime } from './common';

/* =============================================================================
   Mode — an isolated workspace of the assistant.
   ========================================================================== */

/**
 * Palette keys understood by the UI. The backend stores a plain string, so
 * unknown values are normalised to `blue` rather than breaking rendering.
 */
export const MODE_COLORS = [
  'blue',
  'cyan',
  'teal',
  'emerald',
  'lime',
  'amber',
  'orange',
  'rose',
  'pink',
  'violet',
] as const;

export type ModeColor = (typeof MODE_COLORS)[number];

export const DEFAULT_MODE_COLOR: ModeColor = 'blue';

export function normalizeModeColor(value: string | null | undefined): ModeColor {
  if (value && (MODE_COLORS as readonly string[]).includes(value)) {
    return value as ModeColor;
  }
  return DEFAULT_MODE_COLOR;
}

export interface Mode {
  id: string;
  name: string;
  description: string;
  color: ModeColor;
  /** Emoji or icon name shown instead of the colour dot, when provided. */
  icon: string | null;
  /** Telegram premium emoji id; opaque to the console. */
  telegram_emoji_id: string | null;
  system_prompt: string;
  /** Model used for answers in this mode. */
  response_model_id: string;
  hidden_on_watch: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  deleted_at: DeletedAt;
}

/** Payload accepted when creating a mode. Server-managed fields are omitted. */
export interface ModeCreateInput {
  name: string;
  description: string;
  color: ModeColor;
  icon?: string | null;
  telegram_emoji_id?: string | null;
  system_prompt: string;
  response_model_id: string;
  hidden_on_watch: boolean;
}

export type ModeUpdateInput = Partial<ModeCreateInput>;
