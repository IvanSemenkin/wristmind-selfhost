import { useMemo } from 'react';
import { BookOpen } from 'lucide-react';
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
  useToast,
} from '@/components';
import { useQuickActions } from '@/app/QuickActions';
import { SourcesTable, SourcesToolbarSummary, sourceTimestamp } from './SourcesTable';
import styles from './Knowledge.module.css';

const EMPTY_STATUS_COUNTS: Record<JobStatus, number> = {
  uploading: 0,
  processing: 0,
  ready: 0,
  error: 0,
};

export function KnowledgePage() {
  const sources = useSources();
  const modes = useModes();
  const actions = useActions();
  const toast = useToast();
  const quick = useQuickActions();

  /* A plain list on purpose: no search field, mode filter, sort control or
     status tabs. Order stays newest-first, and the header summary still
     reports the per-status counts those tabs used to filter by. */
  const sorted = useMemo(
    () =>
      [...sources].sort(
        (a, b) => +new Date(sourceTimestamp(b)) - +new Date(sourceTimestamp(a)),
      ),
    [sources],
  );

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
            onClick={() => quick.uploadSource(null)}
          >
            Загрузить источник
          </Button>
        }
        below={<SourcesToolbarSummary total={sources.length} byStatus={byStatus} />}
      />

      <Panel flush>
        <PanelBody>
          {/* The panel has no header of its own, and the table's column labels
              carry no top padding, so the table supplies its own headroom. */}
          <div className={styles.tableTop}>
            <SourcesTable
              sources={sorted}
              modeName={modeName}
              modeColor={modeColor}
              onReprocess={handleReprocess}
              onDelete={handleDelete}
              emptyState={
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
              }
            />
          </div>
        </PanelBody>
      </Panel>
    </Page>
  );
}
