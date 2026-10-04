import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from '@/app/router';
import {
  ArrowDown,
  ArrowLeft,
  BookOpen,
  Clock,
  ExternalLink,
  Layers,
  MoreHorizontal,
  Pencil,
  Telescope,
  Trash2,
  Wand2,
} from 'lucide-react';
import { useActions } from '@/services';
import { useChat, useChatMessages, useModes, useModels, useSources } from '@/store';
import { isMessagePhase, type ChatSources, type Message, type MessagePhase } from '@/types';
import { formatDuration, formatTime } from '@/lib/format';
import { chatSourceCards, messageSourceCards, type ChatSourceFilter } from '@/lib/chatSources';
import {
  Button,
  EmptyState,
  IconButton,
  Menu,
  Tooltip,
  useToast,
} from '@/components';
import { ModeBadge, QuickChatBadge } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import { ChatSourcesPanel } from './ChatSourcesPanel';
import { Composer } from './Composer';
import { MessageDiagnostics } from './MessageDiagnostics';
import { MessageSources } from './MessageSources';
import { ProcessingTimeline, StageInlineLabel } from './ProcessingTimeline';
import { RenameChatDialog } from './RenameChatDialog';
import { RichText } from './RichText';
import { useChatSources } from './useChatSources';
import styles from './Chats.module.css';

/* -------------------------------------------------------------------------- */
/* Citations                                                                  */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/* Message                                                                    */
/* -------------------------------------------------------------------------- */

function MessageBlock({
  message,
  chatSources,
  onOpenSources,
}: {
  message: Message;
  chatSources: ChatSources | null;
  onOpenSources: (messageId: string) => void;
}) {
  const models = useModels();
  const model = models.find((m) => m.id === message.model_id);
  const streaming = isMessagePhase(message.status);
  const phase: MessagePhase | null = streaming ? (message.status as MessagePhase) : null;
  // The pipeline is reported by the backend; fall back to what the options imply.
  const phases: MessagePhase[] =
    message.phases.length > 0
      ? message.phases
      : streaming
        ? [message.status as MessagePhase]
        : ['queued', 'context', 'generating'];

  if (message.role === 'user') {
    return (
      <article className={styles.message} data-role="user">
        <div className={styles.userBubble}>{message.content}</div>
        <div className={styles.messageMeta} data-align="end">
          <span>{formatTime(message.created_at)}</span>
        </div>
      </article>
    );
  }

  // Before any text arrives the answer is still being assembled, so the
  // timeline is the only meaningful content.
  const showTimeline = streaming && message.content.length === 0;

  return (
    <article className={styles.message} data-role="assistant">
      <div className={styles.assistantHead}>
        <span className={styles.assistantAvatar} aria-hidden>
          <Wand2 />
        </span>
        <div className={styles.assistantMeta}>
          <span className={styles.assistantName}>WristMind</span>
          {model && <span className={styles.assistantModel}>{model.name}</span>}
        </div>
        {streaming && <StageInlineLabel phase={phase} />}
        {!streaming && message.timings?.total_ms != null && (
          <Tooltip label="Время обработки запроса">
            <span className={styles.duration}>
              <Clock />
              {formatDuration(message.timings.total_ms)}
            </span>
          </Tooltip>
        )}
      </div>

      <div className={styles.assistantBody}>
        {showTimeline ? (
          <ProcessingTimeline current={phase} phases={phases} />
        ) : (
          <>
            <RichText content={message.content} />
            {streaming && <span className={styles.caret} aria-hidden />}
          </>
        )}
        {!streaming && message.status === 'complete' && (
          <MessageSources message={message} chatSources={chatSources} onOpen={onOpenSources} />
        )}
        {!streaming && <MessageDiagnostics message={message} />}
        {message.status === 'cancelled' && (
          <div className={styles.messageMeta}>
            <span>Генерация остановлена</span>
          </div>
        )}
        {message.status === 'error' && (
          <div className={styles.messageMeta} data-tone="danger">
            <span>Не удалось получить ответ</span>
          </div>
        )}
      </div>
    </article>
  );
}

/* -------------------------------------------------------------------------- */
/* Conversation                                                               */
/* -------------------------------------------------------------------------- */

const SUGGESTIONS_WITH_KB = [
  'Что написано в базе знаний по этому режиму?',
  'Перечисли ключевые пункты из самого свежего источника',
  'Есть ли в источниках противоречия?',
];

const SUGGESTIONS_QUICK = [
  'Помоги спланировать неделю: три главные задачи',
  'Объясни простыми словами, как работает RAG',
  'Составь чек-лист для первой недели на новом проекте',
];

export function Conversation({ chatId }: { chatId: string }) {
  const chat = useChat(chatId);
  const messages = useChatMessages(chatId);
  const modes = useModes();
  const sources = useSources();
  const actions = useActions();
  const toast = useToast();
  const quick = useQuickActions();
  const navigate = useNavigate();

  const mode = modes.find((m) => m.id === chat?.mode_id);
  const readySources = sources.filter((s) => s.mode_id === chat?.mode_id && s.status === 'ready');

  // The server always uses the current chat's available context. These switches
  // control only the optional public-web paths.
  const [researchMode, setResearchMode] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [renaming, setRenaming] = useState(false);

  // Chat-scoped sources. Re-fetched when the message count changes so a new
  // answer's Working Sources appear without a manual reload.
  const chatSourcesState = useChatSources(chat ? chatId : undefined, messages.length);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [sourcesMessageId, setSourcesMessageId] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<ChatSourceFilter>('all');

  const chatSourceList = useMemo(
    () => chatSourceCards(chatSourcesState.sources),
    [chatSourcesState.sources],
  );

  const openChatSources = useCallback(() => {
    setSourcesMessageId(null);
    setSourceFilter('all');
    setSourcesOpen(true);
  }, []);

  const openMessageSources = useCallback((messageId: string) => {
    setSourcesMessageId(messageId);
    setSourceFilter('all');
    setSourcesOpen(true);
  }, []);

  const activeSourceMessage = useMemo(
    () =>
      sourcesMessageId
        ? messages.find((message) => message.id === sourcesMessageId) ?? null
        : null,
    [messages, sourcesMessageId],
  );

  const panelSourceCards = useMemo(
    () =>
      activeSourceMessage
        ? messageSourceCards(activeSourceMessage, chatSourcesState.sources)
        : chatSourceList,
    [activeSourceMessage, chatSourcesState.sources, chatSourceList],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const lastMessage = messages[messages.length - 1];
  const lastContentLength = lastMessage?.content.length ?? 0;

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinnedToBottom) return;
    node.scrollTop = node.scrollHeight;
  }, [messages.length, lastContentLength, pinnedToBottom]);

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPinnedToBottom(true);
    setStreaming(false);
    setResearchMode(false);
    setSourcesOpen(false);
    setSourcesMessageId(null);
    setSourceFilter('all');
  }, [chatId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (text: string) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setPinnedToBottom(true);
      setStreaming(true);
      try {
        await actions.sendMessage({
          chat_id: chatId,
          content: text,
          research_mode: researchMode,
          signal: controller.signal,
        });
      } catch {
        toast.error('Не удалось получить ответ', 'Попробуйте отправить сообщение ещё раз');
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setStreaming(false);
      }
    },
    [actions, chatId, researchMode, toast],
  );

  const handleScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    setPinnedToBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 80);
  };

  const handleDelete = async () => {
    if (!chat) return;
    try {
      await actions.deleteChat(chat.id);
      toast.success('Чат удалён', chat.title);
      navigate('/chats');
    } catch {
      toast.error('Не удалось удалить чат');
    }
  };

  const suggestions = useMemo(
    () => (chat?.mode_id ? SUGGESTIONS_WITH_KB : SUGGESTIONS_QUICK),
    [chat?.mode_id],
  );

  if (!chat) {
    return (
      <section className={styles.conversation}>
        <EmptyState
          icon={<BookOpen />}
          title="Чат не найден" description="Возможно, он был удалён. Выберите другой диалог в списке." action={
            <Button variant="secondary" onClick={() => navigate('/chats')}>
              К списку чатов
            </Button>
          }
        />
      </section>
    );
  }

  return (
    <section className={styles.conversation} aria-label="Диалог">
      <header className={styles.convHeader}>
        <div className={styles.convHeaderLeft}>
          <Link to="/chats" className={styles.backButton} aria-label="К списку чатов">
            <ArrowLeft />
          </Link>
          <div className={styles.convTitleBlock}>
            <h2 className={styles.convTitle}>{chat.title}</h2>
            <div className={styles.convSubtitle}>
              {mode ? (
                <ModeBadge
                  modeId={mode.id}
                  color={mode.color}
                  icon={mode.icon}
                  name={mode.name}
                  size="sm"
                />
              ) : (
                <QuickChatBadge size="sm" />
              )}
            </div>
          </div>
        </div>

        <div className={styles.convHeaderActions}>
          {chatSourceList.length > 0 && (
            <button
              type="button" className={styles.chatSourcesButton}
              onClick={openChatSources}
              aria-haspopup="dialog"
              aria-expanded={sourcesOpen}
            >
              <Layers aria-hidden />
              <span>Источники</span>
              <span className={styles.chatSourcesCount}>· {chatSourceList.length}</span>
            </button>
          )}
          <Menu
            align="end" width={230}
            entries={[
              {
                type: 'item' as const,
                id: 'rename',
                label: 'Переименовать',
                icon: <Pencil />,
                onSelect: () => setRenaming(true),
              },
              ...(mode
                ? [
                    {
                      type: 'item' as const,
                      id: 'mode',
                      label: 'Открыть режим',
                      description: mode.name,
                      icon: <ExternalLink />,
                      onSelect: () => navigate(`/modes/${mode.id}`),
                    },
                    {
                      type: 'item' as const,
                      id: 'kb',
                      label: 'База знаний режима',
                      icon: <BookOpen />,
                      onSelect: () => navigate(`/modes/${mode.id}?tab=knowledge`),
                    },
                  ]
                : []),
              { type: 'separator' as const },
              {
                type: 'item',
                id: 'delete',
                label: 'Удалить чат',
                icon: <Trash2 />,
                danger: true,
                onSelect: handleDelete,
              },
            ]}
            trigger={<IconButton size="sm" label="Действия с чатом" icon={<MoreHorizontal />} />}
          />
        </div>
      </header>

      <div className={styles.messagesScroll} ref={scrollRef} onScroll={handleScroll}>
        <div className={styles.messagesInner}>
          {messages.length === 0 ? (
            <div className={styles.emptyChat}>
              <EmptyState
                icon={mode ? <BookOpen /> : <Wand2 />}
                title={mode ? `Режим «${mode.name}»` : 'Быстрый чат'}
                description={
                  mode
                    ? mode.description ||
                      'Задайте вопрос — ответ будет основан на документах режима со ссылками на страницы.'
                    : 'Универсальный чат без базы знаний. Подходит для разовых вопросов и черновиков.'
                }
              />
              {mode && readySources.length === 0 && (
                <div className={styles.emptyWarning}>
                  <span>В базе знаний режима нет готовых источников — ответы будут без ссылок.</span>
                  <Button
                    size="sm" variant="secondary" iconLeft={<BookOpen />}
                    onClick={() => quick.uploadSource(mode.id)}
                  >
                    Загрузить
                  </Button>
                </div>
              )}
              <div className={styles.suggestions}>
                <div className={styles.suggestionsLabel}>Попробуйте спросить</div>
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button" className={styles.suggestion}
                    onClick={() => void send(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
              <div className={styles.emptyOptions}>
                <span className={styles.emptyOptionsLabel}>Опции запроса</span>
                <div className={styles.emptyOptionsList}>
                  <span data-on={researchMode || undefined}>
                    <Telescope /> {researchMode ? 'Исследование' : 'Авто'}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <MessageBlock
                key={message.id}
                message={message}
                chatSources={chatSourcesState.sources}
                onOpenSources={openMessageSources}
              />
            ))
          )}
        </div>

        {!pinnedToBottom && messages.length > 0 && (
          <button
            type="button" className={styles.scrollDown}
            onClick={() => {
              const node = scrollRef.current;
              if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
              setPinnedToBottom(true);
            }}
          >
            <ArrowDown /> К последнему сообщению
          </button>
        )}
      </div>

      <Composer
        onSend={send}
        onStop={() => abortRef.current?.abort()}
        streaming={streaming}
        researchMode={researchMode}
        onResearchModeToggle={setResearchMode}
        autoFocus={messages.length === 0}
        placeholder={mode ? `Вопрос по режиму «${mode.name}»…` : 'Быстрый вопрос без базы знаний…'}
      />

      {streaming && (
        <div className={styles.streamingBar} role="status" aria-label="Идёт генерация ответа">
          <span className={styles.streamingBarInner} />
        </div>
      )}

      <RenameChatDialog chat={renaming ? chat : null} onClose={() => setRenaming(false)} />

      <ChatSourcesPanel
        key={chatId}
        chatId={chatId}
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        mode={activeSourceMessage ? 'message' : 'chat'}
        cards={panelSourceCards}
        loading={chatSourcesState.loading}
        error={chatSourcesState.error}
        filter={sourceFilter}
        onFilterChange={setSourceFilter}
        onShowAll={() => {
          setSourcesMessageId(null);
          setSourceFilter('all');
        }}
        onRetry={chatSourcesState.reload}
      />
    </section>
  );
}
