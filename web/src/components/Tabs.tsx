import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { useIsMobile } from '@/lib/hooks';
import styles from './Tabs.module.css';

export interface TabItem<T extends string> {
  id: T;
  label: string;
  /** Used below the mobile breakpoint to keep the tab strip on one screen. */
  shortLabel?: string;
  icon?: ReactNode;
  /** Trailing counter, e.g. number of chats or sources. */
  count?: number;
  disabled?: boolean;
}

export interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  /** Renders a bottom border across the full width. */
  bordered?: boolean;
  'aria-label'?: string;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
  bordered = true,
  'aria-label': ariaLabel,
}: TabsProps<T>) {
  const isMobile = useIsMobile();

  return (
    <div className={cn(styles.tabs, className)} data-bordered={bordered || undefined} role="tablist" aria-label={ariaLabel}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button" role="tab"
          aria-selected={item.id === value}
          disabled={item.disabled}
          data-active={item.id === value || undefined}
          className={styles.tab}
          onClick={() => onChange(item.id)}
        >
          {item.icon && <span className={styles.tabIcon}>{item.icon}</span>}
          <span className={styles.tabLabel}>
            {isMobile ? (item.shortLabel ?? item.label) : item.label}
          </span>
          {item.count != null && <span className={styles.tabCount}>{item.count}</span>}
        </button>
      ))}
    </div>
  );
}
