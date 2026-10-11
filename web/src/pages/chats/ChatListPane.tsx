import { useChatBase } from './useChatBase';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from '@/app/router';
import {
  BookOpen,
  MessagesSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Trash2,
  Zap,
} from 'lucide-react';
import { useActions } from '@/services';
import { useChats, useModes, useSources } from '@/store';
import type { Chat } from '@/types';
import { formatRelativeTime, plural } from '@/lib/format';
import {
  Button,
  EmptyState,
  IconButton,
  Menu,
  useToast,
} from '@/components';
import { ModeDot } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import { RenameChatDialog } from './RenameChatDialog';
import styles from './Chats.module.css';

/**
 * Where the conversation list is rendered. `rail` is the desktop navigation
 * rail, where the list sits on the rail's own grey tone; `page` is the mobile
 * list screen, which is a page and keeps the page's header and footer.
 */
export type ChatListVariant = 'rail' | 'page';
const listPositions = new Map<string, number>();

/* -------------------------------------------------------------------------- */
/* Row                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * One conversation. The row is a single line everywhere: the rail is too narrow
 * for a message preview, and the same object should not be drawn two different
 * ways depending on the viewport. The timestamp yields to the row menu while
 * the menu is showing, so the two never overlap.
 */
function ChatRow({
  chat,
  active,
  onRename,
  onDelete,
}: {
  chat: Chat;
  active: boolean;
  onRename: (chat: Chat) => void;
  onDelete: (chat: Chat) => void;
}) {
  const base = useChatBase();
  const modes = useModes();
  const actions = useActions();
  const toast = useToast();
  const [pinning, setPinning] = useState(false);
  const togglePin = async () => {
    if (pinning) return;
    setPinning(true);
    try { await actions.updateChat(chat.id, { pinned: !chat.pinned }); }
    catch { toast.error('Не удалось изменить закрепление'); }
    finally { setPinning(false); }
  };
  const mode = modes.find((m) => m.id === chat.mode_id);

  return (
    <div className={styles.chatRow} data-active={active || undefined}>
      <Link to={`${base}/${chat.id}`} className={styles.chatRowLink}>
        <span className={styles.chatRowTop}>
          <span className={styles.chatRowIdentity}>
            <ModeDot color={mode?.color ?? null} icon={mode?.icon} size="sm" />
            <span className={styles.chatRowTitle}>{chat.title}</span>
          </span>
          <span className={styles.chatRowTime}>
            {chat.pinned && <Pin className={styles.pinIcon} />}
            <span className={styles.chatRowTimeText}>{formatRelativeTime(chat.updated_at)}</span>
          </span>
        </span>
      </Link>
      <div className={styles.chatRowActions}>
        <Menu
          align="end" width={218}
          entries={[
            {
              type: 'item',
              id: 'rename',
              label: 'Переименовать',
              icon: <Pencil />,
              onSelect: () => onRename(chat),
            },
            {
              type: 'item',
              id: 'pin',
              label: chat.pinned ? 'Снять закрепление' : 'Закрепить',
              icon: chat.pinned ? <PinOff /> : <Pin />,
              disabled: pinning,
              onSelect: () => void togglePin(),
            },
            { type: 'separator' },
            {
              type: 'item',
              id: 'delete',
              label: 'Удалить чат',
              icon: <Trash2 />,
              danger: true,
              onSelect: () => onDelete(chat),
            },
          ]}
          trigger={
            <IconButton
              size="sm" label="Действия с чатом" icon={<MoreHorizontal />}
              className={styles.rowMenuButton}
            />
          }
        />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* List                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The conversation list itself: date groups and rows.
 * Rendered once — inside the rail on desktop and as the mobile list screen —
 * so both surfaces stay behaviourally identical. It carries no search field and
 * no mode filter: the owner asked for a plain list of conversations.
 */
export function ChatList({
  activeChatId,
  variant = 'page',
}: {
  activeChatId?: string;
  variant?: ChatListVariant;
}) {
  const base = useChatBase();
  const chats = useChats();
  const sources = useSources();
  const actions = useActions();
  const toast = useToast();
  const navigate = useNavigate();

  const listRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const node = listRef.current;
    if (!node) return;
    const key = `${base}:${variant}`;
    node.scrollTop = listPositions.get(key) ?? 0;
    return () => { listPositions.set(key, node.scrollTop); };
  }, [base, variant]);

  const [renaming, setRenaming] = useState<Chat | null>(null);

  const groups = useMemo(() => {
    const now = Date.now();
    const day = 86_400_000;
    const result: Array<{ label: string; items: Chat[] }> = [
      { label: 'Закреплённые', items: [] },
      { label: 'Сегодня', items: [] },
      { label: 'На этой неделе', items: [] },
      { label: 'Ранее', items: [] },
    ];
    for (const chat of chats) {
      const age = now - new Date(chat.updated_at).getTime();
      if (chat.pinned) result[0].items.push(chat);
      else if (age < day) result[1].items.push(chat);
      else if (age < 7 * day) result[2].items.push(chat);
      else result[3].items.push(chat);
    }
    return result.filter((group) => group.items.length > 0);
  }, [chats]);

  const handleDelete = async (chat: Chat) => {
    try {
      await actions.deleteChat(chat.id);
      toast.success('Чат удалён', chat.title);
      if (chat.id === activeChatId) navigate(base);
    } catch {
      toast.error('Не удалось удалить чат');
    }
  };

  const readySources = sources.filter((s) => s.status === 'ready').length;

  return (
    <div className={styles.chatList} data-variant={variant} data-simple={base === '/talk' || undefined}>
      <div ref={listRef} className={styles.listScroll} data-variant={variant}>
        {chats.length === 0 ? (
          variant === 'rail' ? (
            /* The rail has no room for an illustrated empty state, and the
               create action already sits in the section head above. */
            <p className={styles.railEmpty}>Пока нет чатов</p>
          ) : (
            <EmptyState
              compact
              icon={<MessagesSquare />}
              title="Чатов пока нет"
              description="Создайте чат и выберите режим — от него зависят модель и база знаний."
              action={<NewChatButton />}
            />
          )
        ) : (
          groups.map((group) => (
            <div key={group.label} className={styles.chatGroup}>
              <div className={styles.chatGroupLabel} data-variant={variant}>
                {group.label}
                <span className={styles.chatGroupCount}>{group.items.length}</span>
              </div>
              {group.items.map((chat) => (
                <ChatRow
                  key={chat.id}
                  chat={chat}
                  active={chat.id === activeChatId}
                  onRename={setRenaming}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          ))
        )}
      </div>

      {variant === 'page' && (
        <footer className={styles.listFooter}>
          <span>
            {chats.length} {plural(chats.length, 'чат', 'чата', 'чатов')} ·{' '}
            {chats.filter((c) => c.pinned).length} закреплено
          </span>
          <span className={styles.listFooterMeta}>
            <BookOpen />
            {readySources} в базе знаний
          </span>
        </footer>
      )}

      <RenameChatDialog chat={renaming} onClose={() => setRenaming(null)} />
    </div>
  );
}

function NewChatButton({ compact = false }: { compact?: boolean }) {
  const quick = useQuickActions();
  return (
    <Button
      size="sm" variant="primary" iconLeft={<Plus />}
      onClick={() => quick.newChat(null)}
    >
      {compact ? 'Новый' : 'Новый чат'}
    </Button>
  );
}

/* -------------------------------------------------------------------------- */
/* Mobile list screen                                                          */
/* -------------------------------------------------------------------------- */

/**
 * The mobile list screen. On desktop the same list lives inside the rail, so
 * this pane exists only below the rail breakpoint.
 */
export function ChatListPane({ activeChatId }: { activeChatId?: string }) {
  return (
    <section className={styles.listPane} aria-label="Список чатов">
      <header className={styles.listHeader}>
        <div className={styles.listHeaderTop}>
          <h1 className={styles.listTitle}>Чаты</h1>
          <NewChatButton compact />
        </div>
      </header>
      <ChatList activeChatId={activeChatId} variant="page" />
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty conversation placeholder                                             */
/* -------------------------------------------------------------------------- */

export function ConversationPlaceholder() {
  const quick = useQuickActions();

  return (
    <div className={styles.placeholder}>
      <EmptyState
        icon={<Zap />}
        title="Выберите чат"
        description="Диалоги лежат в рельсе слева. Быстрый чат отвечает без поиска по источникам, чат режима — с ссылками на документы."
        action={
          <Button variant="primary" iconLeft={<Plus />} onClick={() => quick.newChat(null)}>
            Новый чат
          </Button>
        }
      />
    </div>
  );
}
