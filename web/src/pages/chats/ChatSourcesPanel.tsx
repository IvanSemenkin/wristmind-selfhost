import { useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, ArrowUpRight, Layers } from 'lucide-react';
import { Badge, Button, Drawer, Spinner } from '@/components';
import { useService } from '@/services';
import { describeError } from '@/services/errors';
import type { ChatWorkingSourceText } from '@/types';
import { formatDate } from '@/lib/format';
import {
  countChatSourceKinds,
  filterChatSourceCards,
  sourceMonogram,
  type ChatSourceCard,
  type ChatSourceFilter,
} from '@/lib/chatSources';
import cardStyles from './MessageSources.module.css';
import styles from './ChatSourcesPanel.module.css';

/* =============================================================================
   "Источники чата" panel — one Drawer for two scopes:

     • chat    — every unique source of the conversation (header button);
     • message — only the sources bound to one answer (per-answer button).

   Both scopes reuse the shared `Drawer`, which already renders a right-hand
   drawer on desktop and a bottom sheet below the mobile breakpoint.
   ========================================================================== */

const FILTERS: { id: ChatSourceFilter; label: string }[] = [
  { id: 'all', label: 'Все' },
  { id: 'working', label: 'Сохранённые' },
  { id: 'read', label: 'Прочитанные' },
  { id: 'referenced', label: 'Ссылки' },
];

export interface ChatSourcesPanelProps {
  chatId: string;
  open: boolean;
  onClose: () => void;
  /** `message` switches the panel to per-answer scope. */
  mode: 'chat' | 'message';
  /** Cards already scoped to the chat or to the selected answer. */
  cards: ChatSourceCard[];
  loading: boolean;
  error: string | null;
  filter: ChatSourceFilter;
  onFilterChange: (filter: ChatSourceFilter) => void;
  /** Leaves per-answer mode and shows the whole chat index. */
  onShowAll: () => void;
  onRetry: () => void;
}

/** `Intl` throws on an invalid date, so unparseable timestamps are dropped. */
function safeDate(iso: string | null): string | null {
  if (!iso) return null;
  const timestamp = new Date(iso).getTime();
  if (Number.isNaN(timestamp)) return null;
  return formatDate(iso);
}

function SourceCard({ card, onOpenWorking }: { card: ChatSourceCard; onOpenWorking: (card: ChatSourceCard) => void }) {
  const working = card.kind === 'working';
  const created = working ? safeDate(card.createdAt) : null;

  const body = (
    <>
      <span className={cardStyles.monogram} aria-hidden>
        {sourceMonogram(card)}
      </span>
      <span className={cardStyles.cardBody}>
        <span className={cardStyles.cardTitle}>{card.title}</span>
        <span className={cardStyles.cardMeta}>
          {card.domain && <span className={cardStyles.cardDomain}>{card.domain}</span>}
          <Badge tone={working && card.status === 'ready' ? 'accent' : 'neutral'} size="sm">
            {working
              ? card.status === 'ready'
                ? 'Текст сохранён в чат'
                : card.status === 'failed'
                  ? 'Сохранён, обработка не удалась'
                  : card.status
                    ? 'Текст сохранён, обрабатывается'
                    : 'Статус не подтверждён'
              : card.kind === 'read' ? 'Страница прочитана' : 'Найденная ссылка'}
          </Badge>
          {working && card.originTitle && (
            <span className={cardStyles.cardPage} title={card.originTitle}>
              из «{card.originTitle}»
            </span>
          )}
          {created && <span className={cardStyles.cardPage}>{created}</span>}
        </span>
        {!working && card.snippet && <span className={cardStyles.cardSnippet}>{card.snippet}</span>}
        {!working && <span className={styles.sourceNote}>{card.kind === 'read'
          ? 'Текст страницы получен ботом. В рабочие материалы не добавлен.'
          : 'Страница не прочитана ботом. Сохранена ссылка и фрагмент поисковой выдачи.'}</span>}
        {working && (
          <span className={styles.sourceActions}>
            {card.status && (
              <button type="button" className={styles.sourceAction} onClick={() => onOpenWorking(card)}>
                Проверить сохранённый текст
              </button>
            )}
            {card.url && <a href={card.url} target="_blank" rel="noopener noreferrer">Открыть исходную страницу</a>}
          </span>
        )}
      </span>
    </>
  );

  if (!working && card.url) {
    return (
      <a
        className={cardStyles.card}
        href={card.url}
        target="_blank" rel="noopener noreferrer" title={card.url}
      >
        {body}
        <ArrowUpRight className={cardStyles.cardArrow} aria-hidden />
      </a>
    );
  }

  return (
    <div className={cardStyles.card} data-static="true">
      {body}
      <Layers className={cardStyles.cardArrow} aria-hidden />
    </div>
  );
}

function CardList({ cards, empty, onOpenWorking }: { cards: ChatSourceCard[]; empty: string; onOpenWorking: (card: ChatSourceCard) => void }) {
  if (cards.length === 0) return <p className={cardStyles.note}>{empty}</p>;
  return (
    <ul className={cardStyles.list}>
      {cards.map((card) => (
        <li key={card.key}>
          <SourceCard card={card} onOpenWorking={onOpenWorking} />
        </li>
      ))}
    </ul>
  );
}

export function ChatSourcesPanel({
  chatId,
  open,
  onClose,
  mode,
  cards,
  loading,
  error,
  filter,
  onFilterChange,
  onShowAll,
  onRetry,
}: ChatSourcesPanelProps) {
  const service = useService();
  const [selected, setSelected] = useState<ChatSourceCard | null>(null);
  const [savedText, setSavedText] = useState<ChatWorkingSourceText | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const requestVersion = useRef(0);
  const openWorking = (card: ChatSourceCard) => {
    const version = ++requestVersion.current;
    setSelected(card);
    setSavedText(null);
    setTextError(null);
    setTextLoading(true);
    void service.chats.workingSourceText(chatId, card.id)
      .then((value) => { if (requestVersion.current === version) setSavedText(value); })
      .catch((cause: unknown) => {
        if (requestVersion.current === version) setTextError(describeError(cause, 'Не удалось открыть сохранённый текст'));
      })
      .finally(() => { if (requestVersion.current === version) setTextLoading(false); });
  };
  const closeText = () => {
    requestVersion.current += 1;
    setSelected(null);
  };
  const isMessage = mode === 'message';
  const counts = useMemo(() => countChatSourceKinds(cards), [cards]);
  const visible = useMemo(() => filterChatSourceCards(cards, filter), [cards, filter]);

  const workingCards = visible.filter((card) => card.kind === 'working');
  const readCards = visible.filter((card) => card.kind === 'read');
  const referencedCards = visible.filter((card) => card.kind === 'referenced');

  const emptyScope = isMessage
    ? 'В этом ответе нет источников.'
    : 'В этом чате пока нет найденных источников.';
  const emptyReferenced = isMessage
    ? 'В этом ответе нет найденных источников.'
    : 'В этом чате пока нет найденных источников.';

  const countFor = (id: ChatSourceFilter) => counts[id];

  return (
    <Drawer
      open={open}
      onClose={() => { closeText(); onClose(); }}
      size="md" eyebrow={isMessage ? 'Конкретный ответ' : 'Текущий чат'}
      title={isMessage ? 'Источники этого ответа' : 'Источники чата'}
      description={
        isMessage
          ? 'Материалы и страницы этого ответа.'
          : 'Сохранённые материалы, прочитанные страницы и найденные ссылки этого чата. Отдельно от базы знаний режима.'
      }
    >
      {selected ? (
        <div className={styles.textDetail}>
          <button type="button" className={styles.back} onClick={closeText}>
            <ArrowLeft aria-hidden /> К списку источников
          </button>
          <h3>{selected.title}</h3>
          {textLoading ? <Spinner label="Загрузка сохранённого текста" /> : textError ? (
            <div className={styles.state} data-tone="danger" role="alert">
              <AlertTriangle aria-hidden /> <span>{textError}</span>
              <Button size="sm" variant="secondary" onClick={() => openWorking(selected)}>Повторить</Button>
            </div>
          ) : savedText ? (
            <>
              <p className={styles.textMeta}>Сохранено в этом чате · {savedText.character_count.toLocaleString('ru-RU')} символов</p>
              <pre className={styles.savedText}>{savedText.content}</pre>
            </>
          ) : null}
        </div>
      ) : loading ? (
        <div className={styles.state} role="status">
          <Spinner label="Загрузка источников" />
          <span>Загружаем источники…</span>
        </div>
      ) : error ? (
        <div className={styles.state} data-tone="danger" role="alert">
          <AlertTriangle aria-hidden />
          <span>{error}</span>
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Повторить
          </Button>
        </div>
      ) : (
        <>
          {isMessage && (
            <button type="button" className={styles.back} onClick={onShowAll}>
              <ArrowLeft aria-hidden />
              Все источники чата
            </button>
          )}

          <div className={cardStyles.filters} role="group" aria-label="Фильтр источников чата">
            {FILTERS.map((item) => (
              <button
                key={item.id}
                type="button" className={cardStyles.filter}
                data-active={filter === item.id || undefined}
                aria-pressed={filter === item.id}
                onClick={() => onFilterChange(item.id)}
              >
                {item.label}
                <span className={cardStyles.filterCount}>{countFor(item.id)}</span>
              </button>
            ))}
          </div>

          {cards.length === 0 ? (
            <p className={cardStyles.note}>{emptyScope}</p>
          ) : (
            <>
              {(filter === 'all' || filter === 'working') && (
                <section className={styles.section}>
                  <h3 className={styles.sectionTitle}>
                    Сохранённые материалы
                    <span className={styles.sectionCount}>{counts.working}</span>
                  </h3>
                  <CardList
                    cards={workingCards}
                    empty="Рабочих материалов в этом чате пока нет." onOpenWorking={openWorking}
                  />
                </section>
              )}
              {(filter === 'all' || filter === 'read') && (
                <section className={styles.section}>
                  <h3 className={styles.sectionTitle}>
                    Прочитанные страницы
                    <span className={styles.sectionCount}>{counts.read}</span>
                  </h3>
                  <CardList cards={readCards} empty="Прочитанных страниц пока нет." onOpenWorking={openWorking} />
                </section>
              )}
              {(filter === 'all' || filter === 'referenced') && (
                <section className={styles.section}>
                  <h3 className={styles.sectionTitle}>
                    Найденные ссылки
                    <span className={styles.sectionCount}>{counts.referenced}</span>
                  </h3>
                  <CardList cards={referencedCards} empty={emptyReferenced} onOpenWorking={openWorking} />
                </section>
              )}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
