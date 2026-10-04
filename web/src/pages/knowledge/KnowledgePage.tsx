import { useMemo, useState } from 'react';
import { BookOpen, Filter, Search } from 'lucide-react';
import { useActions } from '@/services';
import { useModes, useSources } from '@/store';
import type { JobStatus, KnowledgeSource } from '@/types';
import {
  Button,
  EmptyState,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  SearchInput,
  SegmentedControl,
  Select,
  Toolbar,
  ToolbarGroup,
  useToast,
} from '@/components';
import { useQuickActions } from '@/app/QuickActions';
import { SourcesTable, SourcesToolbarSummary, sourceTimestamp } from './SourcesTable';
import styles from './Knowledge.module.css';

type StatusFilter = 'all' | 'ready' | 'processing' | 'error';
type SortKey = 'updated' | 'title' | 'pages' | 'chunks';

const EMPTY_STATUS_COUNTS: Record<JobStatus, number> = {
  uploading: 0,
  processing: 0,
  ready: 0,
  error: 0,
};

function bucketOf(status: JobStatus): StatusFilter {
  if (status === 'ready') return 'ready';
  if (status === 'error') return 'error';
  return 'processing';
}

export function KnowledgePage() {
  const sources = useSources();
  const modes = useModes();
  const actions = useActions();
  const toast = useToast();
  const quick = useQuickActions();

  const [query, setQuery] = useState('');
  const [modeFilter, setModeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sort, setSort] = useState<SortKey>('updated');

  const modeOptions = useMemo(
    () => [
      { value: 'all', label: 'Все режимы' },
      ...modes.map((mode) => ({ value: mode.id, label: mode.name })),
    ],
    [modes],
  );

  const sortOptions = [
    { value: 'updated', label: 'Сначала новые' },
    { value: 'title', label: 'По названию' },
    { value: 'pages', label: 'По числу страниц' },
    { value: 'chunks', label: 'По числу фрагментов' },
  ];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = sources.filter((source) => {
      if (statusFilter !== 'all' && bucketOf(source.status) !== statusFilter) return false;
      if (modeFilter !== 'all' && source.mode_id !== modeFilter) return false;
      if (!q) return true;
      return `${source.title} ${source.filename}`.toLowerCase().includes(q);
    });

    const sorted = [...list];
    switch (sort) {
      case 'title':
        sorted.sort((a, b) => a.title.localeCompare(b.title, 'ru'));
        break;
      case 'pages':
        sorted.sort((a, b) => b.page_count - a.page_count);
        break;
      case 'chunks':
        sorted.sort((a, b) => b.chunk_count - a.chunk_count);
        break;
      default:
        sorted.sort(
          (a, b) => +new Date(sourceTimestamp(b)) - +new Date(sourceTimestamp(a)),
        );
    }
    return sorted;
  }, [sources, query, modeFilter, statusFilter, sort]);

  const byStatus = useMemo(() => {
    const counts = { ...EMPTY_STATUS_COUNTS };
    for (const source of sources) counts[source.status] += 1;
    return counts;
  }, [sources]);

  const modeName = (modeId: string) => modes.find((m) => m.id === modeId)?.name;
  const modeColor = (modeId: string) => modes.find((m) => m.id === modeId)?.color;

  const handleReprocess = async (source: KnowledgeSource) => {
    try {
      await actions.reprocessSource(source.id);
      toast.success('Повторная обработка запущена', source.title);
    } catch {
      toast.error('Не удалось запустить обработку');
    }
  };

  const handleDelete = async (source: KnowledgeSource) => {
    try {
      await actions.deleteSource(source.id);
      toast.success('Источник удалён', source.title);
    } catch {
      toast.error('Не удалось удалить источник');
    }
  };

  return (
    <Page>
      <PageHeader
        title="База знаний" actions={
          <Button
            variant="primary" iconLeft={<BookOpen />}
            onClick={() => quick.uploadSource(modeFilter !== 'all' ? modeFilter : null)}
          >
            Загрузить источник
          </Button>
        }
        below={<SourcesToolbarSummary total={sources.length} byStatus={byStatus} />}
      />

      <Toolbar>
        <ToolbarGroup className={styles.filterGroup}>
          <SearchInput
            value={query}
            placeholder="Поиск по названию или файлу" onChange={(e) => setQuery(e.target.value)}
            onClear={() => setQuery('')}
            className={styles.search}
          />
          <Select
            size="md" value={modeFilter}
            options={modeOptions}
            onChange={setModeFilter}
            ariaLabel="Фильтр по режиму" className={styles.select}
          />
          <Select
            size="md" value={sort}
            options={sortOptions}
            onChange={(value) => setSort(value as SortKey)}
            ariaLabel="Сортировка" className={styles.selectSort}
          />
        </ToolbarGroup>
        <ToolbarGroup>
          <SegmentedControl<StatusFilter>
            size="sm" value={statusFilter}
            onChange={setStatusFilter}
            aria-label="Фильтр по статусу" options={[
              { value: 'all', label: 'Все' },
              { value: 'ready', label: 'Готовые' },
              { value: 'processing', label: 'В обработке' },
              { value: 'error', label: 'Ошибки' },
            ]}
          />
        </ToolbarGroup>
      </Toolbar>

      <Panel flush>
        <PanelBody>
          <SourcesTable
            sources={filtered}
            modeName={modeName}
            modeColor={modeColor}
            onReprocess={handleReprocess}
            onDelete={handleDelete}
            emptyState={
              sources.length === 0 ? (
                <EmptyState
                  icon={<BookOpen />}
                  title="База знаний пуста" description="Загрузите PDF или изображение. Документ пройдёт распознавание, разобьётся на фрагменты и станет доступен в чатах режима." action={
                    <Button
                      variant="primary" iconLeft={<BookOpen />}
                      onClick={() => quick.uploadSource(null)}
                    >
                      Загрузить первый источник
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={<Filter />}
                  title="Ничего не найдено" description={
                    query
                      ? `По запросу «${query}» нет источников. Измените запрос или сбросьте фильтры.`
                      : 'Под текущие фильтры не подходит ни один источник.'
                  }
                  action={
                    <Button
                      variant="secondary" iconLeft={<Search />}
                      onClick={() => {
                        setQuery('');
                        setModeFilter('all');
                        setStatusFilter('all');
                      }}
                    >
                      Сбросить фильтры
                    </Button>
                  }
                />
              )
            }
          />
        </PanelBody>
      </Panel>

      {statusFilter === 'error' && byStatus.error > 0 && (
        <p className={styles.hint}>
          Повторная обработка источника запускается из меню действий в строке. Если ошибка
          повторяется, проверьте качество скана: распознавание требует не менее 200 dpi.
        </p>
      )}
    </Page>
  );
}
