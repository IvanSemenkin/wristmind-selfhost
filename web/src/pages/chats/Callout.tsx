import { memo, useLayoutEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { CircleAlert, Lightbulb, CircleX, BookOpen, CircleCheck, Info, ChevronDown, ChevronUp } from 'lucide-react';
import type { CalloutKind } from '@/lib/richText';
import styles from './Callout.module.css';

const types = {
  important: { label: 'Важно', icon: CircleAlert },
  tip: { label: 'Подсказка', icon: Lightbulb },
  error: { label: 'Ошибка', icon: CircleX },
  example: { label: 'Пример', icon: BookOpen },
  answer: { label: 'Ответ', icon: CircleCheck },
  info: { label: 'Информация', icon: Info },
};

export const Callout = memo(function Callout({ kind, title, children, streaming = false }: {
  kind: CalloutKind; title?: ReactNode; children: ReactNode; streaming?: boolean;
}) {
  const { label, icon: Icon } = types[kind];
  const body = useRef<HTMLDivElement>(null);
  const bodyId = useId();
  const [long, setLong] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const hidden = long && collapsed && !streaming;
  useLayoutEffect(() => {
    const node = body.current;
    if (!node || hidden) return;
    const measure = () => setLong(node.scrollHeight > 220);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [hidden, children]);
  return <aside className={styles.callout} data-kind={kind} aria-label={label}>
    <div className={styles.header}>
      <Icon className={styles.icon} size={16} aria-hidden="true" />
      <span className={styles.label}>{label}</span>
      {title && <><span className={styles.separator} aria-hidden="true">·</span><span className={styles.title}>{title}</span></>}
    </div>
    <div ref={body} id={bodyId} className={styles.body} hidden={hidden}>{children}</div>
    {long && !streaming && <button type="button" className={styles.toggle}
      aria-expanded={!hidden} aria-controls={bodyId} onClick={() => setCollapsed(value => !value)}>
      {hidden ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronUp size={16} aria-hidden="true" />}
      {hidden ? 'Развернуть объяснение' : 'Свернуть объяснение'}
    </button>}
  </aside>;
});
