'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowLeft, BookOpenText, Bot, Check, CircleAlert, Copy, Eye, EyeOff, FileImage,
  FileText, Gauge, HardDriveUpload, Layers3, MessageSquareText, MoreHorizontal,
  Plus, RefreshCw, RotateCcw, Save, Search, Server, Settings, Smartphone, Sparkles,
  SendHorizontal, Trash2, Upload, Watch, X,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import {
  type ApiChat,
  type ApiDevice,
  type ApiKnowledgeSourceDetail,
  type ApiJob,
  type ApiMessage,
  type ApiModel,
  type ApiSession,
  type JobStreamEvent,
  WristMindApi,
  WristMindApiError,
} from '@/lib/wristmind-api';

type Destination = 'overview' | 'chats' | 'modes' | 'knowledge' | 'settings';
type ProcessingMode = 'OCR' | 'VISION';
type SourceStatus = 'ready' | 'processing' | 'failed';
type ModeFormInput = { name: string; description: string; color: string; systemPrompt: string; modelId: string };

type Mode = {
  id: string;
  name: string;
  description: string;
  color: string;
  systemPrompt: string;
  modelId: string;
  hiddenOnWatch: boolean;
  sources: number;
};
type KnowledgeSource = {
  id: string;
  modeId: string;
  title: string;
  filename: string;
  mediaType: string;
  processingMode: ProcessingMode;
  status: SourceStatus;
  pages: number;
  chunks: number;
  tokens: number;
  updated: string;
  error?: string;
};

const destinations = [
  { id: 'overview' as const, label: 'Обзор', icon: Gauge },
  { id: 'chats' as const, label: 'Чаты', icon: MessageSquareText },
  { id: 'modes' as const, label: 'Режимы', icon: Layers3 },
  { id: 'knowledge' as const, label: 'База знаний', icon: BookOpenText },
  { id: 'settings' as const, label: 'Настройки', icon: Settings },
];
const HIDDEN_MODE_NAMES = new Set(['Быстрый чат']);

export function WristMindControlPanel() {
  const [hydrated, setHydrated] = useState(false);
  const [session, setSession] = useState<ApiSession | null>(null);
  const [destination, setDestination] = useState<Destination>('overview');
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [availableModes, setAvailableModes] = useState<Mode[]>([]);
  const [selectedModeId, setSelectedModeId] = useState('');
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [chats, setChats] = useState<ApiChat[]>([]);
  const [devices, setDevices] = useState<ApiDevice[]>([]);
  const [models, setModels] = useState<ApiModel[]>([]);
  const [globalPrompt, setGlobalPrompt] = useState('');
  const [historyMessageLimit, setHistoryMessageLimit] = useState(12);
  const [totalAiRequests, setTotalAiRequests] = useState(0);
  const [loading, setLoading] = useState(false);
  const [dashboardLoaded, setDashboardLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [chatDraftOpen, setChatDraftOpen] = useState(false);
  const selectedMode = availableModes.find((mode) => mode.id === selectedModeId) ?? availableModes[0];

  useEffect(() => {
    queueMicrotask(() => {
      const saved = window.localStorage.getItem('wristmind.web.session');
      if (saved) {
        try { setSession(JSON.parse(saved) as ApiSession); } catch { window.localStorage.removeItem('wristmind.web.session'); }
      }
      setHydrated(true);
    });
  }, []);

  const applyLocation = () => {
    const parts = window.location.pathname.split('/').filter(Boolean);
    const section = parts[0];
    const nextDestination: Destination = section === 'main' ? 'overview' : section === 'chats' ? 'chats' : section === 'modes' ? 'modes' : section === 'knowledge' ? 'knowledge' : section === 'settings' ? 'settings' : 'overview';
    setDestination(nextDestination);
    setSelectedChatId(section === 'chats' && parts[1] && parts[1] !== 'new' ? parts[1] : null);
    setChatDraftOpen(section === 'chats' && parts[1] === 'new');
  };

  useEffect(() => {
    if (!hydrated) return;
    queueMicrotask(applyLocation);
    window.addEventListener('popstate', applyLocation);
    return () => window.removeEventListener('popstate', applyLocation);
  }, [hydrated]);

  const navigate = (next: Destination, chatId?: string | null, draft = false) => {
    const path = next === 'overview' ? '/main' : next === 'chats' ? draft ? '/chats/new' : chatId ? `/chats/${chatId}` : '/chats' : `/${next}`;
    window.history.pushState({}, '', path);
    setDestination(next); setSelectedChatId(chatId ?? null); setChatDraftOpen(draft);
  };

  const refresh = async (currentSession = session) => {
    if (!currentSession) return;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await new WristMindApi(currentSession.baseUrl, currentSession.token).dashboard();
      const nextModes = data.modes.filter((mode) => !HIDDEN_MODE_NAMES.has(mode.name)).map((mode) => ({
        id: mode.id,
        name: mode.name,
        description: mode.description,
        color: mode.color,
        systemPrompt: mode.system_prompt,
        modelId: mode.response_model_id,
        hiddenOnWatch: mode.hidden_on_watch,
        sources: data.knowledge.filter((source) => source.mode_id === mode.id).length,
      }));
      const nextSources = data.knowledge.map((source) => ({
        id: source.id,
        modeId: source.mode_id,
        title: source.title,
        filename: source.filename,
        mediaType: source.media_type,
        processingMode: source.processing_mode,
        status: source.status === 'ready' ? 'ready' as const : source.status === 'failed' ? 'failed' as const : 'processing' as const,
        pages: source.page_count,
        chunks: source.chunk_count,
        tokens: source.token_count,
        updated: formatDate(source.created_at),
        error: source.error ?? undefined,
      }));
      setAvailableModes(nextModes);
      setSources(nextSources);
      setChats(data.chats);
      setDevices(data.devices.filter((device) => !device.revoked_at));
      setModels(data.models);
      setGlobalPrompt(data.globalPrompt);
      setHistoryMessageLimit(data.historyMessageLimit);
      setTotalAiRequests(data.totalAiRequests);
      setSelectedModeId((current) => nextModes.some((mode) => mode.id === current) ? current : nextModes[0]?.id ?? '');
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить данные');
    } finally {
      setLoading(false);
      setDashboardLoaded(true);
    }
  };

  useEffect(() => { if (session) queueMicrotask(() => void refresh(session)); }, [session]);
  if (!hydrated) return <LoadingPanel />;
  if (!session) {
    return <EnrollmentScreen onEnrolled={(nextSession) => {
      window.localStorage.setItem('wristmind.web.session', JSON.stringify(nextSession));
      setSession(nextSession);
    }} />;
  }

  const api = new WristMindApi(session.baseUrl, session.token);
  const disconnect = () => {
    window.localStorage.removeItem('wristmind.web.session');
    setSession(null);
  };
  const startQuickChat = async () => {
    setLoadError(null);
    try {
      const chat = await api.createQuickChat();
      await refresh();
      navigate('chats', chat.id);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Не удалось создать быстрый чат');
    }
  };
  const handleDeleteChat = async (chatId: string) => {
    await api.deleteChat(chatId);
    await refresh();
    navigate('chats');
  };
  const handleDeleteMode = async (modeId: string) => {
    await api.deleteMode(modeId);
    await refresh();
    navigate('modes');
  };

  return (
    <div className={cn('min-h-[100svh] bg-background/92 lg:grid lg:grid-cols-[240px_minmax(0,1fr)]', destination === 'chats' && selectedChatId && 'h-[100dvh] overflow-hidden')}>
      <AppSidebar destination={destination} onNavigate={(next) => navigate(next)} serverLabel={session.baseUrl} />
      <div className={cn('min-w-0 pb-[calc(4.5rem+env(safe-area-inset-bottom))] lg:pb-0', destination === 'chats' && selectedChatId && 'flex h-[100dvh] min-h-0 flex-col overflow-hidden pb-0')}>
        <StatusBar loading={loading} error={loadError} onRefresh={() => void refresh()} />
        <main className={cn('mx-auto w-full max-w-[1440px] px-3 py-4 sm:px-6 sm:py-7 lg:px-8', destination === 'chats' && selectedChatId && 'min-h-0 flex-1 overflow-hidden')}>
          {!dashboardLoaded ? <LoadingPanel /> : destination === 'knowledge' ? selectedMode ? (
            <KnowledgePage
              modes={availableModes}
              selectedMode={selectedMode}
              onModeChange={setSelectedModeId}
              sources={sources}
              uploadOpen={uploadOpen}
              onUploadOpenChange={setUploadOpen}
              onUpload={async (input) => {
                await api.uploadKnowledge(input);
                await refresh();
              }}
              onDelete={async (sourceId) => {
                await api.deleteKnowledge(sourceId);
                await refresh();
              }}
              onLoadDetail={(sourceId, offset) => api.knowledgeSource(sourceId, offset)}
              onReprocess={async (sourceId) => {
                await api.reprocessKnowledge(sourceId);
                await refresh();
              }}
            />
          ) : <EmptyKnowledgeWorkspace onCreateMode={() => setDestination('modes')} /> : <PlaceholderPage
            destination={destination}
            modes={availableModes}
            chats={chats}
            devices={devices}
            models={models}
            globalPrompt={globalPrompt}
            historyMessageLimit={historyMessageLimit}
            totalAiRequests={totalAiRequests}
            onCreatePairingCode={() => api.createPairingCode()}
            onDisconnect={disconnect}
            onCreateChat={async (modeId, title) => { const chat = await api.createChat(modeId, title); await refresh(); return chat; }}
            onCreateQuickChat={startQuickChat}
            onLoadMessages={(chatId) => api.messages(chatId)}
            onSendMessage={(chatId, text) => api.sendMessage(chatId, text)}
            onStreamJob={(jobId, onEvent, signal) => api.streamJob(jobId, onEvent, signal)}
            onRefreshChats={() => refresh()}
            onDeleteChat={handleDeleteChat}
            chatDraftOpen={chatDraftOpen}
            selectedChatId={selectedChatId}
            onChatDraftChange={(open) => navigate('chats', null, open)}
            onSelectChat={(chatId) => navigate('chats', chatId)}
            onStartChat={() => navigate('chats', null, true)}
            onCreateMode={async (input) => { await api.createMode(input); await refresh(); }}
            onUpdateMode={async (modeId, input) => { await api.updateMode(modeId, input); await refresh(); }}
            onSetWatchVisibility={async (modeId, hidden) => { await api.setModeHiddenOnWatch(modeId, hidden); await refresh(); }}
            onDeleteMode={handleDeleteMode}
            onSavePrompt={async (prompt) => { await api.updateGlobalPrompt(prompt); await refresh(); }}
            onSaveHistoryLimit={async (limit) => { await api.updateSettings({ history_message_limit: limit }); await refresh(); }}
          />}
        </main>
      </div>
      {!(destination === 'chats' && selectedChatId) && <MobileNavigation destination={destination} onNavigate={(next) => navigate(next)} />}
    </div>
  );
}

function AppSidebar({ destination, onNavigate, serverLabel }: {
  destination: Destination;
  onNavigate: (destination: Destination) => void;
  serverLabel: string;
}) {
  return (
    <aside className="sticky top-0 hidden h-dvh border-r bg-sidebar/95 p-3 backdrop-blur lg:flex lg:flex-col">
      <div className="flex h-14 items-center gap-3 px-2">
        <div className="grid size-8 place-items-center rounded-lg border border-primary/30 bg-primary/10 p-1">
          <span className="size-full bg-[url(/wristmind-mark.svg)] bg-contain bg-center bg-no-repeat" aria-hidden="true" />
        </div>
        <div>
          <div className="text-sm font-semibold tracking-tight">WristMind</div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">control center</div>
        </div>
      </div>
      <nav className="mt-6 space-y-1" aria-label="Основная навигация">
        {destinations.map((item) => {
          const Icon = item.icon;
          const active = item.id === destination;
          return (
            <button
              key={item.id} type="button" onClick={() => onNavigate(item.id)}
              className={cn(
                'flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                active && 'bg-sidebar-accent text-sidebar-accent-foreground',
                !active && 'hover:bg-sidebar-accent/55 hover:text-foreground',
              )}
            >
              <Icon className={cn('size-4', active && 'text-primary')} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="mt-auto border-t pt-3">
        <div className="flex items-center gap-3 rounded-lg px-3 py-2">
          <div className="relative grid size-8 place-items-center rounded-lg bg-muted text-muted-foreground">
            <Bot className="size-4" />
            <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-sidebar bg-emerald-400" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">Панель владельца</div>
            <div className="max-w-32 truncate font-mono text-[10px] text-muted-foreground" title={serverLabel}>{serverLabel.replace(/^https?:\/\//, '')}</div>
          </div>
          <MoreHorizontal className="ml-auto size-4 text-muted-foreground" aria-hidden="true" />
        </div>
      </div>
    </aside>
  );
}

function StatusBar({ loading, error, onRefresh }: { loading: boolean; error: string | null; onRefresh: () => void }) {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/88 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-2 lg:hidden">
          <div className="grid size-7 place-items-center rounded-md bg-primary/12 p-1"><span className="size-full bg-[url(/wristmind-mark.svg)] bg-contain bg-center bg-no-repeat" aria-hidden="true" /></div>
          <span className="text-sm font-semibold">WristMind</span>
        </div>
        <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
          <Activity className="size-3.5 text-primary" aria-hidden="true" />
          <span>{error ?? 'Все системы отслеживаются автоматически'}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <ConnectionState icon={Server} label="VPS" connected={!error} />
          <ConnectionState icon={Smartphone} label="Телефон" connected />
          <ConnectionState icon={Watch} label="Часы" connected={false} />
          <Button variant="ghost" size="icon-sm" aria-label="Обновить состояния" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={cn(loading && 'animate-spin')} />
          </Button>
        </div>
      </div>
    </header>
  );
}

function ConnectionState({ icon: Icon, label, connected }: {
  icon: typeof Server; label: string; connected: boolean;
}) {
  return (
    <div className="flex h-7 items-center gap-1.5 rounded-md border bg-card/70 px-2 text-[11px]">
      <Icon className="size-3.5 text-muted-foreground" aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
      <span className={cn('size-1.5 rounded-full', connected ? 'bg-emerald-400' : 'bg-amber-400')} aria-label={connected ? 'подключено' : 'ожидание'} />
    </div>
  );
}

function KnowledgePage({ modes, selectedMode, onModeChange, sources, uploadOpen, onUploadOpenChange, onUpload, onDelete, onLoadDetail, onReprocess }: {
  modes: Mode[]; selectedMode: Mode; onModeChange: (modeId: string) => void;
  sources: KnowledgeSource[];
  uploadOpen: boolean; onUploadOpenChange: (open: boolean) => void;
  onUpload: (input: { modeId: string; processingMode: ProcessingMode; title: string; file: File }) => Promise<void>;
  onDelete: (sourceId: string) => Promise<void>;
  onLoadDetail: (sourceId: string, offset?: number) => Promise<ApiKnowledgeSourceDetail>;
  onReprocess: (sourceId: string) => Promise<void>;
}) {
  const [query, setQuery] = useState('');
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ApiKnowledgeSourceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<KnowledgeSource | null>(null);
  const [deleting, setDeleting] = useState(false);
  const modeSources = useMemo(() => sources.filter((source) =>
    source.modeId === selectedMode.id && `${source.title} ${source.filename}`.toLowerCase().includes(query.toLowerCase()),
  ), [query, selectedMode.id, sources]);
  const totalTokens = modeSources.reduce((sum, source) => sum + source.tokens, 0);
  const ready = modeSources.filter((source) => source.status === 'ready').length;

  const openSource = async (sourceId: string) => {
    setSelectedSourceId(sourceId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try { setDetail(await onLoadDetail(sourceId, 0)); }
    catch (cause) { setDetailError(cause instanceof Error ? cause.message : 'Не удалось открыть источник'); }
    finally { setDetailLoading(false); }
  };

  const selectedSource = sources.find((source) => source.id === selectedSourceId);
  if (selectedSourceId && selectedSource) {
    return <>
      <SourceDetailView
        source={selectedSource}
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onBack={() => { setSelectedSourceId(null); setDetail(null); setDetailError(null); }}
        onRetryLoad={() => void openSource(selectedSourceId)}
        onLoadMore={async () => {
          if (!detail) return;
          setDetailLoading(true);
          try {
            const next = await onLoadDetail(selectedSourceId, detail.chunks.length);
            setDetail({ ...next, chunks: [...detail.chunks, ...next.chunks] });
          } catch (cause) {
            setDetailError(cause instanceof Error ? cause.message : 'Не удалось загрузить продолжение');
          } finally { setDetailLoading(false); }
        }}
        onReprocess={async () => {
          setDetailLoading(true); setDetailError(null);
          try { await onReprocess(selectedSourceId); setDetail(await onLoadDetail(selectedSourceId, 0)); }
          catch (cause) { setDetailError(cause instanceof Error ? cause.message : 'Не удалось запустить обработку'); }
          finally { setDetailLoading(false); }
        }}
        onDelete={() => setDeleteCandidate(selectedSource)}
      />
      <DeleteSourceDialog
        source={deleteCandidate}
        deleting={deleting}
        onOpenChange={(open) => { if (!open && !deleting) setDeleteCandidate(null); }}
        onConfirm={async () => {
          if (!deleteCandidate) return;
          setDeleting(true);
          try {
            await onDelete(deleteCandidate.id);
            setDeleteCandidate(null);
            setSelectedSourceId(null);
            setDetail(null);
          } finally { setDeleting(false); }
        }}
      />
    </>;
  }

  return (
    <section aria-labelledby="knowledge-title" className="animate-in fade-in duration-300">
      <div className="flex flex-col gap-5 border-b pb-6 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <span className="size-1.5 rounded-full" style={{ backgroundColor: selectedMode.color }} />
            Изолированное пространство режима
          </div>
          <h1 id="knowledge-title" className="text-2xl font-semibold tracking-tight sm:text-[28px]">База знаний</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
            Источники не смешиваются между режимами. Для каждого документа способ обработки выбирается отдельно.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select
            value={selectedMode.id}
            onValueChange={(value) => onModeChange(value as string)}
            itemToStringLabel={(value) => modes.find((mode) => mode.id === value)?.name ?? ''}
          >
            <SelectTrigger className="h-9 w-full max-sm:h-11 sm:w-[210px]" aria-label="Выбрать режим"><SelectValue /></SelectTrigger>
            <SelectContent>
              {modes.map((mode) => (
                <SelectItem key={mode.id} value={mode.id}>
                  <span className="size-2 rounded-full" style={{ backgroundColor: mode.color }} />
                  {mode.name}
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {sources.filter((source) => source.modeId === mode.id).length}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button className="h-9 w-full max-sm:h-11 sm:w-auto" onClick={() => onUploadOpenChange(true)}><Plus data-icon="inline-start" />Добавить источник</Button>
        </div>
      </div>

      <div className="grid border-b sm:grid-cols-3">
        <SummaryItem label="Источники" value={`${modeSources.length}`} detail={`${ready} готовы`} />
        <SummaryItem label="Объём контекста" value={formatTokens(totalTokens)} detail="RAG включается по порогу" />
        <SummaryItem label="Текущий режим" value={selectedMode.name} detail="данные изолированы" color={selectedMode.color} />
      </div>

      <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти источник" aria-label="Поиск по источникам" className="h-9 pl-8 max-sm:h-11" />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground sm:ml-auto">
          <span className="size-1.5 rounded-full bg-emerald-400" />Последняя синхронизация сейчас
        </div>
      </div>

      {modeSources.length ? (
        <>
          <div className="hidden overflow-hidden rounded-lg border bg-card/60 md:block"><SourcesTable sources={modeSources} onOpen={(sourceId) => void openSource(sourceId)} onDelete={setDeleteCandidate} /></div>
          <div className="space-y-2 md:hidden">{modeSources.map((source) => <MobileSource key={source.id} source={source} onOpen={(sourceId) => void openSource(sourceId)} onDelete={setDeleteCandidate} />)}</div>
        </>
      ) : <EmptyKnowledge mode={selectedMode} onUpload={() => onUploadOpenChange(true)} />}

      <UploadKnowledgeDialog key={selectedMode.id} open={uploadOpen} onOpenChange={onUploadOpenChange} modes={modes} initialModeId={selectedMode.id} onUpload={onUpload} />
      <DeleteSourceDialog
        source={deleteCandidate}
        deleting={deleting}
        onOpenChange={(open) => { if (!open && !deleting) setDeleteCandidate(null); }}
        onConfirm={async () => {
          if (!deleteCandidate) return;
          setDeleting(true);
          try { await onDelete(deleteCandidate.id); setDeleteCandidate(null); }
          finally { setDeleting(false); }
        }}
      />
    </section>
  );
}

function EmptyKnowledgeWorkspace({ onCreateMode }: { onCreateMode: () => void }) {
  return (
    <section aria-labelledby="empty-knowledge-title" className="animate-in fade-in duration-300">
      <div className="border-b pb-6">
        <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Чистая установка</div>
        <h1 id="empty-knowledge-title" className="text-2xl font-semibold tracking-tight sm:text-[28px]">База знаний пока пуста</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Сначала создайте рабочий режим. После этого в нём можно будет добавлять документы и выбирать OCR или Vision для каждого источника.</p>
      </div>
      <div className="mt-6 flex min-h-48 items-center rounded-lg border border-dashed bg-card/30 p-5">
        <div>
          <Layers3 className="size-5 text-primary" aria-hidden="true" />
          <h2 className="mt-3 text-sm font-medium">Создайте первый режим</h2>
          <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">Режим закрепляет модель, системный промпт и отдельную базу знаний для будущих чатов.</p>
          <Button className="mt-4" onClick={onCreateMode}><Plus />Создать режим</Button>
        </div>
      </div>
    </section>
  );
}

function SummaryItem({ label, value, detail, color }: { label: string; value: string; detail: string; color?: string }) {
  return (
    <div className="border-b py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:px-5 sm:first:pl-0 sm:last:border-r-0">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-center gap-2 text-lg font-semibold">
        {color && <span className="size-2 rounded-full" style={{ backgroundColor: color }} />}{value}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function SourcesTable({ sources, onOpen, onDelete }: {
  sources: KnowledgeSource[];
  onOpen: (sourceId: string) => void;
  onDelete: (source: KnowledgeSource) => void;
}) {
  return (
    <Table>
      <TableHeader><TableRow className="bg-muted/35 hover:bg-muted/35">
        <TableHead className="pl-4">Источник</TableHead><TableHead>Обработка</TableHead><TableHead>Состояние</TableHead>
        <TableHead className="text-right">Объём</TableHead><TableHead>Обновлён</TableHead><TableHead className="w-12"><span className="sr-only">Действия</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>{sources.map((source) => (
        <TableRow
          key={source.id}
          tabIndex={0}
          onClick={() => onOpen(source.id)}
          onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(source.id); } }}
          className="group cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          aria-label={`Открыть источник: ${source.title}`}
        >
          <TableCell className="max-w-[360px] py-3 pl-4"><div className="flex items-center gap-3"><FileTypeIcon source={source} /><div className="min-w-0">
            <div className="block max-w-full truncate text-left font-medium group-hover:text-primary" title={source.title}>{source.title}</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground" title={source.filename}>{source.filename}</div>
          </div></div></TableCell>
          <TableCell><ProcessingBadge mode={source.processingMode} /></TableCell>
          <TableCell><StatusBadge source={source} /></TableCell>
          <TableCell className="text-right font-mono text-xs text-muted-foreground">{source.pages} стр. · {source.chunks} фрагм.</TableCell>
          <TableCell className="text-xs text-muted-foreground">{source.updated}</TableCell>
          <TableCell><Button variant="ghost" size="icon-sm" aria-label={`Удалить: ${source.title}`} onClick={(event) => { event.stopPropagation(); onDelete(source); }}><Trash2 /></Button></TableCell>
        </TableRow>
      ))}</TableBody>
    </Table>
  );
}

function MobileSource({ source, onOpen, onDelete }: {
  source: KnowledgeSource;
  onOpen: (sourceId: string) => void;
  onDelete: (source: KnowledgeSource) => void;
}) {
  return (
    <article className="relative rounded-lg border bg-card/70 p-3 transition-colors hover:border-primary/40 hover:bg-primary/5">
      <button type="button" onClick={() => onOpen(source.id)} className="w-full cursor-pointer pr-9 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="flex items-start gap-3"><FileTypeIcon source={source} /><div className="min-w-0 flex-1">
        <div className="break-words text-sm font-medium hover:text-primary">{source.title}</div>
        <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">{source.filename}</p>
      </div></div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
        <ProcessingBadge mode={source.processingMode} /><StatusBadge source={source} />
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{source.pages} стр. · {source.chunks} фрагм.</span>
      </div>
      {source.error && <p className="mt-2 text-xs leading-5 text-destructive">{source.error}</p>}
      </button>
      <Button className="absolute right-2 top-2" variant="ghost" size="icon-sm" aria-label={`Удалить: ${source.title}`} onClick={() => onDelete(source)}><Trash2 /></Button>
    </article>
  );
}

function SourceDetailView({ source, detail, loading, error, onBack, onRetryLoad, onLoadMore, onReprocess, onDelete }: {
  source: KnowledgeSource;
  detail: ApiKnowledgeSourceDetail | null;
  loading: boolean;
  error: string | null;
  onBack: () => void;
  onRetryLoad: () => void;
  onLoadMore: () => Promise<void>;
  onReprocess: () => Promise<void>;
  onDelete: () => void;
}) {
  const outputLabel = source.processingMode === 'VISION' ? 'Ответ Vision-модели' : 'Распознанный текст';
  const processing = source.status === 'processing';
  return (
    <section aria-labelledby="source-detail-title" className="animate-in fade-in duration-200">
      <button type="button" onClick={onBack} className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft className="size-4" />Назад к источникам
      </button>
      <div className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2"><ProcessingBadge mode={source.processingMode} /><StatusBadge source={source} /></div>
          <h1 id="source-detail-title" className="break-words text-2xl font-semibold tracking-tight sm:text-[28px]">{source.title}</h1>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{source.filename}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void onReprocess()} disabled={loading || processing}><RotateCcw className={cn(loading && 'animate-spin')} />Обработать заново</Button>
          <Button variant="destructive" onClick={onDelete} disabled={loading}><Trash2 />Удалить</Button>
        </div>
      </div>

      <div className="grid gap-6 py-6 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="h-fit rounded-lg border bg-card/55">
          <div className="border-b px-4 py-3 text-sm font-medium">Сведения</div>
          <dl className="divide-y text-xs">
            <DetailTerm label="Режим обработки" value={source.processingMode === 'VISION' ? 'Vision-модель' : 'Оцифровка OCR'} />
            <DetailTerm label="Тип файла" value={source.mediaType} mono />
            <DetailTerm label="Страницы" value={`${detail?.page_count ?? source.pages}`} />
            <DetailTerm label="Фрагменты" value={`${detail?.chunk_count ?? source.chunks}`} />
            <DetailTerm label="Токены" value={formatTokens(detail?.token_count ?? source.tokens)} />
            <DetailTerm label="Добавлен" value={source.updated} />
          </dl>
        </aside>

        <div className="min-w-0">
          <div className="flex items-center justify-between border-b pb-3">
            <div><h2 className="text-sm font-medium">{outputLabel}</h2><p className="mt-0.5 text-xs text-muted-foreground">Именно эти данные добавлены в контекст режима.</p></div>
            {detail && <span className="font-mono text-[10px] text-muted-foreground">{detail.chunks.length} / {detail.chunk_count}</span>}
          </div>

          {loading && !detail ? <div className="mt-4 flex min-h-48 items-center justify-center rounded-lg border bg-card/35 text-sm text-muted-foreground"><RefreshCw className="mr-2 size-4 animate-spin text-primary" />Загружаю результат обработки…</div>
            : error && !detail ? <div role="alert" className="mt-4 rounded-lg border border-destructive/30 bg-destructive/8 p-4"><div className="text-sm font-medium text-destructive">Не удалось открыть источник</div><p className="mt-1 text-xs text-muted-foreground">{error}</p><Button variant="outline" className="mt-3" onClick={onRetryLoad}>Повторить</Button></div>
              : detail?.chunks.length ? <div className="mt-4 space-y-3">{detail.chunks.map((chunk) => <article key={chunk.id} className="overflow-hidden rounded-lg border bg-card/45">
                <div className="flex flex-wrap items-center gap-2 border-b bg-muted/25 px-3 py-2 font-mono text-[10px] text-muted-foreground"><span>Фрагмент {chunk.ordinal + 1}</span>{chunk.page_from && <span>· стр. {chunk.page_from}{chunk.page_to && chunk.page_to !== chunk.page_from ? `–${chunk.page_to}` : ''}</span>}<span className="ml-auto">{chunk.token_count} токенов</span></div>
                <pre className="whitespace-pre-wrap break-words p-4 font-sans text-sm leading-6 text-foreground">{chunk.content}</pre>
              </article>)}
                {detail.has_more && <Button variant="outline" className="w-full" onClick={() => void onLoadMore()} disabled={loading}>{loading ? 'Загрузка…' : 'Показать следующие 50 фрагментов'}</Button>}
              </div>
                : <div className="mt-4 grid min-h-48 place-items-center rounded-lg border border-dashed bg-card/30 p-6 text-center"><div><FileText className="mx-auto size-5 text-muted-foreground" /><div className="mt-3 text-sm font-medium">Результата пока нет</div><p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{source.status === 'failed' ? source.error ?? 'Обработка завершилась ошибкой.' : 'Источник ещё обрабатывается. Обновите состояние чуть позже.'}</p></div></div>}
          {error && detail && <div role="alert" className="mt-3 text-xs text-destructive">{error}</div>}
        </div>
      </div>
    </section>
  );
}

function DetailTerm({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="grid gap-1 px-4 py-3"><dt className="text-muted-foreground">{label}</dt><dd className={cn('break-words text-foreground', mono && 'font-mono text-[10px]')}>{value}</dd></div>;
}

function DeleteModeDialog({ mode, deleting, onOpenChange, onConfirm }: {
  mode: Mode | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    setError(null);
    try { await onConfirm(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось удалить режим'); }
  };
  return <Dialog open={Boolean(mode)} onOpenChange={(open) => { if (!open) setError(null); onOpenChange(open); }}>
    <DialogContent>
      <DialogHeader><DialogTitle>Удалить режим?</DialogTitle><DialogDescription>Режим <span className="break-words">«{mode?.name}»</span> и его источники будут скрыты из панели. Уже созданные чаты сохранят историю и название режима. Отменить это действие нельзя.</DialogDescription></DialogHeader>
      {mode && <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-3"><div className="grid size-9 shrink-0 place-items-center rounded-md border" style={{ backgroundColor: `${mode.color}18`, color: mode.color }}><Sparkles className="size-4" /></div><div className="min-w-0"><div className="truncate text-sm font-medium">{mode.name}</div><div className="font-mono text-[10px] text-muted-foreground">{mode.sources} источников · отдельная база знаний</div></div></div>}
      {error && <div role="alert" className="text-xs text-destructive">{error}</div>}
      <DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>Отмена</Button><Button type="button" variant="destructive" onClick={() => void confirm()} disabled={deleting}><Trash2 />{deleting ? 'Удаление…' : 'Удалить режим'}</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}

function DeleteSourceDialog({ source, deleting, onOpenChange, onConfirm }: {
  source: KnowledgeSource | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    setError(null);
    try { await onConfirm(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось удалить источник'); }
  };
  return <Dialog open={Boolean(source)} onOpenChange={(open) => { if (!open) setError(null); onOpenChange(open); }}>
    <DialogContent>
      <DialogHeader><DialogTitle>Удалить источник?</DialogTitle><DialogDescription>Документ <span className="break-words">«{source?.title}»</span> и все извлечённые фрагменты будут удалены из базы режима. Отменить это действие нельзя.</DialogDescription></DialogHeader>
      {source && <div className="flex min-w-0 max-w-full items-center gap-3 overflow-hidden rounded-lg border bg-muted/30 p-3"><FileTypeIcon source={source} /><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{source.title}</div><div className="truncate font-mono text-[10px] text-muted-foreground">{source.filename}</div></div></div>}
      {error && <div role="alert" className="text-xs text-destructive">{error}</div>}
      <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>Отмена</Button><Button variant="destructive" onClick={() => void confirm()} disabled={deleting}><Trash2 />{deleting ? 'Удаление…' : 'Удалить источник'}</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}

function DeleteChatDialog({ chat, deleting, onOpenChange, onConfirm }: {
  chat: ApiChat | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    setError(null);
    try { await onConfirm(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось удалить чат'); }
  };
  return <Dialog open={Boolean(chat)} onOpenChange={(open) => { if (!open) setError(null); onOpenChange(open); }}>
    <DialogContent>
      <DialogHeader><DialogTitle>Удалить чат?</DialogTitle><DialogDescription>История чата <span className="break-words">«{chat?.title}»</span> будет скрыта. Отменить это действие нельзя.</DialogDescription></DialogHeader>
      {chat && <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-3"><div className="grid size-9 shrink-0 place-items-center rounded-md border bg-muted/45"><MessageSquareText className="size-4 text-muted-foreground" /></div><div className="min-w-0"><div className="truncate text-sm font-medium">{chat.title}</div><div className="truncate font-mono text-[10px] text-muted-foreground">{chat.mode_name}</div></div></div>}
      {error && <div role="alert" className="text-xs text-destructive">{error}</div>}
      <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>Отмена</Button><Button variant="destructive" onClick={() => void confirm()} disabled={deleting}><Trash2 />{deleting ? 'Удаление…' : 'Удалить чат'}</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}

function FileTypeIcon({ source }: { source: KnowledgeSource }) {
  const Icon = source.filename.match(/\.(jpg|jpeg|png|webp)$/i) ? FileImage : FileText;
  return <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-muted/45 text-muted-foreground"><Icon className="size-4" /></div>;
}

function ProcessingBadge({ mode }: { mode: ProcessingMode }) {
  return <Badge variant="outline" className="rounded-md font-mono text-[10px]">{mode === 'OCR' ? <FileText /> : <Sparkles />}{mode}</Badge>;
}

function StatusBadge({ source }: { source: KnowledgeSource }) {
  if (source.status === 'ready') return <Badge className="rounded-md bg-emerald-400/12 text-emerald-300"><Check />Готово</Badge>;
  if (source.status === 'processing') return <Badge className="rounded-md bg-sky-400/12 text-sky-300"><RefreshCw className="animate-spin" />Обработка</Badge>;
  return <Badge variant="destructive" className="rounded-md"><CircleAlert />Ошибка</Badge>;
}

function EmptyKnowledge({ mode, onUpload }: { mode: Mode; onUpload: () => void }) {
  return (
    <div className="grid min-h-[300px] place-items-center rounded-lg border border-dashed bg-card/35 p-6 text-center"><div className="max-w-sm">
      <div className="mx-auto grid size-11 place-items-center rounded-lg border bg-muted/50 text-muted-foreground"><BookOpenText className="size-5" /></div>
      <h2 className="mt-4 font-semibold">У режима «{mode.name}» пока нет источников</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">Добавьте PDF или изображение. Оно будет доступно только этому режиму.</p>
      <Button className="mt-4" onClick={onUpload}><Upload />Загрузить документ</Button>
    </div></div>
  );
}

function UploadKnowledgeDialog({ open, onOpenChange, modes, initialModeId, onUpload }: {
  open: boolean; onOpenChange: (open: boolean) => void; modes: Mode[]; initialModeId: string;
  onUpload: (input: { modeId: string; processingMode: ProcessingMode; title: string; file: File }) => Promise<void>;
}) {
  const [modeId, setModeId] = useState(initialModeId);
  const [processingMode, setProcessingMode] = useState<ProcessingMode | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedMode = modes.find((mode) => mode.id === modeId);
  const canSubmit = Boolean(modeId && processingMode && file && !submitting);
  const close = (nextOpen: boolean) => {
    onOpenChange(nextOpen);
    if (!nextOpen) { setProcessingMode(null); setFile(null); setSubmitError(null); }
  };
  const submit = async () => {
    if (!file || !processingMode || !selectedMode) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await onUpload({
        modeId,
        title: file.name.replace(/\.[^.]+$/, '').replaceAll('_', ' '),
        processingMode,
        file,
      });
      close(false);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Не удалось загрузить документ');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-sm:grid-rows-[auto_minmax(0,1fr)_auto] max-sm:gap-3 max-sm:overflow-hidden sm:max-w-[560px]">
        <DialogHeader><DialogTitle>Добавить источник знаний</DialogTitle><DialogDescription>
          Режим и способ обработки сохраняются вместе с документом и не применяются глобально.
        </DialogDescription></DialogHeader>
        <div className="grid gap-5 py-1 max-sm:min-h-0 max-sm:overflow-y-auto max-sm:pr-1">
          <div className="grid gap-1.5 text-sm font-medium"><span>Режим <span className="sr-only">обязательное поле</span></span>
            <Select
              value={modeId}
              onValueChange={(value) => setModeId(value as string)}
              itemToStringLabel={(value) => modes.find((mode) => mode.id === value)?.name ?? ''}
            >
              <SelectTrigger className="h-9 w-full max-sm:h-11"><SelectValue /></SelectTrigger>
              <SelectContent>{modes.map((mode) => <SelectItem key={mode.id} value={mode.id}>
                <span className="size-2 rounded-full" style={{ backgroundColor: mode.color }} />{mode.name}
              </SelectItem>)}</SelectContent>
            </Select>
            <span className="text-xs font-normal text-muted-foreground">Документ попадёт только в базу выбранного режима.</span>
          </div>
          <fieldset><legend className="text-sm font-medium">Как обработать документ</legend><div className="mt-2 grid gap-2 sm:grid-cols-2">
            <ProcessingOption active={processingMode === 'OCR'} icon={FileText} title="Оцифровка" description="Текстовые PDF, книги и чёткие сканы" onClick={() => setProcessingMode('OCR')} />
            <ProcessingOption active={processingMode === 'VISION'} icon={Sparkles} title="Vision-модель" description="Фото задач, схемы, таблицы и рисунки" onClick={() => setProcessingMode('VISION')} />
          </div></fieldset>
          <div><div className="mb-2 text-sm font-medium">Файл</div>
            <input ref={inputRef} type="file" accept="application/pdf,image/jpeg,image/png,image/webp" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            {file ? (
              <div className="flex items-center gap-3 rounded-lg border bg-muted/35 p-3">
                <FileTypeIcon source={{ id: 'preview', modeId, title: file.name, filename: file.name, mediaType: file.type, processingMode: processingMode ?? 'OCR', status: 'processing', pages: 0, chunks: 0, tokens: 0, updated: '' }} />
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{file.name}</div><div className="font-mono text-[10px] text-muted-foreground">{(file.size / 1024 / 1024).toFixed(1)} МБ</div></div>
                <Button variant="ghost" size="icon-sm" onClick={() => setFile(null)} aria-label="Убрать файл"><X /></Button>
              </div>
            ) : (
              <button type="button" onClick={() => inputRef.current?.click()} className="grid min-h-28 w-full place-items-center rounded-lg border border-dashed bg-muted/20 p-4 text-center transition-colors hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span><HardDriveUpload className="mx-auto size-5 text-muted-foreground" /><span className="mt-2 block text-sm font-medium">Выбрать PDF или изображение</span><span className="mt-1 block text-xs text-muted-foreground">до 50 МБ</span></span>
              </button>
            )}
          </div>
          {submitError && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-xs text-destructive">{submitError}</div>}
        </div>
        <DialogFooter><Button variant="outline" onClick={() => close(false)} disabled={submitting}>Отмена</Button><Button disabled={!canSubmit} onClick={() => void submit()}><Upload /><span className="sm:hidden">{submitting ? 'Загрузка…' : 'Добавить документ'}</span><span className="hidden min-w-0 truncate sm:inline">{submitting ? 'Загрузка…' : `Добавить в «${selectedMode?.name ?? 'режим'}»`}</span></Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProcessingOption({ active, icon: Icon, title, description, onClick }: {
  active: boolean; icon: typeof FileText; title: string; description: string; onClick: () => void;
}) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick} className={cn(
      'relative min-h-24 rounded-lg border p-3 text-left transition-colors hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      active && 'border-primary/60 bg-primary/8',
    )}>
      <div className="flex items-start gap-3"><div className={cn('grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground', active && 'bg-primary/15 text-primary')}><Icon className="size-4" /></div>
        <div><div className="text-sm font-medium">{title}</div><div className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</div></div>
      </div>{active && <Check className="absolute right-2 top-2 size-3.5 text-primary" />}
    </button>
  );
}

function LoadingPanel() {
  return (
    <main className="grid min-h-dvh place-items-center bg-background p-6">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <RefreshCw className="size-4 animate-spin text-primary" />
        Загрузка панели WristMind…
      </div>
    </main>
  );
}

function EnrollmentScreen({ onEnrolled }: { onEnrolled: (session: ApiSession) => void }) {
  const [baseUrl, setBaseUrl] = useState(() => typeof window === 'undefined' ? 'https://wm.xspase.ru' : window.location.origin);
  const [method, setMethod] = useState<'code' | 'secret'>('code');
  const [code, setCode] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enroll = async () => {
    setBusy(true);
    setError(null);
    try {
      const api = new WristMindApi(baseUrl);
      await api.health();
      onEnrolled(await (method === 'code' ? api.enrollWebWithPairingCode(code) : api.enrollWeb(secret)));
    } catch (cause) {
      if (cause instanceof WristMindApiError && cause.status === 0) {
        setError(`${cause.message} Если панель открыта по HTTPS, сервер тоже должен использовать HTTPS.`);
      } else {
        setError(cause instanceof Error ? cause.message : 'Не удалось подключить панель');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-10">
      <section className="w-full max-w-[460px] rounded-xl border bg-card/85 p-5 backdrop-blur sm:p-7" aria-labelledby="enrollment-title">
        <div className="flex items-center gap-3 border-b pb-5">
          <div className="grid size-10 place-items-center rounded-lg border border-primary/30 bg-primary/10 p-1.5"><span className="size-full bg-[url(/wristmind-mark.svg)] bg-contain bg-center bg-no-repeat" aria-hidden="true" /></div>
          <div><div className="font-semibold">WristMind</div><div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">web control center</div></div>
        </div>
        <div className="py-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-primary">Первый запуск</div>
          <h1 id="enrollment-title" className="mt-2 text-2xl font-semibold tracking-tight">Подключить панель к серверу</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">Войдите коротким одноразовым кодом или используйте секрет первичной регистрации. Токен сохранится только в этом браузере.</p>
        </div>
        <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); void enroll(); }}>
          <label htmlFor="server-url" className="grid gap-1.5 text-sm font-medium">Адрес сервера
            <Input id="server-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} className="h-10 font-mono text-xs" autoComplete="url" />
            <span className="text-xs font-normal text-muted-foreground">По умолчанию используется адрес открытой панели. Локально: http://192.168.4.191</span>
          </label>
          <div className="grid grid-cols-2 gap-1 rounded-lg border bg-muted/25 p-1" role="tablist" aria-label="Способ входа">
            <button type="button" role="tab" aria-selected={method === 'code'} onClick={() => { setMethod('code'); setError(null); }} className={cn('rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', method === 'code' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>Код доступа</button>
            <button type="button" role="tab" aria-selected={method === 'secret'} onClick={() => { setMethod('secret'); setError(null); }} className={cn('rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', method === 'secret' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>Секрет</button>
          </div>
          {method === 'code' ? (
            <label htmlFor="pairing-code" className="grid gap-1.5 text-sm font-medium">Одноразовый код
              <Input id="pairing-code" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} className="h-12 text-center font-mono text-xl tracking-[0.35em]" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000" />
              <span className="text-xs font-normal text-muted-foreground">Создаётся в уже подключённой панели: Настройки → Подключить часы.</span>
            </label>
          ) : (
            <label htmlFor="bootstrap-secret" className="grid gap-1.5 text-sm font-medium">Секрет первичной регистрации
              <Input id="bootstrap-secret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} className="h-10" autoComplete="off" />
              <span className="text-xs font-normal text-muted-foreground">Секрет остаётся резервным способом входа для первого запуска.</span>
            </label>
          )}
          {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm leading-5 text-destructive">{error}</div>}
          <Button type="submit" size="lg" className="mt-1 h-10" disabled={busy || !baseUrl.trim() || (method === 'code' ? code.length !== 6 : !secret.trim())}>
            {busy ? <RefreshCw className="animate-spin" /> : <Server />}{busy ? 'Подключение…' : method === 'code' ? 'Войти по коду' : 'Подключить панель'}
          </Button>
        </form>
      </section>
    </main>
  );
}

function MobileNavigation({ destination, onNavigate }: { destination: Destination; onNavigate: (destination: Destination) => void }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 grid h-[calc(4rem+env(safe-area-inset-bottom))] grid-cols-5 border-t bg-background/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden" aria-label="Основная навигация">
      {destinations.map((item) => { const Icon = item.icon; const active = item.id === destination; return (
        <button key={item.id} type="button" onClick={() => onNavigate(item.id)} aria-current={active ? 'page' : undefined} className={cn('flex min-h-12 min-w-0 flex-col items-center justify-center gap-1 rounded-md text-[9px] text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring', active && 'bg-primary/8 text-primary')}>
          <Icon className="size-4" /><span className="max-w-full truncate">{item.label}</span>
        </button>
      ); })}
    </nav>
  );
}

function PlaceholderPage({ destination, modes, chats, devices, models, globalPrompt, historyMessageLimit, totalAiRequests, onCreatePairingCode, onDisconnect, onCreateChat, onCreateQuickChat, onLoadMessages, onSendMessage, onStreamJob, onRefreshChats, onDeleteChat, chatDraftOpen, selectedChatId, onChatDraftChange, onSelectChat, onStartChat, onCreateMode, onUpdateMode, onSetWatchVisibility, onDeleteMode, onSavePrompt, onSaveHistoryLimit }: {
  destination: Exclude<Destination, 'knowledge'>;
  modes: Mode[];
  chats: ApiChat[];
  devices: ApiDevice[];
  models: ApiModel[];
  globalPrompt: string;
  historyMessageLimit: number;
  totalAiRequests: number;
  onCreatePairingCode: () => Promise<{ code: string; expires_at: string }>;
  onDisconnect: () => void;
  onCreateChat: (modeId: string, title: string) => Promise<ApiChat>;
  onCreateQuickChat: () => Promise<void>;
  onLoadMessages: (chatId: string) => Promise<ApiMessage[]>;
  onSendMessage: (chatId: string, text: string) => Promise<ApiJob>;
  onStreamJob: (jobId: string, onEvent: (event: JobStreamEvent) => void, signal?: AbortSignal) => Promise<void>;
  onRefreshChats: () => Promise<void>;
  onDeleteChat: (chatId: string) => Promise<void>;
  chatDraftOpen: boolean;
  selectedChatId: string | null;
  onChatDraftChange: (open: boolean) => void;
  onSelectChat: (chatId: string | null) => void;
  onStartChat: () => void;
  onCreateMode: (input: ModeFormInput) => Promise<void>;
  onUpdateMode: (modeId: string, input: ModeFormInput) => Promise<void>;
  onSetWatchVisibility: (modeId: string, hidden: boolean) => Promise<void>;
  onDeleteMode: (modeId: string) => Promise<void>;
  onSavePrompt: (prompt: string) => Promise<void>;
  onSaveHistoryLimit: (limit: number) => Promise<void>;
}) {
  if (destination === 'overview') return <OverviewPage modes={modes} chats={chats} devices={devices} totalAiRequests={totalAiRequests} onStartChat={onStartChat} onStartQuickChat={onCreateQuickChat} />;
  if (destination === 'chats') return <ChatsPage chats={chats} modes={modes} selectedChatId={selectedChatId} onSelectChat={onSelectChat} draftOpen={chatDraftOpen} onDraftChange={onChatDraftChange} onCreateChat={onCreateChat} onStartQuickChat={onCreateQuickChat} onLoadMessages={onLoadMessages} onSendMessage={onSendMessage} onStreamJob={onStreamJob} onRefreshChats={onRefreshChats} onDeleteChat={onDeleteChat} />;
  if (destination === 'modes') return <ModesPage modes={modes} models={models} onCreateMode={onCreateMode} onUpdateMode={onUpdateMode} onSetWatchVisibility={onSetWatchVisibility} onDeleteMode={onDeleteMode} />;
  return <SettingsPage globalPrompt={globalPrompt} historyMessageLimit={historyMessageLimit} onCreatePairingCode={onCreatePairingCode} onDisconnect={onDisconnect} onSavePrompt={onSavePrompt} onSaveHistoryLimit={onSaveHistoryLimit} />;
}

function PageHeading({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 border-b pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div><div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{eyebrow}</div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>{action && <div className="flex w-full max-sm:[&>div]:flex max-sm:[&>div]:flex-col max-sm:[&>div]:gap-2 max-sm:[&>div>*]:w-full sm:w-auto sm:[&>*]:w-auto">{action}</div>}
    </div>
  );
}

function OverviewPage({ modes, chats, devices, totalAiRequests, onStartChat, onStartQuickChat }: { modes: Mode[]; chats: ApiChat[]; devices: ApiDevice[]; totalAiRequests: number; onStartChat: () => void; onStartQuickChat: () => Promise<void> }) {
  const activeDevices = devices.filter((device) => !device.revoked_at);
  return (
    <section className="animate-in fade-in duration-300">
      <PageHeading eyebrow="Система в реальном времени" title="Обзор" description="Состояние сервера, устройств и рабочих пространств WristMind." action={<div className="flex flex-wrap gap-2"><QuickChatButton onClick={onStartQuickChat} /><NewChatButton onClick={onStartChat} compact /></div>} />
      <div className="grid border-b sm:grid-cols-4">
        <SummaryItem label="Режимы" value={`${modes.length}`} detail="у каждого своя база" />
        <SummaryItem label="Чаты" value={`${chats.length}`} detail="режим фиксирован" />
        <SummaryItem label="Запросы к ИИ" value={Number(totalAiRequests || 0).toLocaleString('ru-RU')} detail="за всё время" />
        <SummaryItem label="Устройства" value={`${activeDevices.length}`} detail="активные подключения" />
      </div>
      <div className="mt-6 flex flex-col gap-4 rounded-lg border border-primary/20 bg-primary/[0.04] p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-primary"><Sparkles className="size-4" /></div>
          <div><div className="font-mono text-[10px] uppercase tracking-[0.14em] text-primary">Быстрый старт</div><h2 className="mt-1 text-sm font-medium">Спросите о чём угодно</h2><p className="mt-1 max-w-xl text-xs leading-5 text-muted-foreground">Школьные предметы, готовка, быт и общие вопросы — универсальная инструкция уже встроена.</p></div>
        </div>
        <QuickChatButton onClick={onStartQuickChat} className="shrink-0 self-start sm:self-center" />
      </div>
      <div className="grid gap-6 py-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.7fr)]">
        <div className="overflow-hidden rounded-lg border bg-card/60">
          <div className="flex items-center justify-between border-b px-4 py-3"><h2 className="text-sm font-medium">Рабочие режимы</h2><Badge variant="outline">Изолированы</Badge></div>
          {modes.map((mode) => <div key={mode.id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <span className="size-2 rounded-full" style={{ backgroundColor: mode.color }} /><span className="text-sm font-medium">{mode.name}</span>
            <span className="ml-auto font-mono text-xs text-muted-foreground">{mode.sources} источн.</span>
          </div>)}
        </div>
        <div className="rounded-lg border bg-card/60">
          <div className="border-b px-4 py-3"><h2 className="text-sm font-medium">Подключения</h2></div>
          <SystemRow icon={Server} title="VPS API" status="В сети" ok />
          <SystemRow icon={Smartphone} title="Poco F6" status={devices.some((device) => device.kind === 'PHONE' && !device.revoked_at) ? 'Зарегистрирован' : 'Не найден'} ok={devices.some((device) => device.kind === 'PHONE' && !device.revoked_at)} />
          <SystemRow icon={Watch} title="Xiaomi Watch 2" status={devices.some((device) => device.kind === 'WATCH' && !device.revoked_at) ? 'Зарегистрированы' : 'Ожидаются'} ok={devices.some((device) => device.kind === 'WATCH' && !device.revoked_at)} />
        </div>
      </div>
    </section>
  );
}

function SystemRow({ icon: Icon, title, status, ok }: { icon: typeof Server; title: string; status: string; ok: boolean }) {
  return <div className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0"><Icon className="size-4 text-muted-foreground" /><div><div className="text-sm font-medium">{title}</div><div className="text-xs text-muted-foreground">{status}</div></div><span className={cn('ml-auto size-2 rounded-full', ok ? 'bg-emerald-400' : 'bg-amber-400')} /></div>;
}

function NewChatButton({ onClick, compact = false }: { onClick: () => void; compact?: boolean }) {
  return <Button onClick={onClick}>{compact ? <Plus /> : <MessageSquareText />}{compact ? 'Новый чат' : 'Создать чат'}</Button>;
}

function QuickChatButton({ onClick, className }: { onClick: () => void | Promise<void>; className?: string }) {
  const [busy, setBusy] = useState(false);
  const handleClick = async () => {
    if (busy) return;
    setBusy(true);
    try { await onClick(); }
    finally { setBusy(false); }
  };
  return <Button onClick={() => void handleClick()} disabled={busy} className={cn('gap-2', className)}>{busy ? <RefreshCw className="size-4 animate-spin" /> : <Sparkles className="size-4" />} {busy ? 'Создаём…' : 'Быстрый чат'}</Button>;
}

function ChatsPage({ chats, modes, selectedChatId, onSelectChat, draftOpen, onDraftChange, onCreateChat, onStartQuickChat, onLoadMessages, onSendMessage, onStreamJob, onRefreshChats, onDeleteChat }: {
  chats: ApiChat[];
  modes: Mode[];
  selectedChatId: string | null;
  onSelectChat: (chatId: string | null) => void;
  draftOpen: boolean;
  onDraftChange: (open: boolean) => void;
  onCreateChat: (modeId: string, title: string) => Promise<ApiChat>;
  onStartQuickChat: () => Promise<void>;
  onLoadMessages: (chatId: string) => Promise<ApiMessage[]>;
  onSendMessage: (chatId: string, text: string) => Promise<ApiJob>;
  onStreamJob: (jobId: string, onEvent: (event: JobStreamEvent) => void, signal?: AbortSignal) => Promise<void>;
  onRefreshChats: () => Promise<void>;
  onDeleteChat: (chatId: string) => Promise<void>;
}) {
  const [pendingDelete, setPendingDelete] = useState<ApiChat | null>(null);
  const [deleting, setDeleting] = useState(false);
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try { await onDeleteChat(pendingDelete.id); setPendingDelete(null); }
    finally { setDeleting(false); }
  };
  const selectedChat = chats.find((chat) => chat.id === selectedChatId);
  if (selectedChat) return <ChatDetailView chat={selectedChat} mode={modes.find((mode) => mode.id === selectedChat.mode_id)} onBack={() => onSelectChat(null)} onDeleteChat={onDeleteChat} onLoadMessages={onLoadMessages} onSendMessage={onSendMessage} onStreamJob={onStreamJob} onRefreshChats={onRefreshChats} />;
  if (draftOpen) return <ChatDraftView modes={modes} onCancel={() => onDraftChange(false)} onCreate={async (modeId) => { const chat = await onCreateChat(modeId, 'Новый чат'); onSelectChat(chat.id); }} />;
  return (
    <section className="animate-in fade-in duration-300">
      <PageHeading eyebrow="История запросов" title="Чаты" description="Быстрый чат — для любых вопросов. Остальные чаты навсегда связаны с выбранным режимом." action={<div className="flex flex-wrap gap-2"><QuickChatButton onClick={onStartQuickChat} /><NewChatButton onClick={() => onDraftChange(true)} /></div>} />
      {chats.length ? <div className="mt-6 overflow-hidden rounded-lg border bg-card/60">
        {chats.map((chat) => { const mode = modes.find((item) => item.id === chat.mode_id); return <div key={chat.id} className="group flex items-center border-b px-2 transition-colors last:border-b-0 hover:bg-muted/35">
          <button type="button" onClick={() => onSelectChat(chat.id)} className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 px-2 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
            <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-muted/45"><MessageSquareText className="size-4 text-muted-foreground" /></div>
            <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{chat.title}</div><div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground"><span className="size-1.5 rounded-full" style={{ backgroundColor: mode?.color }} />{chat.mode_name} · {formatDate(chat.updated_at)}</div></div>
            <Badge variant="outline" className="ml-auto hidden rounded-md sm:inline-flex">{chat.mode_name === 'Быстрый чат' ? 'Универсальный' : 'Режим закреплён'}</Badge>
          </button>
          <Button type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" aria-label={`Удалить чат «${chat.title}»`} onClick={() => setPendingDelete(chat)}><Trash2 className="size-4" /></Button>
        </div>; })}
      </div> : <SimpleEmpty icon={MessageSquareText} title="Чатов пока нет" description="Создайте быстрый чат для любого вопроса или выберите отдельный режим." />}
      <DeleteChatDialog chat={pendingDelete} deleting={deleting} onOpenChange={(open) => { if (!open) setPendingDelete(null); }} onConfirm={confirmDelete} />
    </section>
  );
}

function ChatDetailView({ chat, mode, onBack, onDeleteChat, onLoadMessages, onSendMessage, onStreamJob, onRefreshChats }: {
  chat: ApiChat;
  mode?: Mode;
  onBack: () => void;
  onDeleteChat: (chatId: string) => Promise<void>;
  onLoadMessages: (chatId: string) => Promise<ApiMessage[]>;
  onSendMessage: (chatId: string, text: string) => Promise<ApiJob>;
  onStreamJob: (jobId: string, onEvent: (event: JobStreamEvent) => void, signal?: AbortSignal) => Promise<void>;
  onRefreshChats: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ApiMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<AbortController | null>(null);
  const loadMessagesRef = useRef(onLoadMessages);

  useEffect(() => { loadMessagesRef.current = onLoadMessages; }, [onLoadMessages]);

  const reloadMessages = async () => {
    const next = await onLoadMessages(chat.id);
    setMessages(next);
    return next;
  };

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
      void loadMessagesRef.current(chat.id)
        .then((next) => { if (active) setMessages(next); })
        .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить сообщения'); })
        .finally(() => { if (active) setLoading(false); });
    });
    return () => { active = false; streamRef.current?.abort(); };
  }, [chat.id]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: sending ? 'smooth' : 'auto' });
    } else {
      bottomRef.current?.scrollIntoView({ block: 'end', behavior: sending ? 'smooth' : 'auto' });
    }
  }, [messages, phase, sending]);

  const waitForFinalAssistantMessage = async (assistantMessageId?: string) => {
    for (let attempt = 0; attempt < 45; attempt += 1) {
      try {
        const next = await reloadMessages();
        const assistant = next.find((message) => message.id === assistantMessageId)
          ?? [...next].reverse().find((message) => message.role === 'assistant');
        if (assistant && assistant.status !== 'streaming') return true;
      } catch {
        // The SSE connection may be unavailable while the API request still finishes.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    return false;
  };

  const submit = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft('');
    setSending(true);
    setPhase('Отправляем вопрос');
    setError(null);
    let streamError: string | null = null;
    let questionAccepted = false;
    try {
      const job = await onSendMessage(chat.id, text);
      questionAccepted = true;
      const pendingAssistantId = `pending-${job.id}`;
      let assistantId = pendingAssistantId;
      setMessages((current) => [
        ...current,
        {
          id: `pending-user-${job.id}`,
          chat_id: chat.id,
          role: 'user',
          content: text,
          status: 'complete',
          provider: null,
          model_id: null,
          usage: {},
          timings: {},
          created_at: new Date().toISOString(),
        },
        {
          id: pendingAssistantId,
          chat_id: chat.id,
          role: 'assistant',
          content: '',
          status: 'streaming',
          provider: null,
          model_id: null,
          usage: {},
          timings: {},
          created_at: new Date().toISOString(),
        },
      ]);
      try {
        const initial = await reloadMessages();
        assistantId = [...initial].reverse().find((message) => message.role === 'assistant' && message.status === 'streaming')?.id ?? pendingAssistantId;
      } catch {
        setPhase('Готовим ответ');
      }
      const controller = new AbortController();
      streamRef.current = controller;
      try {
        await onStreamJob(job.id, ({ event, data }) => {
          if (event === 'state') {
            const state = typeof data.state === 'string' ? data.state : '';
            setPhase(
              state === 'queued' ? 'Запрос принят' :
              state === 'context' ? 'Готовим контекст' :
              state === 'search_query' ? 'Уточняем поисковый запрос' :
              state === 'searching' ? 'Ищем источники' :
              state === 'reviewing_sources' ? 'Проверяем источники' :
              state === 'opening_source' ? 'Читаем источник' :
              state === 'generating' ? 'Формируем ответ' :
              'Отправляем запрос',
            );
          }
          if (event === 'delta' && assistantId) {
            const chunk = typeof data.text === 'string' ? data.text : '';
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, content: message.content + chunk } : message));
          }
          if (event === 'complete') setPhase('Ответ готов');
          if (event === 'error') streamError = typeof data.detail === 'string' ? data.detail : 'Не удалось сформировать ответ';
        }, controller.signal);
      } catch (cause) {
        streamError = cause instanceof Error ? cause.message : 'Поток ответа прерван';
        setPhase('Восстанавливаем ответ');
      }
      const finished = await waitForFinalAssistantMessage(assistantId);
      await onRefreshChats();
      if (streamError && !finished) setError(streamError);
      if (finished) setError(null);
      setPhase(null);
    } catch (cause) {
      if (!questionAccepted) setDraft(text);
      setError(cause instanceof Error ? cause.message : 'Не удалось отправить сообщение');
      try { await reloadMessages(); } catch { /* keep the useful send error */ }
    } finally {
      streamRef.current = null;
      setSending(false);
    }
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try { await onDeleteChat(chat.id); setDeleteOpen(false); }
    finally { setDeleting(false); }
  };

  return (
    <section aria-labelledby="chat-detail-title" className="flex h-full min-h-0 flex-col overflow-hidden animate-in fade-in duration-200">
      <button type="button" onClick={onBack} className="mb-4 inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft className="size-4" />Назад к чатам
      </button>

      <div className="flex shrink-0 items-end justify-between gap-3 border-b pb-3 sm:pb-5">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            <span className="size-1.5 rounded-full" style={{ backgroundColor: mode?.color }} />
            Режим закреплён · {chat.mode_name}
          </div>
          <h1 id="chat-detail-title" className="truncate text-xl font-semibold tracking-tight sm:text-[28px]">{chat.title}</h1>
        </div>
        <div className="flex items-center gap-2">
          {phase && <Badge variant="outline" className="hidden w-fit rounded-md sm:inline-flex"><RefreshCw className={cn('size-3', sending && 'animate-spin')} />{phase}</Badge>}
          <Button type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" aria-label={`Удалить чат «${chat.title}»`} onClick={() => setDeleteOpen(true)} disabled={sending}><Trash2 className="size-4" /></Button>
        </div>
      </div>

      <div className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col">
        <div ref={messagesRef} className="wristmind-chat-scroll min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-0.5 py-4 pr-1 sm:space-y-5 sm:px-1 sm:py-6 sm:pr-2" aria-live="polite">
          {loading ? <div className="grid min-h-48 place-items-center text-sm text-muted-foreground"><span className="inline-flex items-center gap-2"><RefreshCw className="size-4 animate-spin text-primary" />Загружаю историю…</span></div>
            : !messages.length ? <SimpleEmpty icon={MessageSquareText} title="Начните разговор" description="Напишите первый вопрос. Ответ появится здесь по мере формирования." />
              : messages.map((message) => <ChatMessage key={message.id} message={message} />)}
          {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm text-destructive">{error}<div className="mt-1 text-xs text-muted-foreground">Текст вопроса сохранён в поле — можно отправить ещё раз.</div></div>}
          <div ref={bottomRef} />
        </div>

        <form className="shrink-0 border-t bg-background/95 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="flex items-end gap-2 rounded-lg border bg-card/85 p-2 shadow-lg shadow-background/35 focus-within:border-primary/45">
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
              disabled={sending}
              placeholder="Напишите вопрос…"
              aria-label="Сообщение"
              rows={1}
              className="min-h-10 max-h-32 resize-none border-0 bg-transparent py-2 shadow-none focus-visible:ring-0"
            />
            <Button type="submit" size="icon" className="shrink-0" aria-label="Отправить сообщение" disabled={!draft.trim() || sending}><SendHorizontal className={cn('size-4', sending && 'animate-pulse')} /></Button>
          </div>
        </form>
      </div>
      <DeleteChatDialog chat={deleteOpen ? chat : null} deleting={deleting} onOpenChange={setDeleteOpen} onConfirm={confirmDelete} />
    </section>
  );
}

function ChatMessage({ message }: { message: ApiMessage }) {
  const assistant = message.role === 'assistant';
  const elapsed = typeof message.timings?.total_ms === 'number' ? `${(message.timings.total_ms / 1000).toFixed(1)} с` : null;
  return <article className={cn('flex gap-3', !assistant && 'justify-end')}>
    {assistant && <div className="mt-1 grid size-8 shrink-0 place-items-center rounded-md border bg-primary/8 text-primary"><Bot className="size-4" /></div>}
    <div className={cn('min-w-0 max-w-[92%] rounded-xl px-3 py-2.5 text-sm leading-6 sm:max-w-[88%] sm:px-4 sm:py-3', assistant ? 'border bg-card/60' : 'bg-primary text-primary-foreground')}>
      {message.content ? <pre className="whitespace-pre-wrap break-words font-sans">{message.content}</pre> : message.status === 'streaming' ? <ThinkingDots /> : null}
      {(elapsed || message.status === 'failed') && <div className={cn('mt-2 border-t pt-2 font-mono text-[10px]', assistant ? 'text-muted-foreground' : 'text-primary-foreground/70')}>{message.status === 'failed' ? 'Ответ завершился ошибкой' : elapsed}</div>}
    </div>
  </article>;
}

function ThinkingDots() {
  return <output className="inline-flex h-6 items-center gap-1.5" aria-label="Модель формирует ответ">
    <span className="wristmind-thinking-dot" />
    <span className="wristmind-thinking-dot [animation-delay:140ms]" />
    <span className="wristmind-thinking-dot [animation-delay:280ms]" />
    <span className="sr-only">Модель формирует ответ</span>
  </output>;
}

function ChatDraftView({ modes, onCancel, onCreate }: { modes: Mode[]; onCancel: () => void; onCreate: (modeId: string) => Promise<void> }) {
  const [busyModeId, setBusyModeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const choose = async (modeId: string) => {
    setBusyModeId(modeId); setError(null);
    try { await onCreate(modeId); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось создать чат'); }
    finally { setBusyModeId(null); }
  };
  return <section aria-labelledby="chat-draft-title" className="animate-in fade-in duration-200">
    <button type="button" onClick={onCancel} className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="size-4" />Назад к чатам</button>
    <div className="max-w-3xl"><div className="font-mono text-[11px] uppercase tracking-[0.12em] text-primary">Новый чат</div><h1 id="chat-draft-title" className="mt-2 text-2xl font-semibold tracking-tight sm:text-[28px]">Выберите режим</h1><p className="mt-1 text-sm leading-6 text-muted-foreground">Название появится автоматически. Режим закрепится после выбора и дальше не изменится.</p></div>
    {error && <div role="alert" className="mt-5 rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm text-destructive">{error}</div>}
    <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{modes.map((mode) => <button key={mode.id} type="button" disabled={Boolean(busyModeId)} onClick={() => void choose(mode.id)} className="group min-h-32 rounded-lg border bg-card/55 p-4 text-left transition-colors hover:border-primary/45 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
      <div className="flex items-start justify-between gap-3"><div className="grid size-9 place-items-center rounded-md border" style={{ color: mode.color, backgroundColor: `${mode.color}18` }}><Sparkles className="size-4" /></div>{busyModeId === mode.id && <RefreshCw className="size-4 animate-spin text-primary" />}</div>
      <div className="mt-4 text-sm font-medium group-hover:text-primary">{mode.name}</div><p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{mode.description || 'Отдельный контекст и собственная база знаний'}</p>
    </button>)}</div>
    {!modes.length && <SimpleEmpty icon={Layers3} title="Сначала нужен режим" description="Создайте хотя бы один режим, затем вернитесь к новому чату." />}
  </section>;
}

function ModesPage({ modes, models, onCreateMode, onUpdateMode, onSetWatchVisibility, onDeleteMode }: {
  modes: Mode[];
  models: ApiModel[];
  onCreateMode: (input: ModeFormInput) => Promise<void>;
  onUpdateMode: (modeId: string, input: ModeFormInput) => Promise<void>;
  onSetWatchVisibility: (modeId: string, hidden: boolean) => Promise<void>;
  onDeleteMode: (modeId: string) => Promise<void>;
}) {
  const [selectedModeId, setSelectedModeId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<Mode | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [visibilityBusyId, setVisibilityBusyId] = useState<string | null>(null);
  const [visibilityError, setVisibilityError] = useState<string | null>(null);
  const selectedMode = modes.find((mode) => mode.id === selectedModeId);
  const toggleWatchVisibility = async (mode: Mode) => {
    setVisibilityBusyId(mode.id);
    setVisibilityError(null);
    try { await onSetWatchVisibility(mode.id, !mode.hiddenOnWatch); }
    catch (cause) { setVisibilityError(cause instanceof Error ? cause.message : 'Не удалось изменить видимость режима'); }
    finally { setVisibilityBusyId(null); }
  };
  const confirmDelete = async () => {
    if (!deleteCandidate) return;
    setDeleting(true);
    try {
      await onDeleteMode(deleteCandidate.id);
      setDeleteCandidate(null);
      setSelectedModeId(null);
    } finally {
      setDeleting(false);
    }
  };
  if (selectedMode) return <>
    <ModeDetailView
      key={selectedMode.id}
      mode={selectedMode}
      models={models}
      onBack={() => setSelectedModeId(null)}
      onSave={(input) => onUpdateMode(selectedMode.id, input)}
      onToggleWatchVisibility={() => void toggleWatchVisibility(selectedMode)}
      visibilityBusy={visibilityBusyId === selectedMode.id}
      visibilityError={visibilityError}
      onDelete={() => setDeleteCandidate(selectedMode)}
    />
    <DeleteModeDialog
      mode={deleteCandidate}
      deleting={deleting}
      onOpenChange={(open) => { if (!open && !deleting) setDeleteCandidate(null); }}
      onConfirm={confirmDelete}
    />
  </>;
  return (
    <>
      <section className="animate-in fade-in duration-300">
      <PageHeading eyebrow="Поведение помощника" title="Режимы" description="Промпт, модель и база знаний образуют отдельное рабочее пространство." action={<CreateModeDialog models={models} onCreate={onCreateMode} />} />
      <div className="mt-6 overflow-hidden rounded-lg border bg-card/60">
        {modes.map((mode) => <div key={mode.id} className="flex items-center gap-3 border-b px-4 py-4 last:border-b-0">
          <button type="button" onClick={() => setSelectedModeId(mode.id)} className="grid min-w-0 flex-1 gap-3 rounded-md text-left transition-colors hover:bg-muted/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_180px_120px] sm:items-center">
            <div className="flex min-w-0 items-center gap-3"><div className="grid size-9 shrink-0 place-items-center rounded-md border" style={{ backgroundColor: `${mode.color}18`, color: mode.color }}><Sparkles className="size-4" /></div><div className="min-w-0"><div className="truncate text-sm font-medium">{mode.name}</div><div className="text-xs text-muted-foreground">{mode.hiddenOnWatch ? 'Скрыт на часах' : 'Отдельный контекст и RAG'}</div></div></div>
            <div className="truncate font-mono text-xs text-muted-foreground">{models.find((model) => model.id === mode.modelId)?.label ?? mode.modelId}</div>
            <div className="font-mono text-xs text-muted-foreground">{mode.sources} источн.</div>
          </button>
          <WatchVisibilityButton mode={mode} busy={visibilityBusyId === mode.id} onClick={() => void toggleWatchVisibility(mode)} />
          <Button type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" aria-label={`Удалить режим «${mode.name}»`} onClick={() => setDeleteCandidate(mode)}><Trash2 className="size-4" /></Button>
        </div>)}
      </div>
      {visibilityError && <div role="alert" className="mt-3 text-sm text-destructive">{visibilityError}</div>}
      </section>
      <DeleteModeDialog
        mode={deleteCandidate}
        deleting={deleting}
        onOpenChange={(open) => { if (!open && !deleting) setDeleteCandidate(null); }}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function WatchVisibilityButton({ mode, busy, onClick }: { mode: Mode; busy: boolean; onClick: () => void }) {
  const label = mode.hiddenOnWatch ? `Показать режим «${mode.name}» на часах` : `Скрыть режим «${mode.name}» на часах`;
  return <Button type="button" variant="ghost" size="icon" className="h-11 w-11 shrink-0 text-muted-foreground hover:text-foreground sm:h-9 sm:w-9" aria-label={label} title={label} aria-pressed={mode.hiddenOnWatch} disabled={busy} onClick={onClick}>
    {mode.hiddenOnWatch ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
  </Button>;
}

function ModeDetailView({ mode, models, onBack, onSave, onToggleWatchVisibility, visibilityBusy, visibilityError, onDelete }: { mode: Mode; models: ApiModel[]; onBack: () => void; onSave: (input: ModeFormInput) => Promise<void>; onToggleWatchVisibility: () => void; visibilityBusy: boolean; visibilityError: string | null; onDelete: () => void }) {
  const [name, setName] = useState(mode.name);
  const [description, setDescription] = useState(mode.description);
  const [color, setColor] = useState(mode.color);
  const [modelId, setModelId] = useState(mode.modelId);
  const [prompt, setPrompt] = useState(mode.systemPrompt);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = name !== mode.name || description !== mode.description || color !== mode.color || modelId !== mode.modelId || prompt !== mode.systemPrompt;
  const save = async () => {
    if (!name.trim() || !modelId) return;
    setBusy(true); setError(null); setSaved(false);
    try { await onSave({ name: name.trim(), description: description.trim(), color, modelId, systemPrompt: prompt.trim() }); setSaved(true); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось сохранить режим'); }
    finally { setBusy(false); }
  };
  return <section aria-labelledby="mode-detail-title" className="animate-in fade-in duration-200">
    <button type="button" onClick={onBack} className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="size-4" />Назад к режимам</button>
    <div className="flex flex-col gap-4 border-b pb-6 sm:flex-row sm:items-end sm:justify-between"><div><div className="mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground"><span className="size-2 rounded-full" style={{ backgroundColor: color }} />Настройки режима</div><h1 id="mode-detail-title" className="text-2xl font-semibold tracking-tight sm:text-[28px]">{mode.name}</h1><p className="mt-1 text-sm text-muted-foreground">{mode.sources} источников в изолированной базе знаний{mode.hiddenOnWatch ? ' · Скрыт на часах' : ''}</p></div><div className="flex w-full items-center gap-2 sm:w-auto"><WatchVisibilityButton mode={mode} busy={visibilityBusy} onClick={onToggleWatchVisibility} /><Button type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" aria-label={`Удалить режим «${mode.name}»`} onClick={onDelete}><Trash2 className="size-4" /></Button><Button className="flex-1 sm:flex-none" onClick={() => void save()} disabled={busy || !dirty || !name.trim() || !modelId}><Save />{busy ? 'Сохранение…' : 'Сохранить изменения'}</Button></div></div>
    <div className="grid gap-6 py-6 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]">
      <div className="rounded-lg border bg-card/55 p-4"><h2 className="text-sm font-medium">Основное</h2><div className="mt-4 grid gap-4">
        <label htmlFor="mode-detail-name" className="grid gap-1.5 text-sm font-medium">Название<Input id="mode-detail-name" value={name} onChange={(event) => { setName(event.target.value); setSaved(false); }} maxLength={80} /></label>
        <label htmlFor="mode-detail-description" className="grid gap-1.5 text-sm font-medium">Описание<Textarea id="mode-detail-description" value={description} onChange={(event) => { setDescription(event.target.value); setSaved(false); }} rows={3} maxLength={500} placeholder="Для каких задач нужен этот режим" /><span className="text-xs font-normal text-muted-foreground">Показывается при выборе режима на телефоне и часах.</span></label>
        <div className="grid gap-1.5 text-sm font-medium"><span>Модель ответов</span><Select value={modelId} onValueChange={(value) => { setModelId(value as string); setSaved(false); }} itemToStringLabel={(value) => models.find((model) => model.id === value)?.label ?? ''}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{models.map((model) => <SelectItem key={model.id} value={model.id}>{model.label}<span className="ml-auto font-mono text-[10px] text-muted-foreground">{model.provider}</span></SelectItem>)}</SelectContent></Select></div>
        <label htmlFor="mode-detail-color" className="grid gap-1.5 text-sm font-medium">Цвет<div className="flex items-center gap-2"><Input id="mode-detail-color" type="color" value={color} onChange={(event) => { setColor(event.target.value); setSaved(false); }} className="h-9 w-14 p-1" /><Input aria-label="Цвет режима в HEX" value={color} onChange={(event) => { setColor(event.target.value); setSaved(false); }} className="font-mono text-xs" /></div></label>
      </div></div>
      <div className="rounded-lg border bg-card/55 p-4"><h2 className="text-sm font-medium">Системный промпт</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">Инструкции применяются только к этому режиму и дополняют общий промпт.</p><Textarea value={prompt} onChange={(event) => { setPrompt(event.target.value); setSaved(false); }} rows={14} className="mt-4" placeholder="Как помощник должен отвечать" /></div>
    </div>
    {saved && <output className="block rounded-lg border border-emerald-400/25 bg-emerald-400/8 p-3 text-sm text-emerald-300">Изменения сохранены.</output>}
    {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm text-destructive">{error}</div>}
    {visibilityError && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm text-destructive">{visibilityError}</div>}
  </section>;
}

function CreateModeDialog({ models, onCreate }: { models: ApiModel[]; onCreate: (input: ModeFormInput) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [prompt, setPrompt] = useState('');
  const [color, setColor] = useState('#72e6b1');
  const [modelId, setModelId] = useState(models[0]?.id ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedModelId = modelId || models[0]?.id || '';
  const create = async () => {
    if (!name.trim() || !selectedModelId) return;
    setBusy(true); setError(null);
    try { await onCreate({ name: name.trim(), description: description.trim(), color, systemPrompt: prompt.trim(), modelId: selectedModelId }); setOpen(false); setName(''); setDescription(''); setPrompt(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось создать режим'); }
    finally { setBusy(false); }
  };
  return <><Button onClick={() => setOpen(true)} disabled={!models.length}><Plus />Новый режим</Button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="sm:max-w-[560px]"><DialogHeader><DialogTitle>Новый режим</DialogTitle><DialogDescription>Он получит собственный промпт, модель, чаты и изолированную базу знаний.</DialogDescription></DialogHeader>
      <div className="grid gap-4 py-1"><label htmlFor="mode-name" className="grid gap-1.5 text-sm font-medium">Название<Input id="mode-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, Математика" /></label>
        <label htmlFor="mode-description" className="grid gap-1.5 text-sm font-medium">Описание<Textarea id="mode-description" value={description} onChange={(event) => setDescription(event.target.value)} rows={2} maxLength={500} placeholder="Для каких задач нужен этот режим" /></label>
        <div className="grid gap-1.5 text-sm font-medium"><span>Модель</span><Select value={selectedModelId} onValueChange={(value) => setModelId(value as string)} itemToStringLabel={(value) => models.find((model) => model.id === value)?.label ?? ''}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{models.map((model) => <SelectItem key={model.id} value={model.id}>{model.label}<span className="ml-auto font-mono text-[10px] text-muted-foreground">{model.provider}</span></SelectItem>)}</SelectContent></Select></div>
        <label htmlFor="mode-color" className="grid gap-1.5 text-sm font-medium">Цвет режима<div className="flex items-center gap-2"><Input id="mode-color" type="color" value={color} onChange={(event) => setColor(event.target.value)} className="h-9 w-14 p-1" /><Input aria-label="Цвет режима в HEX" value={color} onChange={(event) => setColor(event.target.value)} className="font-mono text-xs" /></div></label>
        <label htmlFor="mode-prompt" className="grid gap-1.5 text-sm font-medium">Системный промпт<Textarea id="mode-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} placeholder="Как помощник должен отвечать в этом режиме" /></label>
        {error && <div role="alert" className="text-xs text-destructive">{error}</div>}
      </div><DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button><Button disabled={busy || !name.trim() || !selectedModelId} onClick={() => void create()}>{busy ? 'Создание…' : 'Создать режим'}</Button></DialogFooter>
    </DialogContent></Dialog></>;
}

function SettingsPage({ globalPrompt, historyMessageLimit, onCreatePairingCode, onDisconnect, onSavePrompt, onSaveHistoryLimit }: { globalPrompt: string; historyMessageLimit: number; onCreatePairingCode: () => Promise<{ code: string; expires_at: string }>; onDisconnect: () => void; onSavePrompt: (prompt: string) => Promise<void>; onSaveHistoryLimit: (limit: number) => Promise<void> }) {
  const [prompt, setPrompt] = useState(globalPrompt);
  const [historyLimit, setHistoryLimit] = useState(historyMessageLimit);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [pairingBusy, setPairingBusy] = useState(false);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const save = async () => {
    setBusy(true); setError(null);
    try { await onSavePrompt(prompt); setEditing(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось сохранить промпт'); }
    finally { setBusy(false); }
  };
  const saveHistoryLimit = async () => {
    setBusy(true); setError(null);
    try { await onSaveHistoryLimit(historyLimit); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось сохранить лимит истории'); }
    finally { setBusy(false); }
  };
  const issuePairingCode = async () => {
    setPairingBusy(true); setPairingError(null); setCopied(false);
    try { setPairingCode(await onCreatePairingCode()); }
    catch (cause) { setPairingError(cause instanceof Error ? cause.message : 'Не удалось создать код'); }
    finally { setPairingBusy(false); }
  };
  const copyPairingCode = async () => {
    if (!pairingCode) return;
    try {
      await navigator.clipboard.writeText(pairingCode.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { setPairingError('Не удалось скопировать код.'); }
  };
  return (
    <section className="animate-in fade-in duration-300">
      <PageHeading eyebrow="Конфигурация" title="Настройки" description="Общие инструкции и подключение веб-панели." />
      <div className="grid gap-6 py-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.6fr)]">
        <div className="space-y-4"><div className="rounded-lg border bg-card/60 p-4"><h2 className="text-sm font-medium">Общий системный промпт</h2><p className="mt-1 text-xs text-muted-foreground">Применяется перед промптом выбранного режима.</p>
          {editing ? <Textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={8} className="mt-4" /> : <div className="mt-4 min-h-36 whitespace-pre-wrap rounded-lg border bg-background/60 p-3 text-sm leading-6">{globalPrompt || 'Общий промпт пока не задан.'}</div>}
          {error && <div role="alert" className="mt-2 text-xs text-destructive">{error}</div>}
          <div className="mt-3 flex justify-end gap-2">{editing && <Button variant="ghost" onClick={() => { setEditing(false); setPrompt(globalPrompt); }} disabled={busy}>Отмена</Button>}<Button variant="outline" onClick={() => { if (editing) void save(); else { setPrompt(globalPrompt); setEditing(true); } }} disabled={busy}>{editing ? (busy ? 'Сохранение…' : 'Сохранить') : 'Редактировать'}</Button></div>
        </div>
        <div className="rounded-lg border bg-card/60 p-4"><h2 className="text-sm font-medium">История в контексте</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">В модель отправляются последние сообщения чата. Меньше сообщений — ниже расход токенов.</p>
          <div className="mt-4 flex items-center gap-3"><Input type="number" min={2} max={50} value={historyLimit} onChange={(event) => setHistoryLimit(Math.max(2, Math.min(50, Number(event.target.value) || 2)))} className="w-24 font-mono" aria-label="Количество сообщений истории" /><span className="text-sm text-muted-foreground">сообщений</span><Button variant="outline" className="ml-auto" onClick={() => void saveHistoryLimit()} disabled={busy}>Сохранить</Button></div>
          <p className="mt-2 text-xs text-muted-foreground">Сейчас: {historyLimit}. Рекомендуемое значение — 12.</p>
        </div></div>
        <div className="space-y-4">
          <div className="rounded-lg border bg-card/60 p-4">
            <div className="flex items-start gap-3"><div className="grid size-9 shrink-0 place-items-center rounded-md bg-primary/10 text-primary"><Watch className="size-4" /></div><div><h2 className="text-sm font-medium">Подключить устройство</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">Создайте одноразовый код и введите его на часах или в другой панели. Код действует 10 минут.</p></div></div>
            {pairingCode && <div className="mt-4 rounded-lg border border-primary/25 bg-primary/5 p-3"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="font-mono text-2xl font-semibold tracking-[0.22em] text-primary">{pairingCode.code}</div><div className="mt-1 text-[11px] text-muted-foreground">Действует до {formatDate(pairingCode.expires_at)}</div></div><Button type="button" variant="outline" size="sm" className="w-full sm:w-auto" onClick={() => void copyPairingCode()}><Copy />{copied ? 'Скопировано' : 'Копировать'}</Button></div></div>}
            {pairingError && <div role="alert" className="mt-3 text-xs text-destructive">{pairingError}</div>}
            <Button type="button" className="mt-4 w-full" onClick={() => void issuePairingCode()} disabled={pairingBusy}>{pairingBusy ? <RefreshCw className="animate-spin" /> : <Watch />}{pairingBusy ? 'Создание кода…' : pairingCode ? 'Создать новый код' : 'Получить код подключения'}</Button>
          </div>
          <Button variant="destructive" className="w-full" onClick={onDisconnect}>Отключить эту веб-панель</Button></div>
      </div>
    </section>
  );
}

function SimpleEmpty({ icon: Icon, title, description }: { icon: typeof MessageSquareText; title: string; description: string }) {
  return <div className="mt-6 grid min-h-72 place-items-center rounded-lg border border-dashed bg-card/35 p-6 text-center"><div className="max-w-sm"><div className="mx-auto grid size-11 place-items-center rounded-lg border bg-muted/50"><Icon className="size-5 text-muted-foreground" /></div><h2 className="mt-4 font-semibold">{title}</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p></div></div>;
}

function formatTokens(tokens: number) {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)} млн`;
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)} тыс.`;
  return `${tokens}`;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date);
}
