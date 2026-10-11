import { useChatBase } from './useChatBase';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from '@/app/router';
import {
  ArrowDown,
  ArrowLeft,
  PanelLeft,
  MessageSquarePlus,
  BookOpen,
  Clock,
  Layers,
  Watch,
} from 'lucide-react';
import { useActions } from '@/services';
import { useChat, useChatMessages, useModes, useModels, useSettings, useSources } from '@/store';
import { isMessagePhase, type ChatSources, type Message } from '@/types';
import { formatDuration, formatTime } from '@/lib/format';
import { chatSourceCards, chatSourcesRevision, messageSourceCards, type ChatSourceFilter } from '@/lib/chatSources';
import {
  Button,
  EmptyState,
  Tooltip,
  useToast,
} from '@/components';
import { ModeDot } from '@/components/Entities';
import { ChatSourcesPanel } from './ChatSourcesPanel';
import { Composer } from './Composer';
import { MessageSources } from './MessageSources';
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
  const developerMode = useSettings()?.developer_mode === true;
  const model = models.find((m) => m.id === message.model_id);
  const streaming = isMessagePhase(message.status);


  if (message.role === 'user') {
    return (
      <article className={styles.message} data-role="user">
        <div className={styles.userBubble}>{message.content}</div>
        {developerMode && <div className={styles.messageMeta} data-align="end">
          <span>{formatTime(message.created_at)}</span>
        </div>}
      </article>
    );
  }

  const waitingForText = streaming && message.content.length === 0;
  const pendingLabel = ['search_query', 'searching', 'reviewing_sources', 'opening_source'].includes(message.status) ? 'Ищу информацию' : 'Думаю';

  return (
    <article className={styles.message} data-role="assistant">
      <div className={styles.assistantHead}>
        <span className={styles.assistantAvatar} aria-hidden>
          <Watch />
        </span>
        {/* No per-message model name: ChatGPT marks an assistant turn with its
            mark alone, and repeating the product name above every answer is
            noise. The developer-mode model chip stays available. */}
        {developerMode && model && (
          <div className={styles.assistantMeta}>
            <span className={styles.assistantModel}>{model.name}</span>
          </div>
        )}
        {developerMode && !streaming && message.timings?.total_ms != null && (
          <Tooltip label="Время обработки запроса">
            <span className={styles.duration}>
              <Clock />
              {formatDuration(message.timings.total_ms)}
            </span>
          </Tooltip>
        )}
      </div>

      <div className={styles.assistantBody}>
        {waitingForText ? (
          <div className={styles.thinkingStatus} role="status" aria-label={`${pendingLabel}…`}>{pendingLabel}<span className={styles.streamingDots} aria-hidden><span/><span/><span/></span></div>
        ) : (
          <>
            <RichText content={message.content} streaming={streaming} />
            {streaming && <span className={styles.streamingDots} role="status" aria-label="Ответ поступает"><span aria-hidden /><span aria-hidden /><span aria-hidden /></span>}
          </>
        )}
        {!streaming && message.status === 'complete' && (
          <MessageSources message={message} chatSources={chatSources} onOpen={onOpenSources} />
        )}
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

export function Conversation({ chatId, onExternalStop, recoveryText, onOpenHistory }: { chatId: string; onExternalStop?: () => void; recoveryText?: string; onOpenHistory?: () => void }) {
  const base = useChatBase();
  const chat = useChat(chatId);
  const messages = useChatMessages(chatId);
  const modes = useModes();
  const actions = useActions();
  const toast = useToast();
  const navigate = useNavigate();

  const mode = modes.find((m) => m.id === chat?.mode_id);

  // The server always uses the current chat's available context. These switches
  // control only the optional public-web paths.
  const [researchMode, setResearchMode] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);

  // Finalising an existing assistant message does not change the count.
  // Also follow the shared source feed for later indexing/removal updates.
  // Streamed text is excluded so we never refetch on every token.
  const liveSources = useSources();
  const messageSourcesRevision = chatSourcesRevision(messages);
  const sourceRevision = useMemo(
    () => ({ messages: messageSourcesRevision, sources: liveSources }),
    [messageSourcesRevision, liveSources],
  );
  const chatSourcesState = useChatSources(chat ? chatId : undefined, sourceRevision);
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
        toast.error('Не удалось получить ответ', 'Черновик сохранён. Попробуйте отправить сообщение ещё раз');
        return false;
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

  if (!chat) {
    return (
      <section className={styles.conversation}>
        <EmptyState
          icon={<BookOpen />}
          title="Чат не найден" description="Возможно, он был удалён. Выберите другой диалог в списке." action={
            <Button variant="secondary" onClick={() => navigate(base)}>
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
          {onOpenHistory ? <button type="button" className={styles.backButton} onClick={onOpenHistory} aria-label="История чатов"><PanelLeft aria-hidden /></button> : <Link to={base === '/talk' ? '/talk/history' : base} className={styles.backButton} aria-label="К списку чатов">
            <ArrowLeft />
          </Link>}
          <div className={styles.convTitleBlock}>
            {/* The open conversation is the page heading: on desktop the chat
                list now lives in the rail, so the list's own `h1` exists only
                on the mobile list screen. */}
            <ModeDot color={mode?.color} size="md" />
            <h1 className={styles.convTitle} title={chat.title}>{chat.title}</h1>
          </div>
        </div>

        <div className={styles.convHeaderActions}>
          {base === '/talk' && <Link to="/talk" className={styles.newConversationButton} aria-label="Новый чат" title="Новый чат"><MessageSquarePlus aria-hidden /></Link>}
          {chatSourceList.length > 0 && (
            <button
              type="button" className={styles.chatSourcesButton}
              onClick={openChatSources}
              aria-label={`Источники чата: ${chatSourceList.length}`}
              title="Источники чата"
              aria-haspopup="dialog"
              aria-expanded={sourcesOpen}
            >
              <Layers aria-hidden />
              <span className={styles.chatSourcesCount}>{chatSourceList.length}</span>
            </button>
          )}

        </div>
      </header>

      <div className={styles.messagesScroll} ref={scrollRef} onScroll={handleScroll}>
        <div className={styles.messagesInner}>
          {messages.length === 0 ? (
            /* A new chat is a blank page: nothing above the composer. The mode
               lives in the header, the request mode lives in the composer, and
               suggestions were noise on a phone screen. */
            null
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
            aria-label="К последнему сообщению" title="К последнему сообщению"
            onClick={() => {
              const node = scrollRef.current;
              if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
              setPinnedToBottom(true);
            }}
          >
            <ArrowDown aria-hidden="true" />
          </button>
        )}
      </div>

      <Composer
        recoveryText={recoveryText}
        draftKey={chatId}
        onSend={send}
        onStop={() => { abortRef.current?.abort(); onExternalStop?.(); }}
        streaming={streaming || Boolean(lastMessage && isMessagePhase(lastMessage.status))}
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
