import { Check } from 'lucide-react';
import { MESSAGE_PHASE_LABELS, type MessagePhase } from '@/types';
import { cn } from '@/lib/cn';
import { Spinner } from '@/components';
import styles from './Chats.module.css';

export interface ProcessingTimelineProps {
  /** Phase the request is currently in, or `null` once it finished. */
  current: MessagePhase | null;
  /** Phases this request goes through, in order. */
  phases: MessagePhase[];
  className?: string;
}

/**
 * Shows the pipeline the backend reports while an answer is produced. Phases
 * resolve in order, so the user can see where the request currently is.
 */
export function ProcessingTimeline({ current, phases, className }: ProcessingTimelineProps) {
  const activeIndex = current ? phases.indexOf(current) : -1;

  return (
    <ol className={cn(styles.timeline, className)} aria-label="Этапы обработки">
      {phases.map((phase, index) => {
        const state = index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending';
        const meta = MESSAGE_PHASE_LABELS[phase];
        return (
          <li key={phase} className={styles.timelineItem} data-state={state}>
            <span className={styles.timelineMarker}>
              {state === 'done' ? <Check /> : state === 'active' ? <Spinner size={10} /> : null}
            </span>
            <span className={styles.timelineText}>
              <span className={styles.timelineLabel}>{meta.label}</span>
              {state === 'active' && (
                <span className={styles.timelineDescription}>{meta.description}</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Single-line status shown in the message header while streaming. */
export function StageInlineLabel({ phase }: { phase: MessagePhase | null }) {
  if (!phase) return <span className={styles.streamingLabel}>Обработка…</span>;
  return (
    <span className={styles.streamingLabel}>
      <Spinner size={10} />
      {MESSAGE_PHASE_LABELS[phase].label}
    </span>
  );
}
