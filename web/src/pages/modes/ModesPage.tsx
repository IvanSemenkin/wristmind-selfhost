import { useMemo, useState } from 'react';
import { Link, useNavigate } from '@/app/router';
import {
  BookOpen,
  EyeOff,
  Layers,
  MessagesSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
  Watch,
} from 'lucide-react';
import { useActions } from '@/services';
import { useChats, useModes, useModels, useSources } from '@/store';
import type { Mode } from '@/types';
import {
  Button,
  EmptyState,
  IconButton,
  Menu,
  Page,
  PageHeader,
  SearchInput,
  SegmentedControl,
  Switch,
  Toolbar,
  ToolbarGroup,
  useConfirm,
  useToast,
} from '@/components';
import { ModeDot } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import styles from './Modes.module.css';

type ScopeFilter = 'all' | 'watch' | 'local';

export function ModesPage() {
  const modes = useModes();
  const sources = useSources();
  const chats = useChats();
  const models = useModels();
  const actions = useActions();
  const confirm = useConfirm();
  const toast = useToast();
  const quick = useQuickActions();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<ScopeFilter>('all');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return modes.filter((mode) => {
      if (scope === 'watch' && mode.hidden_on_watch) return false;
      if (scope === 'local') {
        const model = models.find((m) => m.id === mode.response_model_id);
        if (!model?.capabilities.includes('local')) return false;
      }
      if (!q) return true;
      return `${mode.name} ${mode.description}`.toLowerCase().includes(q);
    });
  }, [modes, query, scope, models]);

  const handleDelete = async (mode: Mode) => {
    const modeSources = sources.filter((s) => s.mode_id === mode.id);
    const modeChats = chats.filter((c) => c.mode_id === mode.id);
    const ok = await confirm({
      title: `Удалить режим «${mode.name}»?`,
      description:
        'Вместе с режимом будут удалены его чаты и вся база знаний. Это действие нельзя отменить.',
      confirmLabel: 'Удалить режим',
      confirmPhrase: 'удалить',
      details: (
        <>
          <span>Источников будет удалено: {modeSources.length}</span>
          <span>Чатов будет удалено: {modeChats.length}</span>
          <span>Системный промпт и настройки будут потеряны.</span>
        </>
      ),
    });
    if (!ok) return;
    try {
      await actions.deleteMode(mode.id);
      toast.success('Режим удалён', mode.name);
      navigate('/modes');
    } catch {
      toast.error('Не удалось удалить режим');
    }
  };

  const toggleWatch = async (mode: Mode) => {
    await actions.updateMode(mode.id, { hidden_on_watch: !mode.hidden_on_watch });
    toast.toast({
      title: mode.hidden_on_watch ? 'Режим показан на часах' : 'Режим скрыт с часов',
      description: mode.name,
    });
  };

  return (
    <Page>
      <PageHeader
        title="Режимы" actions={
          <Button variant="primary" iconLeft={<Plus />} onClick={quick.createMode}>
            Новый режим
          </Button>
        }
        below={
          <div className={styles.summary}>
            <span className={styles.summaryItem}>
              <strong>{modes.length}</strong> всего
            </span>
            <span className={styles.summaryItem}>
              <Watch />
              <strong>{modes.filter((m) => !m.hidden_on_watch).length}</strong> на часах
            </span>
            <span className={styles.summaryItem}>
              <BookOpen />
              <strong>{sources.filter((s) => s.status === 'ready').length}</strong> источников
            </span>
          </div>
        }
      />

      <Toolbar>
        <ToolbarGroup className={styles.filterGroup}>
          <SearchInput
            value={query}
            placeholder="Поиск по названию или описанию" onChange={(e) => setQuery(e.target.value)}
            onClear={() => setQuery('')}
            className={styles.search}
          />
        </ToolbarGroup>
        <ToolbarGroup>
          <SegmentedControl<ScopeFilter>
            size="sm" value={scope}
            onChange={setScope}
            aria-label="Фильтр режимов" options={[
              { value: 'all', label: 'Все' },
              { value: 'watch', label: 'На часах' },
              { value: 'local', label: 'Локальные модели' },
            ]}
          />
        </ToolbarGroup>
      </Toolbar>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<Layers />}
          title={modes.length === 0 ? 'Режимов пока нет' : 'Ничего не найдено'}
          description={
            modes.length === 0
              ? 'Создайте первый режим: своя модель, промпт и база знаний.'
              : 'Измените запрос или снимите фильтр.'
          }
          action={
            modes.length === 0 ? (
              <Button variant="primary" iconLeft={<Plus />} onClick={quick.createMode}>
                Создать режим
              </Button>
            ) : (
              <Button
                variant="secondary" onClick={() => {
                  setQuery('');
                  setScope('all');
                }}
              >
                Сбросить фильтры
              </Button>
            )
          }
        />
      ) : (
        <div className={styles.grid}>
          {filtered.map((mode) => {
            return (
              <article key={mode.id} className={styles.card} data-mode-color={mode.color}>
                <div className={styles.cardAccent} aria-hidden />
                {/* One thin row: identity, the name that opens the mode, the
                    watch toggle and the actions menu. Model, source and chat
                    counts live on the mode's own page instead of repeating on
                    every card. */}
                <div className={styles.cardRow}>
                  {mode.icon ? (
                    <ModeDot color={mode.color} icon={mode.icon} size="md" />
                  ) : (
                    <span className={styles.cardDot} data-mode-color={mode.color} aria-hidden />
                  )}
                  <Link to={`/modes/${mode.id}`} className={styles.cardTitle}>
                    {mode.name}
                  </Link>
                  <Switch
                    size="sm" checked={!mode.hidden_on_watch}
                    onChange={() => void toggleWatch(mode)}
                    label="На часах"
                  />
                  <Menu
                    align="end" width={236}
                    entries={[
                      {
                        type: 'item',
                        id: 'edit',
                        label: 'Настройки режима',
                        icon: <Pencil />,
                        onSelect: () => quick.editMode(mode),
                      },
                      {
                        type: 'item',
                        id: 'watch',
                        label: mode.hidden_on_watch
                          ? 'Показать на часах'
                          : 'Скрыть с часов',
                        icon: mode.hidden_on_watch ? <Watch /> : <EyeOff />,
                        onSelect: () => void toggleWatch(mode),
                      },
                      {
                        type: 'item',
                        id: 'chat',
                        label: 'Новый чат в режиме',
                        icon: <MessagesSquare />,
                        onSelect: () => quick.newChat(mode.id),
                      },
                      {
                        type: 'item',
                        id: 'upload',
                        label: 'Загрузить источник',
                        icon: <BookOpen />,
                        onSelect: () => quick.uploadSource(mode.id),
                      },
                      { type: 'separator' },
                      {
                        type: 'item',
                        id: 'delete',
                        label: 'Удалить режим',
                        icon: <Trash2 />,
                        danger: true,
                        onSelect: () => handleDelete(mode),
                      },
                    ]}
                    trigger={
                      <IconButton size="sm" label="Действия с режимом" icon={<MoreHorizontal />} />
                    }
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Page>
  );
}
