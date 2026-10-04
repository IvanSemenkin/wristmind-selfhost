import { useState } from 'react';
import type { ActivityPoint } from '@/types';
import { cn } from '@/lib/cn';
import { formatNumber } from '@/lib/format';
import styles from './Chart.module.css';

/* -------------------------------------------------------------------------- */
/* Activity chart                                                             */
/* -------------------------------------------------------------------------- */

export interface ActivityChartProps {
  points: ActivityPoint[];
  height?: number;
  className?: string;
}

/** 14-day request volume with the error share layered on top of each bar. */
export function ActivityChart({ points, height = 132, className }: ActivityChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  const max = Math.max(1, ...points.map((p) => p.requests));
  const total = points.reduce((sum, p) => sum + p.requests, 0);
  const errors = points.reduce((sum, p) => sum + p.errors, 0);
  const active = hovered != null ? points[hovered] : null;

  const dayLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' });
  const fullLabel = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    weekday: 'short',
  });

  return (
    <div className={cn(styles.chart, className)}>
      <div className={styles.chartHead}>
        <div className={styles.chartSummary}>
          {active ? (
            <>
              <span className={styles.chartSummaryValue}>{formatNumber(active.requests)}</span>
              <span className={styles.chartSummaryLabel}>
                {fullLabel.format(new Date(active.bucket))} ·{' '}
                {active.errors > 0 ? `${formatNumber(active.errors)} с ошибкой` : 'без ошибок'}
              </span>
            </>
          ) : (
            <>
              <span className={styles.chartSummaryValue}>{formatNumber(total)}</span>
              <span className={styles.chartSummaryLabel}>
                запросов за 14 дней · {formatNumber(errors)} с ошибкой
              </span>
            </>
          )}
        </div>
        <div className={styles.legend}>
          <span className={styles.legendItem}>
            <span className={styles.legendSwatch} data-kind="ok" /> Запросы
          </span>
          <span className={styles.legendItem}>
            <span className={styles.legendSwatch} data-kind="error" /> Ошибки
          </span>
        </div>
      </div>

      <div className={styles.plot} style={{ height }}>
        <div className={styles.gridLines} aria-hidden>
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className={styles.bars} onMouseLeave={() => setHovered(null)}>
          {points.map((point, index) => {
            const ratio = point.requests / max;
            const errorRatio = point.requests > 0 ? point.errors / point.requests : 0;
            return (
              <button
                key={point.bucket}
                type="button" className={styles.bar}
                data-active={hovered === index || undefined}
                onMouseEnter={() => setHovered(index)}
                onFocus={() => setHovered(index)}
                onBlur={() => setHovered(null)}
                aria-label={`${dayLabel.format(new Date(point.bucket))}: ${point.requests} запросов, ${point.errors} с ошибкой`}
              >
                <span className={styles.barTrack}>
                  <span className={styles.barFill} style={{ height: `${Math.max(3, ratio * 100)}%` }}>
                    {errorRatio > 0 && (
                      <span
                        className={styles.barErrors}
                        style={{ height: `${Math.max(4, errorRatio * 100)}%` }}
                      />
                    )}
                  </span>
                </span>
                <span className={styles.barLabel}>
                  {index % 3 === 0 || index === points.length - 1
                    ? dayLabel.format(new Date(point.bucket)).replace('.', '')
                    : ''}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Ranked bars                                                                */
/* -------------------------------------------------------------------------- */

export interface RankedBarItem {
  id: string;
  label: string;
  value: number;
  display: string;
  meta?: string;
  color?: string;
}

export function RankedBars({
  items,
  className,
}: {
  items: RankedBarItem[];
  className?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className={cn(styles.ranked, className)}>
      {items.map((item) => (
        <li key={item.id} className={styles.rankedRow}>
          <div className={styles.rankedHead}>
            <span className={styles.rankedLabel} title={item.label}>
              {item.color && (
                <span className={styles.rankedDot} style={{ background: item.color }} aria-hidden />
              )}
              {item.label}
            </span>
            <span className={styles.rankedValue}>{item.display}</span>
          </div>
          <div className={styles.rankedTrack}>
            <span
              className={styles.rankedFill}
              style={{
                width: `${Math.max(2, (item.value / max) * 100)}%`,
                background: item.color ?? 'var(--accent)',
              }}
            />
          </div>
          {item.meta && <span className={styles.rankedMeta}>{item.meta}</span>}
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/* Sparkline                                                                  */
/* -------------------------------------------------------------------------- */

export function Sparkline({
  values,
  width = 72,
  height = 22,
  tone = 'accent',
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  tone?: 'accent' | 'success' | 'danger';
  className?: string;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values
    .map((value, i) => `${(i * stepX).toFixed(1)},${(height - ((value - min) / span) * (height - 4) - 2).toFixed(1)}`)
    .join(' ');

  return (
    <svg
      className={cn(styles.sparkline, className)}
      data-tone={tone}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      aria-hidden
    >
      <polyline points={points} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
