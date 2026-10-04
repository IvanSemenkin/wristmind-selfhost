import type { ComponentPropsWithRef, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import styles from './Feedback.module.css';

/* -------------------------------------------------------------------------- */
/* Spinner                                                                    */
/* -------------------------------------------------------------------------- */

export interface SpinnerProps {
  size?: number;
  className?: string;
  label?: string;
}

export function Spinner({ size = 14, className, label }: SpinnerProps) {
  return (
    <span
      className={cn(styles.spinner, className)}
      style={{ width: size, height: size }}
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Skeletons                                                                  */
/* -------------------------------------------------------------------------- */

export interface SkeletonProps extends ComponentPropsWithRef<'div'> {
  width?: string | number;
  height?: string | number;
  radius?: string | number;
}

export function Skeleton({ width, height = 10, radius, className, style, ...rest }: SkeletonProps) {
  return (
    <div
      {...rest}
      aria-hidden
      className={cn(styles.skeleton, className)}
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

/** Skeleton shaped like the list rows used across chats, sources and devices. */
export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn(styles.skeletonRows, className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skeletonRow} style={{ opacity: 1 - i * 0.12 }}>
          <Skeleton width={i % 3 === 0 ? '38%' : i % 3 === 1 ? '26%' : '31%'} height={11} />
          <Skeleton width={i % 2 === 0 ? '18%' : '12%'} height={11} />
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Progress                                                                   */
/* -------------------------------------------------------------------------- */

export interface ProgressProps {
  /** 0…1 */
  value: number;
  size?: 'sm' | 'md';
  tone?: 'accent' | 'success' | 'danger';
  className?: string;
  label?: string;
}

export function Progress({ value, size = 'sm', tone = 'accent', className, label }: ProgressProps) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div
      className={cn(styles.progress, className)}
      data-size={size}
      data-tone={tone}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={styles.progressFill} style={{ width: `${pct}%` }} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Status                                                                     */
/* -------------------------------------------------------------------------- */

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface StatusDotProps {
  tone?: Tone;
  /** Adds a soft pulse — reserved for genuinely live states. */
  pulse?: boolean;
  className?: string;
}

export function StatusDot({ tone = 'neutral', pulse = false, className }: StatusDotProps) {
  return <span className={cn(styles.dot, className)} data-tone={tone} data-pulse={pulse || undefined} />;
}

export interface BadgeProps extends ComponentPropsWithRef<'span'> {
  tone?: Tone;
  variant?: 'soft' | 'outline';
  icon?: ReactNode;
  size?: 'sm' | 'md';
  /** Render a leading status dot. */
  dot?: boolean;
}

export function Badge({
  tone = 'neutral',
  variant = 'soft',
  icon,
  size = 'md',
  dot = false,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      {...rest}
      className={cn(styles.badge, className)}
      data-tone={tone}
      data-variant={variant}
      data-size={size}
    >
      {dot && <StatusDot tone={tone} />}
      {icon && <span className={styles.badgeIcon}>{icon}</span>}
      {children}
    </span>
  );
}

export interface KbdProps {
  children: ReactNode;
  className?: string;
}

export function Kbd({ children, className }: KbdProps) {
  return <kbd className={cn(styles.kbd, className)}>{children}</kbd>;
}

/* -------------------------------------------------------------------------- */
/* Empty state                                                                */
/* -------------------------------------------------------------------------- */

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  /** Compact variant for inside panels and side columns. */
  compact?: boolean;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div className={cn(styles.empty, className)} data-compact={compact || undefined}>
      {icon && <div className={styles.emptyIcon}>{icon}</div>}
      <div className={styles.emptyTitle}>{title}</div>
      {description && <p className={styles.emptyText}>{description}</p>}
      {(action || secondaryAction) && (
        <div className={styles.emptyActions}>
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Inline banner                                                              */
/* -------------------------------------------------------------------------- */

export interface BannerProps {
  tone?: Tone;
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function Banner({ tone = 'neutral', icon, title, children, action, className }: BannerProps) {
  return (
    <div className={cn(styles.banner, className)} data-tone={tone} role="status">
      {icon && <span className={styles.bannerIcon}>{icon}</span>}
      <div className={styles.bannerBody}>
        {title && <div className={styles.bannerTitle}>{title}</div>}
        {children && <div className={styles.bannerText}>{children}</div>}
      </div>
      {action && <div className={styles.bannerAction}>{action}</div>}
    </div>
  );
}
