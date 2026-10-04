import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from './Button';
import { Input } from './Field';
import { Modal } from './Modal';
import styles from './ConfirmDialog.module.css';

export interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  /** Extra context shown above the confirmation phrase (counts, names, impact). */
  details?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'default';
  /** When set, the user must type this exact string to enable confirmation. */
  confirmPhrase?: string;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((options) => {
    setRequest(options);
    setTyped('');
    setBusy(false);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const settle = (value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setRequest(null);
  };

  const value = useMemo(() => confirm, [confirm]);

  const phraseOk = !request?.confirmPhrase || typed.trim() === request.confirmPhrase;
  const danger = request?.tone !== 'default';

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Modal
        open={request !== null}
        onClose={() => settle(false)}
        size="sm" title={request?.title}
        eyebrow={
          danger ? (
            <span className={styles.eyebrow}>
              <AlertTriangle /> Необратимое действие
            </span>
          ) : undefined
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => settle(false)} disabled={busy}>
              {request?.cancelLabel ?? 'Отмена'}
            </Button>
            <Button
              variant={danger ? 'danger' : 'primary'}
              disabled={!phraseOk || busy}
              loading={busy}
              onClick={() => {
                setBusy(true);
                settle(true);
              }}
            >
              {request?.confirmLabel ?? 'Удалить'}
            </Button>
          </>
        }
      >
        <div className={styles.content}>
          {request?.description && <p className={styles.description}>{request.description}</p>}
          {request?.details && <div className={styles.details}>{request.details}</div>}
          {request?.confirmPhrase && (
            <div className={styles.phrase}>
              <label className={styles.phraseLabel} htmlFor="confirm-phrase">
                Введите <code>{request.confirmPhrase}</code> для подтверждения
              </label>
              <Input
                id="confirm-phrase" value={typed}
                autoComplete="off" spellCheck={false}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={request.confirmPhrase}
                invalid={typed.length > 0 && !phraseOk}
              />
            </div>
          )}
        </div>
      </Modal>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('useConfirm должен использоваться внутри ConfirmProvider');
  return context;
}
