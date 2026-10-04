import { useEffect, useMemo, useState } from 'react';
import { Check, Copy, RefreshCw, Smartphone, Watch, Wifi } from 'lucide-react';
import { describeError, useActions } from '@/services';
import { usePairingCodes } from '@/store';
import { isPairingCodeActive, type DeviceKind, type PairingCode } from '@/types';
import { cn } from '@/lib/cn';
import { formatCountdown } from '@/lib/format';
import { useCopyToClipboard, useInterval } from '@/lib/hooks';
import { Button, Modal, SegmentedControl, useToast } from '@/components';
import styles from './Devices.module.css';

type Target = 'ANY' | DeviceKind;

/** Pairing UI: the backend issues a single-use code that lives for 10 minutes. */
export function PairingCodeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const actions = useActions();
  const toast = useToast();
  const codes = usePairingCodes();
  const [target, setTarget] = useState<Target>('ANY');
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [copied, copy] = useCopyToClipboard();

  useInterval(() => setNow(Date.now()), open ? 1000 : null);

  const active: PairingCode | undefined = useMemo(
    () => codes.find((code) => isPairingCodeActive(code, now)),
    [codes, now],
  );

  // Issue a code as soon as the dialog opens without a live one.
  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const hasLive = codes.some((code) => isPairingCodeActive(code));
    if (hasLive) return;
    setGenerationError(null);
    setGenerating(true);
    actions
      .createPairingCode(null)
      .catch((error) => {
        const message = describeError(error, 'Не удалось получить код');
        setGenerationError(message);
        toast.error('Не удалось получить код', 'Нажмите «Повторить»: уже созданный код не потеряется.');
      })
      .finally(() => setGenerating(false));
    // Intentionally only on open: regenerating on every code change would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const secondsLeft = active
    ? Math.max(0, Math.floor((new Date(active.expires_at).getTime() - now) / 1000))
    : 0;

  const generate = async () => {
    setGenerationError(null);
    setGenerating(true);
    try {
      const previousCode = active?.code;
      const created = await actions.createPairingCode(target === 'ANY' ? null : target);
      if (previousCode && previousCode !== created.code) await actions.revokePairingCode(previousCode);
    } catch (error) {
      const message = describeError(error, 'Не удалось получить код подключения');
      setGenerationError(message);
      toast.error('Не удалось получить код', 'При повторе панель восстановит тот же код, если сервер уже успел его создать.');
    } finally {
      setGenerating(false);
    }
  };

  const digits = active ? active.code.split('') : ['—', '—', '—', '—', '—', '—'];

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm" title="Подключение устройства" description="Одноразовый код действует 10 минут и срабатывает только один раз." footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
          <Button
            variant="primary" iconLeft={<RefreshCw />}
            onClick={generate}
            loading={generating}
          >
            {generationError && !active ? 'Повторить' : active ? 'Новый код' : 'Сгенерировать код'}
          </Button>
        </>
      }
    >
      <div className={styles.pairing}>
        <div className={styles.pairingTarget}>
          <SegmentedControl<Target>
            value={target}
            onChange={setTarget}
            aria-label="Тип устройства" options={[
              { value: 'ANY', label: 'Любое', icon: <Wifi /> },
              { value: 'PHONE', label: 'Телефон', icon: <Smartphone /> },
              { value: 'WATCH', label: 'Часы', icon: <Watch /> },
            ]}
          />
        </div>

        <div
          className={styles.codeBox}
          data-expired={secondsLeft === 0 || undefined}
          aria-busy={generating}
        >
          <div
            className={styles.codeDigits}
            aria-label={`Код подключения ${active?.code ?? 'не создан'}`}
          >
            {digits.map((digit, index) => (
              <span key={index} className={styles.codeDigit}>
                {digit}
              </span>
            ))}
          </div>
          <div className={styles.codeTimer}>
            {active ? (
              <>
                <span className={styles.timerValue}>{formatCountdown(secondsLeft)}</span>
                <span className={styles.timerLabel}>до истечения кода</span>
              </>
            ) : (
              <span className={styles.timerLabel}>Код не создан</span>
            )}
          </div>
          <div className={styles.codeActions}>
            <Button
              size="sm" variant="secondary" iconLeft={copied ? <Check /> : <Copy />}
              disabled={!active}
              onClick={() => active && void copy(active.code)}
            >
              {copied ? 'Скопировано' : 'Скопировать код'}
            </Button>
          </div>
          {generationError && (
            <p className={styles.pairingError} role="alert">
              {generationError}. Повторите запрос — новый код не будет создан второй раз.
            </p>
          )}
        </div>

        <ol className={styles.steps}>
          <li>
            <span className={styles.stepNumber}>1</span>
            Откройте WristMind на телефоне или часах.
          </li>
          <li>
            <span className={styles.stepNumber}>2</span>
            Выберите «Подключить к панели» и введите код.
          </li>
          <li>
            <span className={styles.stepNumber}>3</span>
            Устройство появится в списке ниже сразу после подтверждения.
          </li>
        </ol>

        {target !== 'ANY' && (
          <p className={styles.pairingNote}>
            Код выпущен для устройства типа «{target === 'PHONE' ? 'телефон' : 'часы'}».
            Устройство другого типа его не примет.
          </p>
        )}
      </div>
    </Modal>
  );
}

export function CodeCountdown({ expiresAt, className }: { expiresAt: string; className?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useInterval(() => setNow(Date.now()), 1000);
  const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000));
  return (
    <span className={cn(styles.countdown, className)} data-expired={seconds === 0 || undefined}>
      {formatCountdown(seconds)}
    </span>
  );
}
