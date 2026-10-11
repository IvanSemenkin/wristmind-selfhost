import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Check, Info, X, XCircle } from 'lucide-react';
import { cn } from '@/lib/cn';
import { createId } from '@/lib/id';
import { IconButton } from './Button';
import styles from './Toast.module.css';

export type ToastTone = 'default' | 'success' | 'danger' | 'warning';

export interface ToastOptions {
  title: string;
  description?: ReactNode;
  tone?: ToastTone;
  duration?: number;
  action?: { label: string; onClick: () => void };
}

interface ToastRecord extends ToastOptions {
  id: string;
}

interface ToastApi {
  toast: (options: ToastOptions) => string;
  success: (title: string, description?: ReactNode) => string;
  error: (title: string, description?: ReactNode) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICONS: Record<ToastTone, ReactNode> = {
  default: <Info />,
  success: <Check />,
  danger: <XCircle />,
  warning: <AlertTriangle />,
};

/** Horizontal travel that dismisses a toast instead of snapping it back. */
const SWIPE_DISMISS_PX = 64;
/** Travel at which a dragged toast has faded out completely. */
const SWIPE_FADE_PX = 220;

/**
 * One notification.
 *
 * It follows a horizontal drag and dismisses past a threshold, in either
 * direction — a toast that covers the list underneath should be removable by
 * the gesture people already use, not only by the close button. Vertical motion
 * is left to the page: `touch-action: pan-y` keeps scrolling working.
 *
 * While the pointer rests on it, or the keyboard is inside it, the auto-dismiss
 * countdown is held; releasing starts it over from the full duration, so a toast
 * being read never disappears mid-interaction.
 */
function ToastCard({
  item,
  onDismiss,
  onHoldStart,
  onHoldEnd,
}: {
  item: ToastRecord;
  onDismiss: (id: string) => void;
  onHoldStart: (id: string) => void;
  onHoldEnd: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  // The gesture's own state lives in refs: a pointer sequence must not depend on
  // a re-render having landed between two events.
  const draggingRef = useRef(false);
  const startX = useRef(0);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    // A drag that starts on the close button or an action is that control's.
    if ((event.target as HTMLElement).closest('button, a')) return;
    draggingRef.current = true;
    startX.current = event.clientX;
    setDragging(true);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Capture is an optimisation: without it the drag still works, it just
      // stops tracking once the pointer leaves the toast.
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    setOffset(event.clientX - startX.current);
  };

  const handlePointerEnd = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    setDragging(false);
    // Measured from the release event, so the threshold never reads stale state.
    if (Math.abs(event.clientX - startX.current) >= SWIPE_DISMISS_PX) {
      onDismiss(item.id);
      return;
    }
    setOffset(0);
  };

  return (
    <div
      className={styles.toast}
      data-tone={item.tone ?? 'default'}
      data-dragging={dragging || undefined}
      style={{
        transform: offset ? `translateX(${offset}px)` : undefined,
        opacity: offset ? Math.max(0, 1 - Math.abs(offset) / SWIPE_FADE_PX) : undefined,
      }}
      role="status"
      aria-live="polite"
      onPointerEnter={() => onHoldStart(item.id)}
      onPointerLeave={() => onHoldEnd(item.id)}
      onPointerDown={(event) => {
        onHoldStart(item.id);
        handlePointerDown(event);
      }}
      onPointerMove={handlePointerMove}
      onPointerUp={(event) => {
        handlePointerEnd(event);
        onHoldEnd(item.id);
      }}
      onPointerCancel={(event) => {
        handlePointerEnd(event);
        onHoldEnd(item.id);
      }}
      onFocus={() => onHoldStart(item.id)}
      onBlur={(event) => {
        // Moving focus between the toast's own controls is not leaving it.
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          onHoldEnd(item.id);
        }
      }}
    >
      <span className={styles.icon}>{ICONS[item.tone ?? 'default']}</span>
      <div className={styles.body}>
        <div className={styles.title}>{item.title}</div>
        {item.description && <div className={styles.description}>{item.description}</div>}
        {item.action && (
          <button
            type="button" className={styles.action}
            onClick={() => {
              item.action?.onClick();
              onDismiss(item.id);
            }}
          >
            {item.action.label}
          </button>
        )}
      </div>
      <IconButton
        label="Закрыть" size="xs" icon={<X />}
        className={cn(styles.close)}
        onClick={() => onDismiss(item.id)}
      />
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<string, number>());
  // Kept separately from the rendered list so a paused toast can be restarted
  // without reading state during a render.
  const durations = useRef(new Map<string, number>());

  const clearTimer = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const dismiss = useCallback(
    (id: string) => {
      clearTimer(id);
      durations.current.delete(id);
      setToasts((current) => current.filter((t) => t.id !== id));
    },
    [clearTimer],
  );

  /** (Re)starts the auto-dismiss countdown from the toast's full duration. */
  const startTimer = useCallback(
    (id: string) => {
      const duration = durations.current.get(id);
      if (duration === undefined) return;
      clearTimer(id);
      timers.current.set(id, window.setTimeout(() => dismiss(id), duration));
    },
    [clearTimer, dismiss],
  );

  const toast = useCallback(
    (options: ToastOptions) => {
      const id = createId('toast');
      const duration = options.duration ?? (options.action ? 8000 : 4600);
      const record: ToastRecord = { ...options, id, duration };
      durations.current.set(id, duration);
      setToasts((current) => [...current.slice(-3), record]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), duration));
      return id;
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      dismiss,
      success: (title, description) => toast({ title, description, tone: 'success' }),
      error: (title, description) => toast({ title, description, tone: 'danger' }),
    }),
    [toast, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toasts.length > 0 &&
        createPortal(
          <div className={styles.viewport} role="region" aria-label="Уведомления">
            {toasts.map((item) => (
              <ToastCard
                key={item.id}
                item={item}
                onDismiss={dismiss}
                onHoldStart={clearTimer}
                onHoldEnd={startTimer}
              />
            ))}
          </div>,
          document.body,
        )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast должен использоваться внутри ToastProvider');
  return context;
}
