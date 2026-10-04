import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import styles from './Layout.module.css';

/* -------------------------------------------------------------------------- */
/* Page scaffolding                                                           */
/* -------------------------------------------------------------------------- */

export interface PageProps {
  children: ReactNode;
  /** Narrower measure for reading-oriented screens (chat, source detail). */
  width?: 'default' | 'narrow' | 'full';
  className?: string;
}

export function Page({ children, width = 'default', className }: PageProps) {
  return (
    <div className={cn(styles.page, className)} data-width={width}>
      {children}
    </div>
  );
}

export interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  /** Small line above the title: breadcrumb or parent context. */
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  /** Secondary row below the title — tabs, filters or metrics. */
  below?: ReactNode;
  /** Leading element, e.g. a colour dot or avatar. */
  leading?: ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  description,
  breadcrumb,
  actions,
  below,
  leading,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn(styles.pageHeader, className)}>
      <div className={styles.pageHeaderRow}>
        <div className={styles.pageHeaderMain}>
          {breadcrumb && <div className={styles.breadcrumb}>{breadcrumb}</div>}
          <div className={styles.titleRow}>
            {leading}
            <h1 className={styles.pageTitle}>{title}</h1>
          </div>
          {description && <p className={styles.pageDescription}>{description}</p>}
        </div>
        {actions && <div className={styles.pageActions}>{actions}</div>}
      </div>
      {below && <div className={styles.pageBelow}>{below}</div>}
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                   */
/* -------------------------------------------------------------------------- */

export interface PanelProps {
  children: ReactNode;
  className?: string;
  /** Removes the inner padding so tables and lists can span edge to edge. */
  flush?: boolean;
  /** Adds a hover affordance; use when the whole panel is clickable. */
  interactive?: boolean;
  tone?: 'default' | 'inset';
}

export function Panel({ children, className, flush = false, interactive = false, tone = 'default' }: PanelProps) {
  return (
    <section
      className={cn(styles.panel, className)}
      data-flush={flush || undefined}
      data-interactive={interactive || undefined}
      data-tone={tone}
    >
      {children}
    </section>
  );
}

export interface PanelHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  className?: string;
  /** Removes the bottom border when the content provides its own separation. */
  borderless?: boolean;
}

export function PanelHeader({
  title,
  description,
  actions,
  icon,
  className,
  borderless = false,
}: PanelHeaderProps) {
  return (
    <header className={cn(styles.panelHeader, className)} data-borderless={borderless || undefined}>
      <div className={styles.panelHeaderText}>
        <div className={styles.panelTitleRow}>
          {icon && <span className={styles.panelIcon}>{icon}</span>}
          <h2 className={styles.panelTitle}>{title}</h2>
        </div>
        {description && <p className={styles.panelDescription}>{description}</p>}
      </div>
      {actions && <div className={styles.panelActions}>{actions}</div>}
    </header>
  );
}

export function PanelBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn(styles.panelBody, className)}>{children}</div>;
}

/* -------------------------------------------------------------------------- */
/* Toolbar                                                                    */
/* -------------------------------------------------------------------------- */

export interface ToolbarProps {
  children: ReactNode;
  className?: string;
  /** Sticks the toolbar under the top bar while the list scrolls. */
  sticky?: boolean;
}

export function Toolbar({ children, className, sticky = false }: ToolbarProps) {
  return (
    <div className={cn(styles.toolbar, className)} data-sticky={sticky || undefined}>
      {children}
    </div>
  );
}

export function ToolbarGroup({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn(styles.toolbarGroup, className)}>{children}</div>;
}

/* -------------------------------------------------------------------------- */
/* Lists & key/value                                                          */
/* -------------------------------------------------------------------------- */

export interface DefinitionItem {
  label: ReactNode;
  value: ReactNode;
  /** Span both columns on wide screens. */
  wide?: boolean;
}

export function DefinitionList({
  items,
  columns = 2,
  className,
}: {
  items: DefinitionItem[];
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  return (
    <dl className={cn(styles.defList, className)} data-columns={columns}>
      {items.map((item, index) => (
        <div key={index} className={styles.defItem} data-wide={item.wide || undefined}>
          <dt className={styles.defLabel}>{item.label}</dt>
          <dd className={styles.defValue}>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Divider({ className }: { className?: string }) {
  return <hr className={cn(styles.divider, className)} />;
}

export function SectionTitle({
  children,
  actions,
  className,
}: {
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn(styles.sectionTitle, className)}>
      <h2 className={styles.sectionTitleText}>{children}</h2>
      {actions && <div className={styles.sectionTitleActions}>{actions}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Metric                                                                     */
/* -------------------------------------------------------------------------- */

export interface MetricProps {
  label: ReactNode;
  value: ReactNode;
  /** Small qualifier under the value. */
  meta?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

/** Compact metric used inside a metrics strip — never a giant number card. */
export function Metric({ label, value, meta, icon, className }: MetricProps) {
  return (
    <div className={cn(styles.metric, className)}>
      <div className={styles.metricLabel}>
        {icon && <span className={styles.metricIcon}>{icon}</span>}
        {label}
      </div>
      <div className={styles.metricValue}>{value}</div>
      {meta && <div className={styles.metricMeta}>{meta}</div>}
    </div>
  );
}

export function MetricStrip({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn(styles.metricStrip, className)}>{children}</div>;
}
