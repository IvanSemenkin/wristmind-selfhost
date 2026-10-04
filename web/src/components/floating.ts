/* =============================================================================
   Floating-layer positioning.

   One place that decides where a tooltip / dropdown / popover goes, so every
   overlay in the product behaves the same way:

   - never leaves the viewport;
   - keeps a small gutter (8–12px) from every edge;
   - flips to the opposite side when there is not enough room;
   - shrinks to the available space instead of overflowing.

   Pure function — no DOM access — so it is easy to reason about and test.
   ========================================================================== */

export type FloatingSide = 'top' | 'bottom';
export type FloatingAlign = 'start' | 'center' | 'end';

/** Minimum distance kept between a floating layer and the viewport edge. */
export const FLOATING_GUTTER = 10;

/** Distance between the anchor and the floating layer. */
export const FLOATING_OFFSET = 6;

export interface RectLike {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface FloatingInput {
  anchor: RectLike;
  /** Natural (unconstrained) size of the floating layer. */
  floating: { width: number; height: number };
  viewport: { width: number; height: number };
  align?: FloatingAlign;
  side?: FloatingSide;
  offset?: number;
  /** Requested gutter; clamped to a sane 8–12px range. */
  gutter?: number;
  /** Never let the layer grow beyond this, regardless of the viewport. */
  maxWidth?: number;
}

export interface FloatingOutput {
  top: number;
  left: number;
  /** Side actually used — may differ from the requested one after flipping. */
  side: FloatingSide;
  /** Resolved width after viewport clamping. */
  width: number;
  /** Set when the layer must scroll vertically to fit. */
  maxHeight: number | null;
  /** True when the layer had to be flipped or shrunk. */
  constrained: boolean;
}

export function computeFloatingPosition(input: FloatingInput): FloatingOutput {
  const gutter = clamp(input.gutter ?? FLOATING_GUTTER, 8, 12);
  const offset = input.offset ?? FLOATING_OFFSET;
  const { anchor, viewport, floating } = input;

  // Available room on each axis after reserving the gutter on both sides.
  const usableWidth = Math.max(0, viewport.width - gutter * 2);
  const width = Math.max(
    0,
    Math.min(floating.width, usableWidth, input.maxWidth ?? Number.POSITIVE_INFINITY),
  );

  /* ---- Horizontal: align, then shift inside the viewport ---------------- */
  let left: number;
  switch (input.align ?? 'start') {
    case 'center':
      left = anchor.left + anchor.width / 2 - width / 2;
      break;
    case 'end':
      left = anchor.right - width;
      break;
    default:
      left = anchor.left;
  }
  const maxLeft = Math.max(gutter, viewport.width - width - gutter);
  left = clamp(left, gutter, maxLeft);

  /* ---- Vertical: prefer the requested side, flip when it does not fit --- */
  const roomBelow = viewport.height - anchor.bottom - offset - gutter;
  const roomAbove = anchor.top - offset - gutter;
  const desired = input.side ?? 'bottom';

  let side: FloatingSide;
  if (desired === 'bottom') {
    if (floating.height <= roomBelow) side = 'bottom';
    else if (floating.height <= roomAbove) side = 'top';
    else side = roomBelow >= roomAbove ? 'bottom' : 'top';
  } else {
    if (floating.height <= roomAbove) side = 'top';
    else if (floating.height <= roomBelow) side = 'bottom';
    else side = roomAbove >= roomBelow ? 'top' : 'bottom';
  }

  const room = side === 'bottom' ? roomBelow : roomAbove;
  const fits = floating.height <= room;
  // Never taller than the space on the chosen side; keep a usable minimum.
  const maxHeight = fits ? null : Math.max(80, Math.min(room, viewport.height - gutter * 2));
  const height = maxHeight ?? floating.height;

  let top = side === 'bottom' ? anchor.bottom + offset : anchor.top - offset - height;
  const maxTop = Math.max(gutter, viewport.height - height - gutter);
  top = clamp(top, gutter, maxTop);

  return {
    top,
    left,
    side,
    width,
    maxHeight,
    constrained: side !== desired || width < floating.width || maxHeight !== null,
  };
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}
