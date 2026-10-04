import { useMemo, useState } from 'react';
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
import { useChats, useChatMessages, useModes, useSources } from '@/store';
import type { Chat } from '@/types';
import { cn } from '@/lib/cn';
import { formatRelativeTime, plural } from '@/lib/format';
import {
  Button,
  EmptyState,
  IconButton,
  Menu,
  SearchInput,
  Select,
  useToast,
} from '@/components';
import { ModeDot } from '@/components/Entities';
import { useQuickActions } from '@/app/QuickActions';
import { RenameChatDialog } from './RenameChatDialog';
import styles from './Chats.module.css';

/* -------------------------------------------------------------------------- */
/* Row                                                                        */
/* -------------------------------------------------------------------------- */

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
  const messages = useChatMessages(chat.id);
  const modes = useModes();
  const actions = useActions();
  const mode = modes.find((m) => m.id === chat.mode_id);
  const last = messages[messages.length - 1];

  return (
    <div className={styles.chatRow} data-active={active || undefined}>
      <Link to={`/chats/${chat.id}`} className={styles.chatRowLink}>
        <span className={styles.chatRowTop}>
          <span className={styles.chatRowIdentity}>
            <ModeDot color={mode?.color ?? null} icon={mode?.icon} size="sm" />
            <span className={styles.chatRowTitle}>{chat.title}</span>
          </span>
          <span className={styles.chatRowTime}>
            {chat.pinned && <Pin className={styles.pinIcon} />}
            {formatRelativeTime(chat.updated_at)}
          </span>
        </span>
        <span className={styles.chatRowBottom}>
          <span className={styles.chatRowPreview}>
            {last
              ? last.content.replace(/[*`#]|<sup>[^<]*<\/sup>/g, '').slice(0, 90)
              : 'Нет сообщений — задайте первый вопрос'}
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
              onSelect: () => void actions.updateChat(chat.id, { pinned: !chat.pinned }),
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
/* Pane                                                                       */
/* -------------------------------------------------------------------------- */

export function ChatListPane({ activeChatId }: { activeChatId?: string }) {
  const chats = useChats();
  const modes = useModes();
  const sources = useSources();
  const actions = useActions();
  const quick = useQuickActions();
  const toast = useToast();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [modeFilter, setModeFilter] = useState<string>('all');
  const [renaming, setRenaming] = useState<Chat | null>(null);

  const modeOptions = useMemo(
    () => [
      { value: 'all', label: 'Все режимы' },
      { value: 'quick', label: 'Быстрые чаты' },
      ...modes.map((mode) => ({ value: mode.id, label: mode.name })),
    ],
    [modes],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return chats.filter((chat) => {
      if (modeFilter === 'quick' && chat.mode_id !== null) return false;
      if (modeFilter !== 'all' && modeFilter !== 'quick' && chat.mode_id !== modeFilter) return false;
      if (!q) return true;
      const mode = modes.find((m) => m.id === chat.mode_id);
      return `${chat.title} ${mode?.name ?? ''}`.toLowerCase().includes(q);
    });
  }, [chats, query, modeFilter, modes]);

  const groups = useMemo(() => {
    const now = Date.now();
    const day = 86_400_000;
    const result: Array<{ label: string; items: Chat[] }> = [
      { label: 'Закреплённые', items: [] },
      { label: 'Сегодня', items: [] },
      { label: 'На этой неделе', items: [] },
      { label: 'Ранее', items: [] },
    ];
    for (const chat of filtered) {
      const age = now - new Date(chat.updated_at).getTime();
      if (chat.pinned) result[0].items.push(chat);
      else if (age < day) result[1].items.push(chat);
      else if (age < 7 * day) result[2].items.push(chat);
      else result[3].items.push(chat);
    }
    return result.filter((group) => group.items.length > 0);
  }, [filtered]);

  const handleDelete = async (chat: Chat) => {
    try {
      await actions.deleteChat(chat.id);
      toast.success('Чат удалён', chat.title);
      if (chat.id === activeChatId) navigate('/chats');
    } catch {
      toast.error('Не удалось удалить чат');
    }
  };

  const readySources = sources.filter((s) => s.status === 'ready').length;

  return (
    <section className={styles.listPane} aria-label="Список чатов">
      <header className={styles.listHeader}>
        <div className={styles.listHeaderTop}>
          <h1 className={styles.listTitle}>Чаты</h1>
          <Button
            size="sm" variant="primary" iconLeft={<Plus />}
            onClick={() => quick.newChat(null)}
          >
            Новый
          </Button>
        </div>
        <div className={styles.listControls}>
          <SearchInput
            size="sm" value={query}
            placeholder="Поиск по чатам" onChange={(e) => setQuery(e.target.value)}
            onClear={() => setQuery('')}
          />
          <Select
            size="sm" value={modeFilter}
            options={modeOptions}
            onChange={setModeFilter}
            ariaLabel="Фильтр по режиму" className={styles.modeFilter}
          />
        </div>
      </header>

      <div className={styles.listScroll}>
        {filtered.length === 0 ? (
          <EmptyState
            compact
            icon={<MessagesSquare />}
            title={query ? 'Ничего не найдено' : 'Чатов пока нет'}
            description={
              query
                ? 'Попробуйте изменить запрос или сбросить фильтр по режиму.'
                : 'Создайте чат и выберите режим — от него зависят модель и база знаний.'
            }
            action={
              <Button
                size="sm" variant="primary" iconLeft={<Plus />}
                onClick={() => quick.newChat(null)}
              >
                Новый чат
              </Button>
            }
          />
        ) : (
          groups.map((group) => (
            <div key={group.label} className={styles.chatGroup}>
              <div className={styles.chatGroupLabel}>
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

      <footer className={styles.listFooter}>
        <span>
          {filtered.length} {plural(filtered.length, 'чат', 'чата', 'чатов')} ·{' '}
          {chats.filter((c) => c.pinned).length} закреплено
        </span>
        <span className={styles.listFooterMeta}>
          <BookOpen />
          {readySources} в базе знаний
        </span>
      </footer>

      <RenameChatDialog chat={renaming} onClose={() => setRenaming(null)} />
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty conversation placeholder                                             */
/* -------------------------------------------------------------------------- */

export function ConversationPlaceholder() {
  const chats = useChats();
  const quick = useQuickActions();

  return (
    <div className={styles.placeholder}>
      <EmptyState
        icon={<Zap />}
        title="Выберите чат" description="Откройте диалог слева или начните новый. Быстрый чат отвечает без поиска по источникам, чат режима — с ссылками на документы." action={
          <Button variant="primary" iconLeft={<Plus />} onClick={() => quick.newChat(null)}>
            Новый чат
          </Button>
        }
      />
      {chats.length > 0 && (
        <div className={styles.recentList}>
          <div className={styles.recentLabel}>
            <Pin /> Недавние
          </div>
          {chats.slice(0, 5).map((chat) => (
            <Link key={chat.id} to={`/chats/${chat.id}`} className={cn(styles.recentItem)}>
              <span className={styles.recentTitle}>{chat.title}</span>
              <span className={styles.recentTime}>{formatRelativeTime(chat.updated_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
