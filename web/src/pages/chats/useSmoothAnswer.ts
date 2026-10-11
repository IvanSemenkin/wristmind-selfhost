import { useEffect, useRef, useState } from 'react';

/** A short bounded reveal buffer absorbs uneven token batches without delaying completion. */
export function useSmoothAnswer(content: string, streaming: boolean) {
  const [visible, setVisible] = useState(streaming ? '' : content);
  const target = useRef(content); target.current = content;
  useEffect(() => {
    if (!streaming || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(target.current); return;
    }
    let frame = 0;
    let last = 0;
    const tick = (now: number) => {
      if (now - last >= 50) {
        last = now;
        setVisible((current) => {
          const next = target.current;
          if (!next.startsWith(current)) return next;
          const count = Math.max(6, Math.ceil((next.length - current.length) / 2));
          let end = Math.min(next.length, current.length + count);
          // Never split an emoji's UTF-16 pair.
          if (end < next.length && /[\uD800-\uDBFF]/.test(next[end - 1])) end++;
          return next.slice(0, end);
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [streaming]);
  return streaming ? visible : content;
}
