import { useMemo } from 'react';
import { Layers } from 'lucide-react';
import { messageSourceCards, messageSourcesLabel } from '@/lib/chatSources';
import type { ChatSources, Message } from '@/types';
import styles from './MessageSources.module.css';

/* =============================================================================
   Per-answer "Источники · N" trigger.

   The panel itself lives in `ChatSourcesPanel`; this button only reports how
   many sources belong to one answer and asks the conversation to open the panel
   in per-answer mode. The count is computed with the same pure function the
   panel uses, so the number always matches what is shown.
   ========================================================================== */

export interface MessageSourcesProps {
  message: Message;
  /** Chat-scoped index used to resolve working titles named by the answer. */
  chatSources: ChatSources | null;
  onOpen: (messageId: string) => void;
}

export function MessageSources({ message, chatSources, onOpen }: MessageSourcesProps) {
  const cards = useMemo(
    () => messageSourceCards(message, chatSources),
    [message, chatSources],
  );
  const count = cards.length;

  if (count === 0) return null;

  return (
    <button
      type="button" className={styles.trigger}
      onClick={() => onOpen(message.id)}
      aria-haspopup="dialog"
    >
      <Layers aria-hidden />
      <span>{messageSourcesLabel(message, cards)}</span>
      <span className={styles.triggerCount}>· {count}</span>
    </button>
  );
}
