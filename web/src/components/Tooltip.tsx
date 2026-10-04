import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import {
  computeFloatingPosition,
  FLOATING_GUTTER,
  type FloatingOutput,
  type FloatingSide,
} from './floating';
import styles from './Tooltip.module.css';

/**
 * Marks a subtree as already explained by a tooltip. Controls such as
 * `IconButton` read this to avoid rendering a second, native browser tooltip.
 */
const InsideTooltipContext = createContext(false);

export const useInsideTooltip = (): boolean => useContext(InsideTooltipContext);

export interface TooltipProps {
  label: ReactNode;
  children: ReactNode;
  /** Preferred side; flips automatically when there is not enough room. */
  side?: FloatingSide;
  /** Maximum bubble width before the text wraps. */
  maxWidth?: number;
  /** Render children as-is, without the inline wrapper. */
  className?: string;
  disabled?: boolean;
}

/**
 * Viewport-aware tooltip.
 *
 * Positioning is delegated to `computeFloatingPosition`, so the bubble is
 * always pulled back inside the screen — including anchors sitting against the
 * left or right edge of a narrow window. Touch devices suppress it entirely,
 * which is why the handlers are mouse/focus only.
 */
export function Tooltip({
  label,
  children,
  side = 'top',
  maxWidth = 280,
  className,
  disabled = false,
}: TooltipProps) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  const naturalRef = useRef<{ width: number; height: number } | null>(null);

  const [open, setOpen] = useState(false);
  const [layout, setLayout] = useState<FloatingOutput | null>(null);

  const reposition = useCallback(() => {
    const anchorEl = anchorRef.current;
    const bubble = bubbleRef.current;
    if (!anchorEl) return;

    // Measure at natural size so flipping decisions are not based on a
    // previously clamped dimension.
    if (bubble) {
      const previousMax = bubble.style.maxHeight;
      const previousWidth = bubble.style.width;
      bubble.style.maxHeight = 'none';
      bubble.style.width = 'max-content';
      const measured = bubble.getBoundingClientRect();
      bubble.style.maxHeight = previousMax;
      bubble.style.width = previousWidth;
      if (measured.width > 0 && measured.height > 0) {
        naturalRef.current = { width: measured.width, height: measured.height };
      }
    }

    const natural = naturalRef.current;
    if (!natural) return;

    setLayout(
      computeFloatingPosition({
        anchor: anchorEl.getBoundingClientRect(),
        floating: natural,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        side,
        align: 'center',
        gutter: FLOATING_GUTTER,
        maxWidth,
      }),
    );
  }, [side, maxWidth]);

  useLayoutEffect(() => {
    if (!open) {
      setLayout(null);
      naturalRef.current = null;
      return;
    }
    reposition();
    const raf = requestAnimationFrame(reposition);
    return () => cancelAnimationFrame(raf);
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => reposition();
    const onResize = () => reposition();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  const show = () => {
    if (!disabled) setOpen(true);
  };
  const hide = () => setOpen(false);

  return (
    <InsideTooltipContext.Provider value>
      <span
        ref={anchorRef}
        className={cn(styles.anchor, className)}
        data-floating-anchor="tooltip" onMouseEnter={show}
        onMouseLeave={hide}
        // Pointer events cover pens; `touch` is ignored so phones never get
        // stuck tooltips.
        onPointerDown={(event) => {
          if (event.pointerType === 'touch') hide();
        }}
        onFocusCapture={show}
        onBlurCapture={hide}
      >
        {children}
      </span>
      {open &&
        label != null &&
        createPortal(
          <div
            ref={bubbleRef}
            className={styles.bubble}
            data-side={layout?.side ?? side}
            aria-hidden="true" style={{
              top: layout?.top ?? -9999,
              left: layout?.left ?? -9999,
              width: layout && layout.width < maxWidth ? layout.width : undefined,
              maxWidth: layout?.width ?? maxWidth,
              maxHeight: layout?.maxHeight ?? undefined,
              visibility: layout ? 'visible' : 'hidden',
            }}
          >
            {label}
          </div>,
          document.body,
        )}
    </InsideTooltipContext.Provider>
  );
}
