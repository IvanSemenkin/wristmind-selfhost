import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { useIsMobile } from '@/lib/hooks';
import { EmptyState, Skeleton } from './Feedback';
import styles from './Table.module.css';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** CSS width applied on desktop. */
  width?: string;
  align?: 'left' | 'right' | 'center';
  /** Hide this column below the given breakpoint (desktop table only). */
  hideBelow?: 'md' | 'lg';
  /** Label rendered next to the value in the mobile card layout. */
  mobileLabel?: ReactNode;
  /** Skip this column in the mobile card layout (it becomes the card header). */
  mobileHidden?: boolean;
  /** Marks the column that becomes the mobile card title. */
  mobilePrimary?: boolean;
  cellClassName?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Rendered at the end of each row — usually a row menu. */
  rowActions?: (row: T) => ReactNode;
  loading?: boolean;
  skeletonRows?: number;
  emptyState?: ReactNode;
  /** Accessible description of the table. */
  caption?: string;
  className?: string;
  /** Highlight a row (e.g. the currently open chat). */
  isRowActive?: (row: T) => boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  rowActions,
  loading = false,
  skeletonRows = 6,
  emptyState,
  caption,
  className,
  isRowActive,
}: DataTableProps<T>) {
  const isMobile = useIsMobile();

  if (loading) {
    return (
      <div className={cn(styles.wrap, className)}>
        <div className={styles.loadingRows} aria-busy>
          {Array.from({ length: skeletonRows }, (_, i) => (
            <div key={i} className={styles.loadingRow} style={{ opacity: 1 - i * 0.1 }}>
              <Skeleton width={`${34 + ((i * 13) % 26)}%`} height={11} />
              <Skeleton width={64} height={11} />
              <Skeleton width={48} height={11} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (rows.length === 0) {
    return <div className={cn(styles.wrap, className)}>{emptyState ?? <EmptyState title="Нет данных" />}</div>;
  }

  if (isMobile) {
    const primary = columns.find((c) => c.mobilePrimary) ?? columns[0];
    const secondary = columns.filter((c) => c !== primary && !c.mobileHidden);

    return (
      <ul className={cn(styles.cards, className)}>
        {rows.map((row) => {
          const active = isRowActive?.(row) ?? false;
          return (
            <li key={rowKey(row)} className={styles.card} data-active={active || undefined}>
              <div className={styles.cardMain}>
                <div
                  className={cn(styles.cardPrimary, onRowClick && styles.clickable)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  role={onRowClick ? 'button' : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {primary.render(row)}
                </div>
                {rowActions && <div className={styles.cardActions}>{rowActions(row)}</div>}
              </div>
              {secondary.length > 0 && (
                <dl className={styles.cardMeta}>
                  {secondary.map((column) => (
                    <div key={column.key} className={styles.cardMetaRow}>
                      {column.mobileLabel != null && (
                        <dt className={styles.cardMetaLabel}>{column.mobileLabel}</dt>
                      )}
                      <dd className={styles.cardMetaValue}>{column.render(row)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className={cn(styles.wrap, className)}>
      <table className={styles.table}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width }}
                data-align={column.align ?? 'left'}
                data-hide-below={column.hideBelow}
                className={styles.th}
              >
                {column.header}
              </th>
            ))}
            {rowActions && <th className={cn(styles.th, styles.actionsHead)} aria-label="Действия" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = isRowActive?.(row) ?? false;
            return (
              <tr
                key={rowKey(row)}
                className={styles.tr}
                data-active={active || undefined}
                data-clickable={onRowClick ? true : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    data-align={column.align ?? 'left'}
                    data-hide-below={column.hideBelow}
                    className={cn(styles.td, column.cellClassName)}
                  >
                    {column.render(row)}
                  </td>
                ))}
                {rowActions && (
                  <td
                    className={cn(styles.td, styles.actionsCell)}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {rowActions(row)}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
