import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Square, Telescope } from 'lucide-react';
import type { ReactNode } from 'react';
import styles from './Chats.module.css';
import { VoiceDictation } from './VoiceDictation';

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
  onSend: (text: string) => void | Promise<void | boolean>;
  draftKey?: string;
  recoveryText?: string;
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
  draftKey,
  recoveryText,
  onStop,
  streaming,
  researchMode,
  onResearchModeToggle,
  placeholder = 'Спросите что-нибудь…',
  autoFocus = false,
}: ComposerProps) {
  const [value, setValue] = useState(() => {
    try { return draftKey ? sessionStorage.getItem(`wristmind.draft.${draftKey}`) ?? '' : ''; } catch { return ''; }
  });
  useEffect(() => {
    if (!draftKey) return;
    try {
      if (value) sessionStorage.setItem(`wristmind.draft.${draftKey}`, value);
      else sessionStorage.removeItem(`wristmind.draft.${draftKey}`);
    } catch { /* Storage may be unavailable; editing remains usable. */ }
  }, [value, draftKey]);
  useEffect(() => { if (recoveryText) setValue(previous => previous || recoveryText); }, [recoveryText]);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sending = useRef(false);

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const dispatch = (text: string) => {
    if (sending.current || streaming) return;
    sending.current = true;
    setValue('');
    if (window.matchMedia('(max-width: 860px)').matches) textareaRef.current?.blur();
    else requestAnimationFrame(() => textareaRef.current?.focus());
    void Promise.resolve().then(() => onSend(text)).then(result => {
      if (result === false) setValue(previous => previous || text);
    }).catch(() => setValue(previous => previous || text)).finally(() => { sending.current = false; });
  };

  const submit = () => {
    const text = value.trim();
    if (!text || streaming || voiceBusy) return;
    dispatch(text);
    requestAnimationFrame(() => {
      const node = textareaRef.current;
      if (node) {
        node.style.height = 'auto';
      }
    });
  };

  return (
    <div className={styles.composer}>
      <div className={styles.composerBox} data-streaming={streaming || undefined} data-voice-busy={voiceBusy || undefined}>
        <textarea
          ref={textareaRef}
          className={styles.composerInput}
          value={value}
          rows={1}
          aria-label="Сообщение"
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          disabled={voiceBusy}
        />
        <div className={styles.composerBar}>
          <div className={styles.composerTools}>
            {!voiceBusy && <ToggleChip
              on={researchMode}
              label="Исследование" offLabel="Исследование" icon={<Telescope />}
              title={
                researchMode
                  ? 'Исследование — более глубокая проверка и доработка ответа'
                  : 'Авто — система сама выберет поиск и глубину ответа'
              }
              onToggle={() => onResearchModeToggle(!researchMode)}
            />}
          </div>
          <div className={styles.composerActions}>
            <VoiceDictation disabled={streaming} onBusy={setVoiceBusy} onError={setVoiceError} onSend={(text) => {
              const message = `${value.trimEnd()}${value.trim() ? ' ' : ''}${text}`.trim();
              if (!message || streaming) return;
              dispatch(message);
            }} onText={(text) => {
              setValue((previous) => `${previous.trimEnd()}${previous.trim() ? ' ' : ''}${text}`);
              requestAnimationFrame(() => textareaRef.current?.focus());
            }} />
            {streaming ? (
              <button type="button" className={styles.sendButton} onClick={onStop} aria-label="Остановить генерацию" title="Остановить генерацию"><Square /></button>
            ) : !voiceBusy && (
              <button type="button" className={styles.sendButton} onClick={submit} disabled={value.trim().length === 0} aria-label="Отправить сообщение" title="Отправить сообщение"><ArrowUp /></button>
            )}
          </div>
        </div>
        {voiceError && <div className={styles.dictationError} role="alert">{voiceError}</div>}
      </div>
    </div>
  );
}
