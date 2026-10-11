import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import type { ReactElement, ReactNode } from 'react';
import { Check } from 'lucide-react';
import { useEscapeKey, useOnClickOutside } from '@/lib/hooks';
import { computeFloatingPosition, type FloatingOutput } from './floating';
import styles from './Menu.module.css';

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

export interface MenuAction {
  type?: 'item';
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  /** Renders a check mark; use for toggles. */
  checked?: boolean;
  description?: string;
  onSelect: () => void;
}

export interface MenuSeparator {
  type: 'separator';
  id?: string;
}

export interface MenuLabel {
  type: 'label';
  id?: string;
  label: string;
}

export type MenuEntry = MenuAction | MenuSeparator | MenuLabel;

export interface MenuProps {
  /** A single interactive element. It receives the click handler and ref. */
  trigger: ReactElement<{
    onClick?: (event: React.MouseEvent) => void;
    onKeyDown?: (event: React.KeyboardEvent) => void;
    ref?: React.Ref<HTMLElement>;
    'aria-expanded'?: boolean;
    'aria-haspopup'?: string;
  }>;
  entries: MenuEntry[];
  align?: 'start' | 'end';
  side?: 'bottom' | 'top';
  /** Fixed width; omit to size to content. Either way it is clamped on screen. */
  width?: number;
  header?: ReactNode;
  variant?: 'menu' | 'select';
  /** Controlled open state, for menus driven from other UI (e.g. context menus). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const isAction = (entry: MenuEntry): entry is MenuAction =>
  (entry as MenuSeparator).type !== 'separator' && (entry as MenuLabel).type !== 'label';

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

export function Menu({
  trigger,
  entries,
  align = 'start',
  side = 'bottom',
  width,
  header,
  variant = 'menu',
  open: controlledOpen,
  onOpenChange,
}: MenuProps) {
  const [uncontrolled, setUncontrolled] = useState(false);
  const open = controlledOpen ?? uncontrolled;

  const setOpen = useCallback(
    (next: boolean) => {
      setUncontrolled(next);
      onOpenChange?.(next);
    },
    [onOpenChange],
  );

  const triggerRef = useRef<HTMLElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const naturalRef = useRef<{ width: number; height: number } | null>(null);
  const [layout, setLayout] = useState<FloatingOutput | null>(null);

  /**
   * Measures at natural size, then asks the shared engine where the menu fits.
   * Using natural dimensions (rather than the clamped ones from the previous
   * pass) keeps flipping decisions stable while scrolling.
   */
  const reposition = useCallback(() => {
    const anchorEl = triggerRef.current;
    const menu = menuRef.current;
    if (!anchorEl) return;

    if (menu) {
      const previousMaxHeight = menu.style.maxHeight;
      const previousWidth = menu.style.width;
      menu.style.maxHeight = 'none';
      menu.style.width = width ? `${width}px` : 'max-content';
      const measured = menu.getBoundingClientRect();
      menu.style.maxHeight = previousMaxHeight;
      menu.style.width = previousWidth;
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
        align,
        side,
      }),
    );
  }, [align, side, width]);

  // A portalled menu is mounted after the trigger has already changed its
  // open state. Measure again from the ref callback so the first opening can
  // never remain at the hidden off-screen fallback position.
  const setMenuElement = useCallback(
    (node: HTMLDivElement | null) => {
      menuRef.current = node;
      if (node) requestAnimationFrame(reposition);
    },
    [reposition],
  );

  useLayoutEffect(() => {
    if (!open) {
      setLayout(null);
      naturalRef.current = null;
      return;
    }
    reposition();
    const raf = requestAnimationFrame(reposition);
    return () => cancelAnimationFrame(raf);
    // `entries` is a new array on every render, so only its length is a safe
    // dependency — anything else re-runs the effect forever.
  }, [open, reposition, entries.length]);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => reposition();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [open, reposition]);

  useOnClickOutside(
    menuRef,
    (event) => {
      // Clicks inside the menu are handled by the item itself; only the trigger
      // is excluded here because it toggles the menu on click.
      if (triggerRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    },
    open,
  );

  useEscapeKey(() => {
    setOpen(false);
    triggerRef.current?.focus?.();
  }, open);

  const focusItem = (direction: 1 | -1 | 'first' | 'last') => {
    const menu = menuRef.current;
    if (!menu) return;
    const items = Array.from(
      menu.querySelectorAll<HTMLButtonElement>('[data-menu-item]:not([disabled])'),
    );
    if (items.length === 0) return;
    const current = document.activeElement as HTMLElement | null;
    const index = current ? items.indexOf(current as HTMLButtonElement) : -1;
    if (direction === 'first') items[0].focus();
    else if (direction === 'last') items[items.length - 1].focus();
    else {
      const next = index === -1 ? (direction === 1 ? 0 : items.length - 1) : index + direction;
      items[(next + items.length) % items.length].focus();
    }
  };

  useEffect(() => {
    if (!open) return;
    const raf = requestAnimationFrame(() => {
      const menu = menuRef.current;
      if (!menu) return;
      if (!menu.contains(document.activeElement) || document.activeElement === menu) {
        const selected = menu.querySelector<HTMLButtonElement>('[aria-checked="true"]:not([disabled])');
        if (selected) selected.focus();
        else focusItem('first');
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [open]);

  const triggerNode = isValidElement(trigger)
    ? cloneElement(trigger, {
        ref: (node: HTMLElement | null) => {
          triggerRef.current = node;
          const original = trigger.props.ref;
          if (typeof original === 'function') original(node);
          else if (original && typeof original === 'object') {
            (original as React.MutableRefObject<HTMLElement | null>).current = node;
          }
        },
        onClick: (event: React.MouseEvent) => {
          trigger.props.onClick?.(event);
          if (event.defaultPrevented) return;
          setOpen(!open);
        },
        onKeyDown: (event: React.KeyboardEvent) => {
          trigger.props.onKeyDown?.(event);
          if (!event.defaultPrevented && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault();
            setOpen(true);
          }
        },
        'aria-expanded': open,
        'aria-haspopup': 'menu',
      })
    : trigger;

  return (
    <>
      {triggerNode}
      {open &&
        createPortal(
          <div
            ref={setMenuElement}
            role="menu"
            aria-orientation="vertical" className={styles.menu} data-variant={variant}
            style={{
              top: layout?.top ?? -9999,
              left: layout?.left ?? -9999,
              width: layout ? layout.width : width,
              maxHeight: layout?.maxHeight ?? undefined,
              visibility: layout ? 'visible' : 'hidden',
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                focusItem(1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                focusItem(-1);
              } else if (event.key === 'Home') {
                event.preventDefault();
                focusItem('first');
              } else if (event.key === 'End') {
                event.preventDefault();
                focusItem('last');
              } else if (event.key === 'Tab') {
                setOpen(false);
              }
            }}
          >
            {header && <div className={styles.header}>{header}</div>}
            <div className={styles.list}>
              {entries.map((entry, i) => {
                if (!isAction(entry)) {
                  if ((entry as MenuLabel).type === 'label') {
                    return (
                      <div key={entry.id ?? `label-${i}`} className={styles.groupLabel}>
                        {(entry as MenuLabel).label}
                      </div>
                    );
                  }
                  return (
                    <div key={entry.id ?? `sep-${i}`} className={styles.separator} role="separator" />
                  );
                }
                return (
                  <button
                    key={entry.id}
                    type="button" role={entry.checked === undefined ? "menuitem" : "menuitemradio"}
                    aria-checked={entry.checked}
                    data-selected={entry.checked || undefined}
                    data-menu-item
                    disabled={entry.disabled}
                    data-danger={entry.danger || undefined}
                    className={styles.item}
                    onClick={() => {
                      setOpen(false);
                      entry.onSelect();
                      triggerRef.current?.focus();
                    }}
                  >
                    <span className={styles.itemIcon}>{entry.checked ? <Check /> : entry.icon}</span>
                    <span className={styles.itemBody}>
                      <span className={styles.itemLabel}>{entry.label}</span>
                      {entry.description && (
                        <span className={styles.itemDescription}>{entry.description}</span>
                      )}
                    </span>
                    {entry.shortcut && <span className={styles.shortcut}>{entry.shortcut}</span>}
                  </button>
                );
              })}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

export function menuDivider(): MenuSeparator {
  return { type: 'separator' };
}

export const menuItem = (item: MenuAction): MenuAction => ({ ...item, type: 'item' });
