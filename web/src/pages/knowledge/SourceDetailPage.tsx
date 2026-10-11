import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from '@/app/router';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  FileImage,
  FileText,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import { useActions } from '@/services';
import { useMode, useSource, useSourceContent } from '@/store';
import { sourceKind, type KnowledgeSource } from '@/types';
import { formatDateTime, formatNumber } from '@/lib/format';
import {
  Badge,
  Button,
  DefinitionList,
  EmptyState,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  Progress,
  SearchInput,
  Skeleton,
  useToast,
} from '@/components';
import { SourceStatusBadge } from '@/components/Entities';
import styles from './Knowledge.module.css';

export function SourceDetailPage() {
  const { sourceId } = useParams<{ sourceId: string }>();
  const source = useSource(sourceId);
  const mode = useMode(source?.mode_id);
  const { content, loading } = useSourceContent(sourceId);
  const actions = useActions();
  const toast = useToast();
  const navigate = useNavigate();

  const [pageIndex, setPageIndex] = useState(0);
  const [query, setQuery] = useState('');

  useEffect(() => {
    setPageIndex(0);
    setQuery('');
  }, [sourceId]);

  const pages = content?.pages ?? [];
  const currentPage = pages[Math.min(pageIndex, Math.max(0, pages.length - 1))];

  const matchingPages = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return new Set(pages.filter((page) => page.text.toLowerCase().includes(q)).map((p) => p.index));
  }, [pages, query]);

  const highlight = (text: string) => {
    const q = query.trim();
    if (!q) return text;
    const index = text.toLowerCase().indexOf(q.toLowerCase());
    if (index === -1) return text;
    return (
      <>
        {text.slice(0, index)}
        <mark className={styles.mark}>{text.slice(index, index + q.length)}</mark>
        {text.slice(index + q.length)}
      </>
    );
  };

  const handleReprocess = async (target: KnowledgeSource) => {
    try {
      await actions.reprocessSource(target.id);
      toast.success('Повторная обработка запущена', target.title);
    } catch {
      toast.error('Не удалось запустить обработку');
    }
  };

  const handleDelete = async (target: KnowledgeSource) => {
    try {
      await actions.deleteSource(target.id);
      toast.success('Источник удалён', target.title);
      navigate('/knowledge');
    } catch {
      toast.error('Не удалось удалить источник');
    }
  };

  if (loading || !source) {
    return (
      <Page>
        <Skeleton width={280} height={22} />
        <Skeleton width="100%" height={180} radius={12} />
        <Skeleton width="100%" height={280} radius={12} />
      </Page>
    );
  }

  const kind = sourceKind(source.media_type, source.filename);
  const busy = source.status === 'processing' || source.status === 'uploading';

  return (
    <Page>
      <PageHeader
        breadcrumb={
          <>
            <Link to="/knowledge">База знаний</Link>
            <span>/</span>
            {mode && <Link to={`/modes/${mode.id}?tab=knowledge`}>{mode.name}</Link>}
          </>
        }
        leading={
          <span className={styles.detailIcon} data-kind={kind}>
            {kind === 'image' ? <FileImage /> : <FileText />}
          </span>
        }
        title={source.title}

        actions={
          <>
            {/* No separate "Назад": the breadcrumb above is the way back, and a
                text button beside the destructive actions read as one of them. */}
            <Button
              variant="secondary" iconLeft={<RefreshCw />}
              onClick={() => handleReprocess(source)}
              disabled={busy}
            >
              Переобработать
            </Button>
            <Button
              variant="dangerGhost" iconLeft={<Trash2 />}
              onClick={() => handleDelete(source)}
            >
              Удалить
            </Button>
          </>
        }
        below={
          <div className={styles.detailBadges}>
            {/* Only what is not already on the properties panel: the current
                state and which mode the source belongs to. */}
            <SourceStatusBadge status={source.status} />
            {mode && (
              <Badge tone="neutral" size="sm" data-mode-color={mode.color}>
                <span className={styles.badgeDot} />
                {mode.name}
              </Badge>
            )}
          </div>
        }
      />

      {source.status === 'error' && (
        <div className={styles.errorBanner}>
          <AlertTriangle />
          <div className={styles.errorBody}>
            <div className={styles.errorTitle}>Обработка не удалась</div>
            <p className={styles.errorText}>
              {source.error ?? 'Неизвестная ошибка обработки.'}
            </p>
          </div>
          <Button
            variant="secondary" iconLeft={<RefreshCw />}
            onClick={() => handleReprocess(source)}
          >
            Попробовать снова
          </Button>
        </div>
      )}

      {busy && (
        <Panel>
          <PanelBody>
            <div className={styles.progressPanel}>
              <div className={styles.progressHead}>
                <span className={styles.progressTitle}>{source.stage ?? 'Обработка началась'}</span>
                <span className={styles.progressValue}>
                  {Math.round((source.progress ?? 0) * 100)}%
                </span>
              </div>
              <Progress value={source.progress ?? 0} size="md" label="Прогресс обработки" />
              <p className={styles.progressNote}>
                Источник появится в чатах режима сразу после индексации. Можно уйти со страницы —
                обработка продолжится в фоне, а статус обновится автоматически.
              </p>
            </div>
          </PanelBody>
        </Panel>
      )}

      <div className={styles.detailGrid}>
        <Panel flush className={styles.viewerPanel}>
          <PanelHeader
            title="Содержимое" actions={
              pages.length > 0 ? (
                <SearchInput
                  size="sm" value={query}
                  placeholder="Поиск по тексту" onChange={(e) => setQuery(e.target.value)}
                  onClear={() => setQuery('')}
                  className={styles.viewerSearch}
                />
              ) : undefined
            }
          />

          {source.status === 'error' ? (
            <PanelBody>
              <EmptyState
                icon={<AlertTriangle />}
                title="Нет извлечённого текста" description="Источник не был обработан. Запустите обработку повторно — потребуется скан лучшего качества."
                compact
              />
            </PanelBody>
          ) : loading || busy || pages.length === 0 ? (
            <PanelBody>
              <div className={styles.viewerSkeleton}>
                <Skeleton width="100%" height={14} />
                <Skeleton width="92%" height={14} />
                <Skeleton width="78%" height={14} />
                <Skeleton width="88%" height={14} />
                <Skeleton width="64%" height={14} />
              </div>
            </PanelBody>
          ) : (
            <div className={styles.viewer}>
              <nav className={styles.pageRail} aria-label="Страницы">
                <div className={styles.pageRailList}>
                <div className={styles.pageRailLabel}>
                  Страницы
                  {matchingPages && (
                    <span className={styles.pageRailMatches}>{matchingPages.size} совп.</span>
                  )}
                </div>
                {pages.map((page) => (
                  <button
                    key={page.index}
                    type="button" className={styles.pageButton}
                    data-active={page.index === pageIndex || undefined}
                    data-match={matchingPages?.has(page.index) || undefined}
                    data-dim={matchingPages && !matchingPages.has(page.index) ? true : undefined}
                    onClick={() => setPageIndex(page.index)}
                  >
                    <span className={styles.pageNumber}>{page.index + 1}</span>
                    <span className={styles.pagePreview}>
                      {page.text.replace(/\s+/g, ' ').slice(0, 52) || 'Пустая страница'}
                    </span>
                  </button>
                ))}
                </div>
              </nav>

              <div className={styles.pageBody}>
                <div className={styles.pageNavRow}>
                  <Button
                    size="sm" variant="ghost" iconLeft={<ChevronLeft />}
                    disabled={pageIndex === 0}
                    onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                  >
                    Пред.
                  </Button>
                  <span className={styles.pageNavLabel}>
                    Страница {pageIndex + 1} из {pages.length}
                  </span>
                  <Button
                    size="sm" variant="ghost" iconRight={<ChevronRight />}
                    disabled={pageIndex >= pages.length - 1}
                    onClick={() => setPageIndex((i) => Math.min(pages.length - 1, i + 1))}
                  >
                    След.
                  </Button>
                </div>

                <article className={styles.pageText}>{highlight(currentPage?.text ?? '')}</article>
              </div>
            </div>
          )}
        </Panel>

        <div className={styles.detailSide}>
          <Panel>
            <PanelHeader title="Параметры источника" />
            <PanelBody>
              <DefinitionList
                columns={1}
                items={[
                  {
                    label: 'Режим',
                    value: mode ? (
                      <Link to={`/modes/${mode.id}`} className={styles.sideLink}>
                        {mode.name}
                      </Link>
                    ) : (
                      '—'
                    ),
                  },
                  {
                    label: 'Исходный файл',
                    value: <span className={styles.mono}>{source.filename}</span>,
                  },
                  { label: 'Тип файла', value: source.media_type },
                  {
                    label: 'Способ обработки',
                    value:
                      source.processing_mode === 'VISION'
                        ? 'Vision-анализ'
                        : 'OCR-распознавание',
                  },
                  { label: 'Страниц', value: source.page_count || '—' },
                  { label: 'Фрагментов', value: formatNumber(source.chunk_count) },
                  { label: 'Токенов (оценка)', value: formatNumber(source.token_count) },
                  { label: 'Загружен', value: formatDateTime(source.created_at) },
                  {
                    label: 'Обновлён',
                    value: source.updated_at ? formatDateTime(source.updated_at) : '—',
                  },
                ]}
              />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Использование" />
            <PanelBody>
              <div className={styles.usageBlock}>
                <p className={styles.usageText}>
                  Фрагменты этого источника доступны в поиске только внутри режима
                  {mode ? ` «${mode.name}»` : ''}. Повторная обработка перезапишет фрагменты после
                  успешного завершения.
                </p>
                <div className={styles.usageActions}>
                  <Button
                    size="sm" variant="secondary" iconLeft={<Search />}
                    onClick={() => navigate('/chats')}
                  >
                    Спросить в чате
                  </Button>
                  <Button
                    size="sm" variant="ghost" iconLeft={<RefreshCw />}
                    onClick={() => handleReprocess(source)}
                    disabled={busy}
                  >
                    Переобработать
                  </Button>
                </div>
              </div>
            </PanelBody>
          </Panel>
        </div>
      </div>
    </Page>
  );
}
