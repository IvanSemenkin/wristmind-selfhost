import type { ReactNode } from 'react';
import { Link, useNavigate } from '@/app/router';
import {
  BookOpen,
  ExternalLink,
  Eye,
  FileImage,
  FileText,
  MoreHorizontal,
  RefreshCw,
  ScanLine,
  Trash2,
  Upload,
} from 'lucide-react';
import type { JobStatus, KnowledgeSource } from '@/types';
import { PROCESSING_MODE_LABELS, sourceKind } from '@/types';
import { formatNumber, formatRelativeTime } from '@/lib/format';
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  IconButton,
  Menu,
  Progress,
} from '@/components';
import type { Column } from '@/components';
import { SourceStatusBadge } from '@/components/Entities';
import styles from './Knowledge.module.css';

export interface SourcesTableProps {
  sources: KnowledgeSource[];
  modeName: (modeId: string) => string | undefined;
  modeColor: (modeId: string) => string | undefined;
  /** Hide the mode column when the view is already scoped to one mode. */
  showMode?: boolean;
  onReprocess: (source: KnowledgeSource) => void;
  onDelete: (source: KnowledgeSource) => void;
  emptyState?: ReactNode;
}

export const sourceKindLabel = (source: KnowledgeSource): string =>
  sourceKind(source.media_type, source.filename) === 'image' ? 'Изображение' : 'PDF';

/** Sources may omit `updated_at`; fall back to the upload time. */
export const sourceTimestamp = (source: KnowledgeSource): string =>
  source.updated_at ?? source.created_at;

export function SourcesTable({
  sources,
  modeName,
  modeColor,
  showMode = true,
  onReprocess,
  onDelete,
  emptyState,
}: SourcesTableProps) {
  const navigate = useNavigate();

  const columns: Column<KnowledgeSource>[] = [
    {
      key: 'title',
      header: 'Источник',
      mobilePrimary: true,
      width: '32%',
      render: (source) => {
        const kind = sourceKind(source.media_type, source.filename);
        return (
          <div className={styles.sourceCell}>
            <span className={styles.sourceIcon} data-kind={kind}>
              {kind === 'image' ? <FileImage /> : <FileText />}
            </span>
            <span className={styles.sourceText}>
              <Link to={`/knowledge/sources/${source.id}`} className={styles.sourceTitle}>
                {source.title}
              </Link>
              <span className={styles.sourceFile} title={source.filename}>
                {source.filename}
              </span>
            </span>
          </div>
        );
      },
    },
    {
      key: 'status',
      header: 'Статус',
      width: '150px',
      mobileLabel: 'Статус',
      render: (source) =>
        source.status === 'processing' || source.status === 'uploading' ? (
          <div className={styles.progressCell}>
            <SourceStatusBadge status={source.status} />
            <Progress value={source.progress ?? 0} />
            <span className={styles.progressStage}>{source.stage ?? 'В очереди'}</span>
          </div>
        ) : (
          <SourceStatusBadge status={source.status} />
        ),
    },
    ...(showMode
      ? [
          {
            key: 'mode',
            header: 'Режим',
            width: '16%',
            mobileLabel: 'Режим',
            render: (source: KnowledgeSource) => (
              <span className={styles.modeCell} data-mode-color={modeColor(source.mode_id)}>
                <span className={styles.modeCellDot} />
                <span className={styles.modeCellName}>{modeName(source.mode_id) ?? '—'}</span>
              </span>
            ),
          },
        ]
      : []),
    {
      key: 'method',
      header: 'Обработка',
      width: '110px',
      hideBelow: 'lg',
      mobileLabel: 'Обработка',
      render: (source) =>
        source.status === 'error' ? (
          <span className={styles.muted}>—</span>
        ) : (
          <Badge
            tone="neutral" size="sm" icon={source.processing_mode === 'VISION' ? <Eye /> : <ScanLine />}
          >
            {PROCESSING_MODE_LABELS[source.processing_mode]}
          </Badge>
        ),
    },
    {
      key: 'stats',
      header: 'Объём',
      width: '150px',
      hideBelow: 'md',
      mobileLabel: 'Объём',
      render: (source) =>
        source.status === 'ready' ? (
          <span className={styles.volume}>
            {source.page_count} стр. · {formatNumber(source.chunk_count)} фрагм.
          </span>
        ) : source.status === 'error' ? (
          <span className={styles.muted}>не обработан</span>
        ) : (
          <span className={styles.muted}>обрабатывается…</span>
        ),
    },
    {
      key: 'updated',
      header: 'Обновлён',
      width: '130px',
      hideBelow: 'lg',
      align: 'right',
      mobileLabel: 'Обновлён',
      render: (source) => (
        <span className={styles.time}>{formatRelativeTime(sourceTimestamp(source))}</span>
      ),
    },
  ];

  const empty = emptyState ?? (
    <EmptyState
      icon={<BookOpen />}
      title="Источников нет" description="Загрузите PDF или изображение — документ попадёт в базу знаний выбранного режима."
    />
  );

  return (
    <DataTable
      columns={columns}
      rows={sources}
      rowKey={(source) => source.id}
      emptyState={empty}
      rowActions={(source) => (
        <Menu
          align="end" width={240}
          header={
            <div className={styles.menuHeader}>
              <div className={styles.menuHeaderTitle}>{source.title}</div>
              <div className={styles.menuHeaderMeta}>
                {sourceKindLabel(source)} ·{' '}
                {source.status === 'ready' ? `${source.page_count} стр.` : 'не обработан'}
              </div>
            </div>
          }
          entries={[
            {
              type: 'item',
              id: 'open',
              label: 'Открыть источник',
              icon: <ExternalLink />,
              onSelect: () => navigate(`/knowledge/sources/${source.id}`),
            },
            {
              type: 'item',
              id: 'reprocess',
              label: source.status === 'error' ? 'Обработать снова' : 'Переобработать',
              icon: <RefreshCw />,
              disabled: source.status === 'processing' || source.status === 'uploading',
              onSelect: () => onReprocess(source),
            },
            { type: 'separator' },
            {
              type: 'item',
              id: 'delete',
              label: 'Удалить источник',
              icon: <Trash2 />,
              danger: true,
              onSelect: () => onDelete(source),
            },
          ]}
          trigger={<IconButton size="sm" label="Действия с источником" icon={<MoreHorizontal />} />}
        />
      )}
    />
  );
}

export function SourcesToolbarSummary({
  total,
  byStatus,
}: {
  total: number;
  byStatus: Record<JobStatus, number>;
}) {
  const inFlight = byStatus.processing + byStatus.uploading;
  return (
    <div className={styles.summary}>
      <span className={styles.summaryItem}>
        <strong>{total}</strong> всего
      </span>
      <span className={styles.summaryItem} data-tone="success">
        <strong>{byStatus.ready}</strong> готово
      </span>
      {inFlight > 0 && (
        <span className={styles.summaryItem} data-tone="info">
          <strong>{inFlight}</strong> в обработке
        </span>
      )}
      {byStatus.error > 0 && (
        <span className={styles.summaryItem} data-tone="danger">
          <strong>{byStatus.error}</strong> с ошибкой
        </span>
      )}
    </div>
  );
}

export function UploadButton({
  onClick,
  label = 'Загрузить источник',
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <Button variant="primary" iconLeft={<Upload />} onClick={onClick}>
      {label}
    </Button>
  );
}
