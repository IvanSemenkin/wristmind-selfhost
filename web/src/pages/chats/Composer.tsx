import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Square, Telescope } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button, Kbd } from '@/components';
import styles from './Chats.module.css';

/** Compact on/off control used for the request options next to the input. */
function ToggleChip({
  on,
  label,
  offLabel,
  icon,
  onToggle,
  title,
  disabled = false,
}: {
  on: boolean;
  label: string;
  offLabel: string;
  icon: ReactNode;
  onToggle: () => void;
  title: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button" className={styles.chip}
      data-on={on || undefined}
      aria-pressed={on}
      aria-label={title}
      title={title}
      disabled={disabled}
      onClick={onToggle}
    >
      {icon}
      <span className={styles.chipLabel}>{on ? label : offLabel}</span>
    </button>
  );
}

export interface ComposerProps {
  onSend: (text: string) => void;
  onStop?: () => void;
  streaming: boolean;
  /**
   * The single request mode: off is AUTO, on is RESEARCH. Retrieval itself is
   * decided by the backend Router in both modes.
   */
  researchMode: boolean;
  onResearchModeToggle: (value: boolean) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

const MAX_HEIGHT = 200;

export function Composer({
  onSend,
  onStop,
  streaming,
  researchMode,
  onResearchModeToggle,
  placeholder = 'Спросите что-нибудь…',
  autoFocus = false,
}: ComposerProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const submit = () => {
    const text = value.trim();
    if (!text || streaming) return;
    onSend(text);
    setValue('');
    requestAnimationFrame(() => {
      const node = textareaRef.current;
      if (node) {
        node.style.height = 'auto';
        node.focus();
      }
    });
  };

  return (
    <div className={styles.composer}>
      <div className={styles.composerBox} data-streaming={streaming || undefined}>
        <textarea
          ref={textareaRef}
          className={styles.composerInput}
          value={value}
          rows={1}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          disabled={streaming}
        />
        <div className={styles.composerBar}>
          <div className={styles.composerTools}>
            <ToggleChip
              on={researchMode}
              label="Исследование" offLabel="Авто" icon={<Telescope />}
              title={
                researchMode
                  ? 'Исследование — более глубокая проверка и доработка ответа'
                  : 'Авто — система сама выберет поиск и глубину ответа'
              }
              onToggle={() => onResearchModeToggle(!researchMode)}
            />
          </div>
          <div className={styles.composerActions}>
            <span className={styles.composerHint}>
              <Kbd>↵</Kbd> отправить · <Kbd>⇧↵</Kbd> перенос
            </span>
            {streaming ? (
              <Button
                size="sm" variant="secondary" iconLeft={<Square />}
                onClick={onStop}
                aria-label="Остановить генерацию"
              >
                Стоп
              </Button>
            ) : (
              <Button
                size="sm" variant="primary" iconLeft={<ArrowUp />}
                onClick={submit}
                disabled={value.trim().length === 0}
                aria-label="Отправить сообщение"
              >
                Отправить
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
