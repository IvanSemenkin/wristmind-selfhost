import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from '@/app/router';
import {
  AlertTriangle,
  BookOpen,
  Check,
  Eye,
  Layers,
  MessagesSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Upload,
  Watch,
  Zap,
} from 'lucide-react';
import { useActions } from '@/services';
import { useChats, useMode, useModels, useSources, useStats } from '@/store';
import type { Chat, KnowledgeSource, Mode, ModeColor } from '@/types';
import { formatCompact, formatNumber, formatRelativeTime, plural } from '@/lib/format';
import {
  Badge,
  Banner,
  Button,
  DataTable,
  DefinitionList,
  EmptyState,
  Field,
  IconButton,
  Input,
  Menu,
  Metric,
  MetricStrip,
  OptionList,
  Page,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  SearchInput,
  SegmentedControl,
  Switch,
  Tabs,
  Textarea,
  useConfirm,
  useToast,
} from '@/components';
import type { Column, TabItem } from '@/components';
import { ModeDot, ModelIcon, SourceStatusBadge } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import { ColorSwatchRow } from './ModeFormDialog';
import { SourcesTable } from '@/pages/knowledge/SourcesTable';
import styles from './Modes.module.css';

type TabId = 'overview' | 'chats' | 'knowledge' | 'settings';

const TABS: TabItem<TabId>[] = [
  { id: 'overview', label: 'Обзор', icon: <Layers /> },
  { id: 'chats', label: 'Чаты', icon: <MessagesSquare /> },
  { id: 'knowledge', label: 'База знаний', shortLabel: 'Знания', icon: <BookOpen /> },
  { id: 'settings', label: 'Настройки', icon: <Pencil /> },
];

export function ModeDetailPage() {
  const { modeId } = useParams<{ modeId: string }>();
  const mode = useMode(modeId);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const rawTab = searchParams.get('tab');
  const tab: TabId = (['overview', 'chats', 'knowledge', 'settings'] as TabId[]).includes(
    rawTab as TabId,
  )
    ? (rawTab as TabId)
    : 'overview';

  if (!mode) {
    return (
      <Page>
        <EmptyState
          icon={<Layers />}
          title="Режим не найден" description="Возможно, он был удалён." action={
            <Button variant="secondary" onClick={() => navigate('/modes')}>
              К списку режимов
            </Button>
          }
        />
      </Page>
    );
  }

  return (
    <ModeShell
      mode={mode}
      tab={tab}
      onTabChange={(next) =>
        setSearchParams(next === 'overview' ? {} : { tab: next }, { replace: true })
      }
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Shell                                                                      */
/* -------------------------------------------------------------------------- */

function ModeShell({
  mode,
  tab,
  onTabChange,
}: {
  mode: Mode;
  tab: TabId;
  onTabChange: (tab: TabId) => void;
}) {
  const sources = useSources(mode.id);
  const chats = useChats().filter((c) => c.mode_id === mode.id);
  const models = useModels();
  const model = models.find((m) => m.id === mode.response_model_id);
  const quick = useQuickActions();

  const tabsWithCounts = TABS.map((item) =>
    item.id === 'chats'
      ? { ...item, count: chats.length }
      : item.id === 'knowledge'
        ? { ...item, count: sources.length }
        : item,
  );

  return (
    <Page>
      <PageHeader
        breadcrumb={<Link to="/modes">Режимы</Link>}
        leading={<ModeDot color={mode.color} icon={mode.icon} size="lg" />}
        title={mode.name}
        actions={
          <>
            <Button
              variant="secondary" iconLeft={<Upload />}
              onClick={() => quick.uploadSource(mode.id)}
            >
              Источник
            </Button>
            <Button variant="primary" iconLeft={<Plus />} onClick={() => quick.newChat(mode.id)}>
              Новый чат
            </Button>
          </>
        }
        below={
          <div className={styles.detailHeader}>
            <div className={styles.detailHeaderMeta}>
              <Badge tone="neutral" size="sm">
                <ModelIcon model={model} />
                {model?.name ?? 'модель не выбрана'}
              </Badge>
              <Badge
                tone={mode.hidden_on_watch ? 'neutral' : 'success'}
                size="sm"
                dot
              >
                {mode.hidden_on_watch ? 'Скрыт с часов' : 'На часах'}
              </Badge>
              <span className={styles.detailHeaderDim}>
                Создан {formatRelativeTime(mode.created_at)}
              </span>
            </div>
            <Tabs
              items={tabsWithCounts}
              value={tab}
              onChange={onTabChange}
              aria-label="Разделы режима"
            />
          </div>
        }
      />

      {tab === 'overview' && <ModeOverview mode={mode} />}
      {tab === 'chats' && <ModeChats mode={mode} chats={chats} />}
      {tab === 'knowledge' && <ModeKnowledge mode={mode} sources={sources} />}
      {tab === 'settings' && <ModeSettings mode={mode} />}
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview tab                                                               */
/* -------------------------------------------------------------------------- */

function ModeOverview({ mode }: { mode: Mode }) {
  const sources = useSources(mode.id);
  const chats = useChats().filter((c) => c.mode_id === mode.id);
  const models = useModels();
  const stats = useStats();
  const quick = useQuickActions();
  const model = models.find((m) => m.id === mode.response_model_id);

  const ready = sources.filter((s) => s.status === 'ready');
  const processing = sources.filter(
    (s) => s.status === 'processing' || s.status === 'uploading',
  );
  const failed = sources.filter((s) => s.status === 'error');
  const tokens = ready.reduce((sum, s) => sum + s.token_count, 0);
  const chunks = ready.reduce((sum, s) => sum + s.chunk_count, 0);
  const pages = ready.reduce((sum, s) => sum + s.page_count, 0);
  const modeUsage = stats?.usage.find((u) => u.mode_id === mode.id);
  const recentChats = [...chats].sort(
    (a, b) => +new Date(b.updated_at) - +new Date(a.updated_at),
  );

  return (
    <>
      <MetricStrip>
        <Metric
          label="Готовых источников" value={ready.length}
          meta={
            processing.length > 0
              ? `${processing.length} в обработке`
              : sources.length === 0
                ? 'база знаний пуста'
                : 'все обработаны'
          }
        />
        <Metric label="Страниц" value={formatNumber(pages)} meta="распознано" />
        <Metric label="Фрагментов" value={formatNumber(chunks)} meta="доступно в поиске" />
        <Metric label="Токенов" value={formatCompact(tokens)} meta="оценка объёма" />
        <Metric
          label="Чатов" value={chats.length}
          meta={recentChats.length ? 'есть история' : 'нет диалогов'}
        />
        <Metric
          label="Запросов" value={modeUsage ? formatCompact(modeUsage.requests) : '0'}
          meta={modeUsage?.tokens ? `${formatCompact(modeUsage.tokens)} токенов за 14 дней` : 'за 14 дней'}
        />
      </MetricStrip>

      {failed.length > 0 && (
        <Banner
          tone="danger" icon={<AlertTriangle />}
          title={`${failed.length} ${plural(failed.length, 'источник не обработан', 'источника не обработаны', 'источников не обработано')}`}
          action={
            <Button size="sm" variant="secondary" onClick={() => quick.uploadSource(mode.id)}>
              Загрузить заново
            </Button>
          }
        >
          {failed.map((s) => s.title).join(', ')} — проверьте качество скана и запустите повторную
          обработку.
        </Banner>
      )}

      <div className={styles.overviewGrid}>
        <Panel flush>
          <PanelHeader
            title="Последние чаты режима" actions={
              <Button
                size="sm" variant="ghost" iconLeft={<Plus />}
                onClick={() => quick.newChat(mode.id)}
              >
                Новый чат
              </Button>
            }
          />
          {chats.length === 0 ? (
            <EmptyState
              compact
              icon={<MessagesSquare />}
              title="Диалогов ещё нет" description="Задайте первый вопрос — ответ будет основан на источниках режима." action={
                <Button
                  size="sm" variant="primary" iconLeft={<Plus />}
                  onClick={() => quick.newChat(mode.id)}
                >
                  Создать чат
                </Button>
              }
            />
          ) : (
            <ul className={styles.miniList}>
              {recentChats.slice(0, 6).map((chat) => (
                <li key={chat.id}>
                  <Link to={`/chats/${chat.id}`} className={styles.miniRow}>
                    <span className={styles.miniTitle}>{chat.title}</span>
                    <span className={styles.miniTime}>{formatRelativeTime(chat.updated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel flush>
          <PanelHeader
            title="Источники" actions={
              <Button
                size="sm" variant="ghost" iconLeft={<Upload />}
                onClick={() => quick.uploadSource(mode.id)}
              >
                Загрузить
              </Button>
            }
          />
          {sources.length === 0 ? (
            <EmptyState
              compact
              icon={<BookOpen />}
              title="База знаний пуста" description="Загрузите PDF или изображение — фрагменты станут доступны в ответах." action={
                <Button
                  size="sm" variant="primary" iconLeft={<Upload />}
                  onClick={() => quick.uploadSource(mode.id)}
                >
                  Загрузить источник
                </Button>
              }
            />
          ) : (
            <ul className={styles.miniList}>
              {sources.slice(0, 6).map((source) => (
                <li key={source.id}>
                  <Link to={`/knowledge/sources/${source.id}`} className={styles.miniRow}>
                    <span className={styles.miniTitle}>{source.title}</span>
                    <SourceStatusBadge status={source.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className={styles.overviewGrid}>
        <Panel>
          <PanelHeader
            title="Системный промпт"
          />
          <PanelBody>
            <pre className={styles.promptPreview}>{mode.system_prompt}</pre>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Модель и видимость" />
          <PanelBody>
            <DefinitionList
              columns={1}
              items={[
                { label: 'Модель', value: <ModelIcon model={model} /> },
                { label: 'Название', value: model?.name ?? 'не выбрана' },
                { label: 'Провайдер', value: model?.provider ?? '—' },
                {
                  label: 'Контекст',
                  value: model ? `${formatCompact(model.context_window)} токенов` : '—',
                },
                { label: 'Возможности', value: model?.capabilities.join(' · ') ?? '—' },
                {
                  label: 'На часах',
                  value: mode.hidden_on_watch ? (
                    <span className={styles.dim}>скрыт</span>
                  ) : (
                    <span className={styles.inlineOk}>
                      <Check /> показывается
                    </span>
                  ),
                },
              ]}
            />
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Chats tab                                                                  */
/* -------------------------------------------------------------------------- */

function ModeChats({ mode, chats }: { mode: Mode; chats: Chat[] }) {
  const [query, setQuery] = useState('');
  const actions = useActions();
  const toast = useToast();
  const quick = useQuickActions();
  const navigate = useNavigate();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chats.filter((c) => c.title.toLowerCase().includes(q)) : chats;
  }, [chats, query]);

  const columns: Column<Chat>[] = [
    {
      key: 'title',
      header: 'Чат',
      mobilePrimary: true,
      render: (chat) => (
        <Link to={`/chats/${chat.id}`} className={styles.chatCell}>
          {chat.pinned && <Pin className={styles.pinSmall} />}
          <span className={styles.chatCellTitle}>{chat.title}</span>
        </Link>
      ),
    },
    {
      key: 'updated',
      header: 'Обновлён',
      width: '150px',
      align: 'right',
      mobileLabel: 'Обновлён',
      render: (chat) => <span className={styles.dim}>{formatRelativeTime(chat.updated_at)}</span>,
    },
  ];

  const handleDelete = async (chat: Chat) => {
    try {
      await actions.deleteChat(chat.id);
      toast.success('Чат удалён', chat.title);
    } catch {
      toast.error('Не удалось удалить чат');
    }
  };

  return (
    <Panel flush>
      <PanelHeader
        title={`Чаты режима «${mode.name}»`}
        actions={
          <>
            <SearchInput
              size="sm" value={query}
              placeholder="Поиск" onChange={(e) => setQuery(e.target.value)}
              onClear={() => setQuery('')}
              className={styles.panelSearch}
            />
            <Button
              size="sm" variant="primary" iconLeft={<Plus />}
              onClick={() => quick.newChat(mode.id)}
            >
              Новый
            </Button>
          </>
        }
      />
      <PanelBody>
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={(chat) => chat.id}
          onRowClick={(chat) => navigate(`/chats/${chat.id}`)}
          emptyState={
            <EmptyState
              icon={<MessagesSquare />}
              title={chats.length === 0 ? 'Диалогов ещё нет' : 'Ничего не найдено'}
              description={
                chats.length === 0
                  ? 'Создайте чат в этом режиме — он будет искать ответы в источниках режима.'
                  : 'Попробуйте другой запрос.'
              }
              action={
                chats.length === 0 ? (
                  <Button
                    variant="primary" iconLeft={<Plus />}
                    onClick={() => quick.newChat(mode.id)}
                  >
                    Создать чат
                  </Button>
                ) : undefined
              }
            />
          }
          rowActions={(chat) => (
            <Menu
              align="end" width={210}
              entries={[
                {
                  type: 'item',
                  id: 'pin',
                  label: chat.pinned ? 'Снять закрепление' : 'Закрепить',
                  icon: chat.pinned ? <PinOff /> : <Pin />,
                  onSelect: () => void actions.updateChat(chat.id, { pinned: !chat.pinned }),
                },
                {
                  type: 'item',
                  id: 'delete',
                  label: 'Удалить чат',
                  icon: <Trash2 />,
                  danger: true,
                  onSelect: () => handleDelete(chat),
                },
              ]}
              trigger={<IconButton size="sm" label="Действия с чатом" icon={<MoreHorizontal />} />}
            />
          )}
        />
      </PanelBody>
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* Knowledge tab                                                              */
/* -------------------------------------------------------------------------- */

function ModeKnowledge({ mode, sources }: { mode: Mode; sources: KnowledgeSource[] }) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<'all' | 'ready' | 'processing' | 'error'>('all');
  const actions = useActions();
  const toast = useToast();
  const quick = useQuickActions();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sources.filter((source) => {
      if (status !== 'all') {
        const bucket =
          source.status === 'ready' ? 'ready' : source.status === 'error' ? 'error' : 'processing';
        if (bucket !== status) return false;
      }
      if (!q) return true;
      return `${source.title} ${source.filename}`.toLowerCase().includes(q);
    });
  }, [sources, query, status]);

  const inFlight = sources.filter(
    (s) => s.status === 'processing' || s.status === 'uploading',
  ).length;

  const handleReprocess = async (source: KnowledgeSource) => {
    await actions.reprocessSource(source.id);
    toast.success('Повторная обработка запущена', source.title);
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
    <Panel flush>
      <PanelHeader
        title="База знаний режима" actions={
          <>
            <SearchInput
              size="sm" value={query}
              placeholder="Поиск" onChange={(e) => setQuery(e.target.value)}
              onClear={() => setQuery('')}
              className={styles.panelSearch}
            />
            <Button
              size="sm" variant="primary" iconLeft={<Upload />}
              onClick={() => quick.uploadSource(mode.id)}
            >
              Загрузить
            </Button>
          </>
        }
      />
      <div className={styles.knowledgeToolbar}>
        <SegmentedControl
          size="sm" value={status}
          onChange={setStatus}
          aria-label="Статус обработки" options={[
            { value: 'all', label: `Все (${sources.length})` },
            {
              value: 'ready',
              label: `Готовые (${sources.filter((s) => s.status === 'ready').length})`,
            },
            { value: 'processing', label: `В обработке (${inFlight})` },
            {
              value: 'error',
              label: `Ошибки (${sources.filter((s) => s.status === 'error').length})`,
            },
          ]}
        />
      </div>
      <PanelBody>
        <SourcesTable
          sources={filtered}
          showMode={false}
          modeName={() => mode.name}
          modeColor={() => mode.color}
          onReprocess={handleReprocess}
          onDelete={handleDelete}
          emptyState={
            <EmptyState
              icon={<BookOpen />}
              title={sources.length === 0 ? 'База знаний пуста' : 'Ничего не найдено'}
              description={
                sources.length === 0
                  ? 'Загрузите PDF или изображение — режим начнёт отвечать со ссылками на страницы.'
                  : 'Измените запрос или снимите фильтр по статусу.'
              }
              action={
                sources.length === 0 ? (
                  <Button
                    variant="primary" iconLeft={<Upload />}
                    onClick={() => quick.uploadSource(mode.id)}
                  >
                    Загрузить источник
                  </Button>
                ) : undefined
              }
            />
          }
        />
      </PanelBody>
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* Settings tab                                                               */
/* -------------------------------------------------------------------------- */

const DEFAULT_PROMPT = `Ты — ассистент режима.

Правила:
1. Отвечай кратко и по делу.
2. Опирайся на базу знаний режима и ссылайся на источники.
3. Если данных недостаточно — скажи об этом прямо.`;

function ModeSettings({ mode }: { mode: Mode }) {
  const models = useModels();
  const sources = useSources(mode.id);
  const chats = useChats().filter((c) => c.mode_id === mode.id);
  const actions = useActions();
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();

  const [name, setName] = useState(mode.name);
  const [description, setDescription] = useState(mode.description);
  const [color, setColor] = useState<ModeColor>(mode.color);
  const [responseModelId, setResponseModelId] = useState(mode.response_model_id);
  const [systemPrompt, setSystemPrompt] = useState(mode.system_prompt);
  const [hiddenOnWatch, setHiddenOnWatch] = useState(mode.hidden_on_watch);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(mode.name);
    setDescription(mode.description);
    setColor(mode.color);
    setResponseModelId(mode.response_model_id);
    setSystemPrompt(mode.system_prompt);
    setHiddenOnWatch(mode.hidden_on_watch);
  }, [mode]);

  const dirty =
    name !== mode.name ||
    description !== mode.description ||
    color !== mode.color ||
    responseModelId !== mode.response_model_id ||
    systemPrompt !== mode.system_prompt ||
    hiddenOnWatch !== mode.hidden_on_watch;

  const nameError = name.trim().length < 2 ? 'Укажите название' : null;
  const promptError = systemPrompt.trim().length < 10 ? 'Промпт слишком короткий' : null;

  const save = async () => {
    if (nameError || promptError) return;
    setSaving(true);
    try {
      await actions.updateMode(mode.id, {
        name: name.trim(),
        description: description.trim(),
        color,
        response_model_id: responseModelId,
        system_prompt: systemPrompt.trim(),
        hidden_on_watch: hiddenOnWatch,
      });
      toast.success('Режим сохранён', name.trim());
    } catch {
      toast.error('Не удалось сохранить режим');
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setName(mode.name);
    setDescription(mode.description);
    setColor(mode.color);
    setResponseModelId(mode.response_model_id);
    setSystemPrompt(mode.system_prompt);
    setHiddenOnWatch(mode.hidden_on_watch);
    toast.toast({ title: 'Изменения отменены' });
  };

  const handleDelete = async () => {
    const ok = await confirm({
      title: `Удалить режим «${mode.name}»?`,
      description: 'Чаты и база знаний режима будут удалены. Действие необратимо.',
      confirmLabel: 'Удалить режим',
      confirmPhrase: 'удалить',
      details: (
        <>
          <span>Источников: {sources.length}</span>
          <span>Чатов: {chats.length}</span>
        </>
      ),
    });
    if (!ok) return;
    await actions.deleteMode(mode.id);
    toast.success('Режим удалён', mode.name);
    navigate('/modes');
  };

  return (
    <>
      <div className={styles.settingsGrid}>
        <div className={styles.settingsMain}>
          <Panel>
            <PanelHeader title="Основное" />
            <PanelBody>
              <div className={styles.formStack}>
                <Field label="Название" required error={nameError} htmlFor="mode-name">
                  <Input
                    id="mode-name" value={name}
                    invalid={Boolean(nameError)}
                    onChange={(e) => setName(e.target.value)}
                  />
                </Field>
                <Field
                  label="Описание" hint="Коротко о назначении режима." htmlFor="mode-description"
                >
                  <Textarea
                    id="mode-description" rows={2}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </Field>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Системный промпт" actions={<span className={styles.promptMeta}>{systemPrompt.length} символов</span>}
            />
            <PanelBody>
              <div className={styles.formStack}>
                <Textarea
                  rows={14}
                  mono
                  value={systemPrompt}
                  invalid={Boolean(promptError)}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                />
                {promptError && <p className={styles.fieldError}>{promptError}</p>}
                <div className={styles.promptActions}>
                  <Button
                    size="sm" variant="ghost" iconLeft={<Zap />}
                    onClick={() => setSystemPrompt(DEFAULT_PROMPT)}
                  >
                    Вставить шаблон
                  </Button>
                  <Button
                    size="sm" variant="ghost" iconLeft={<RefreshCw />}
                    onClick={() => setSystemPrompt(mode.system_prompt)}
                    disabled={systemPrompt === mode.system_prompt}
                  >
                    Вернуть исходный
                  </Button>
                </div>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Модель" />
            <PanelBody>
              <OptionList
                value={responseModelId}
                onChange={setResponseModelId}
                options={models.map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: model.description,
                  meta: `${model.provider} · ${formatCompact(model.context_window)}`,
                }))}
              />
            </PanelBody>
          </Panel>
        </div>

        <div className={styles.settingsSide}>
          <Panel>
            <PanelHeader title="Оформление" />
            <PanelBody>
              <div className={styles.formStack}>
                <Field label="Цвет режима" hint="Видно в списках, чатах и на часах.">
                  <ColorSwatchRow value={color} onChange={setColor} />
                </Field>
                <div className={styles.previewCard} data-mode-color={color}>
                  <ModeDot color={color} size="md" />
                  <span className={styles.previewName}>{name || 'Режим'}</span>
                </div>
              </div>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Доступ с часов" />
            <PanelBody>
              <Switch
                checked={!hiddenOnWatch}
                onChange={(visible) => setHiddenOnWatch(!visible)}
                label="Показывать режим на часах" description="Скрытые режимы остаются в панели и на телефоне."
              />
              <div className={styles.watchPreview}>
                <Watch />
                <span>
                  {hiddenOnWatch
                    ? 'Режим не отображается на часах'
                    : 'Режим появится в списке на Wear OS'}
                </span>
              </div>
            </PanelBody>
          </Panel>

          <Panel tone="inset">
            <PanelBody>
              <div className={styles.dangerBlock}>
                <div className={styles.dangerHead}>
                  <AlertTriangle />
                  <span>Опасная зона</span>
                </div>
                <p className={styles.dangerText}>
                  Удаление режима уберёт его чаты и базу знаний. Сначала убедитесь, что нужные
                  документы есть в других режимах.
                </p>
                <Button variant="dangerGhost" iconLeft={<Trash2 />} onClick={handleDelete}>
                  Удалить режим
                </Button>
              </div>
            </PanelBody>
          </Panel>
        </div>
      </div>

      {dirty && (
        <div className={styles.saveBar}>
          <span className={styles.saveBarText}>
            <Eye /> Есть несохранённые изменения
          </span>
          <div className={styles.saveBarActions}>
            <Button variant="ghost" onClick={reset} disabled={saving}>
              Отменить
            </Button>
            <Button
              variant="primary" iconLeft={<Save />}
              onClick={save}
              loading={saving}
              disabled={Boolean(nameError || promptError)}
            >
              Сохранить
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
