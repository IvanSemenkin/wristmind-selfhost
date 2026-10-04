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

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<string, number>());

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const toast = useCallback(
    (options: ToastOptions) => {
      const id = createId('toast');
      const record: ToastRecord = {
        ...options,
        id,
        duration: options.duration ?? (options.action ? 8000 : 4600),
      };
      setToasts((current) => [...current.slice(-3), record]);
      const timer = window.setTimeout(() => dismiss(id), record.duration);
      timers.current.set(id, timer);
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
              <div
                key={item.id}
                className={styles.toast}
                data-tone={item.tone ?? 'default'}
                role="status"
                aria-live="polite"
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
                        dismiss(item.id);
                      }}
                    >
                      {item.action.label}
                    </button>
                  )}
                </div>
                <IconButton
                  label="Закрыть" size="xs" icon={<X />}
                  className={cn(styles.close)}
                  onClick={() => dismiss(item.id)}
                />
              </div>
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
