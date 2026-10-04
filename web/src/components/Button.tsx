import type { ComponentPropsWithRef, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Spinner } from './Feedback';
import { useInsideTooltip } from './Tooltip';
import styles from './Button.module.css';

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'dangerGhost'
  | 'accentSoft';
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';

export interface ButtonProps extends ComponentPropsWithRef<'button'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
  /** Stretch to the container width. */
  block?: boolean;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  iconLeft,
  iconRight,
  block = false,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled || loading}
      data-variant={variant}
      data-size={size}
      data-block={block || undefined}
      data-loading={loading || undefined}
      className={cn(styles.button, className)}
    >
      {loading ? (
        <Spinner size={size === 'lg' || size === 'md' ? 13 : 11} className={styles.spinner} />
      ) : (
        iconLeft && <span className={styles.icon}>{iconLeft}</span>
      )}
      {children != null && <span className={styles.label}>{children}</span>}
      {iconRight && !loading && <span className={styles.icon}>{iconRight}</span>}
    </button>
  );
}

export interface IconButtonProps extends ComponentPropsWithRef<'button'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  /** Required: icon-only controls need an accessible name. */
  label: string;
  icon: ReactNode;
  /** Show a subtle background by default instead of only on hover. */
  outlined?: boolean;
}

export function IconButton({
  variant = 'ghost',
  size = 'md',
  loading = false,
  label,
  icon,
  outlined = false,
  className,
  disabled,
  type = 'button',
  ...rest
}: IconButtonProps) {
  // When wrapped in <Tooltip> the custom bubble is the visual hint; a native
  // `title` on top of it would show a second, unstyleable tooltip.
  const describedByTooltip = useInsideTooltip();

  return (
    <button
      {...rest}
      type={type}
      aria-label={label}
      title={describedByTooltip ? undefined : label}
      disabled={disabled || loading}
      data-variant={variant}
      data-size={size}
      data-outlined={outlined || undefined}
      className={cn(styles.button, styles.iconOnly, className)}
    >
      {loading ? <Spinner size={13} /> : <span className={styles.icon}>{icon}</span>}
    </button>
  );
}
