import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from '@/app/router';
import {
  BookOpen,
  CornerDownLeft,
  Layers,
  LayoutDashboard,
  MessagesSquare,
  Moon,
  Plus,
  Radio,
  Search,
  Settings,
  Sun,
  Watch,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useChats, useModes, useSources } from '@/store';
import { cn } from '@/lib/cn';
import { useEscapeKey, useScrollLock } from '@/lib/hooks';
import { Kbd, useToast } from '@/components';
import { useTheme } from './ThemeProvider';
import { useQuickActions } from './QuickActions';
import { ModeDot } from '@/components/Entities';
import styles from './CommandPalette.module.css';

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  keywords?: string;
  icon?: LucideIcon;
  color?: string;
  run: () => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const modes = useModes();
  const chats = useChats();
  const sources = useSources();
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const actions = useQuickActions();

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useScrollLock(open);
  useEscapeKey(() => onOpenChange(false), open);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActiveIndex(0);
    const raf = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(raf);
  }, [open]);

  const close = () => onOpenChange(false);

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [
      {
        id: 'nav-overview',
        group: 'Переход',
        label: 'Обзор',
        icon: LayoutDashboard,
        keywords: 'dashboard главная обзор система',
        run: () => navigate('/'),
      },
      {
        id: 'nav-chats',
        group: 'Переход',
        label: 'Чаты',
        icon: MessagesSquare,
        keywords: 'диалоги история',
        run: () => navigate('/chats'),
      },
      {
        id: 'nav-modes',
        group: 'Переход',
        label: 'Режимы',
        icon: Layers,
        keywords: 'workspaces пространства',
        run: () => navigate('/modes'),
      },
      {
        id: 'nav-knowledge',
        group: 'Переход',
        label: 'База знаний',
        icon: BookOpen,
        keywords: 'источники rag pdf ocr vision',
        run: () => navigate('/knowledge'),
      },
      {
        id: 'nav-devices',
        group: 'Переход',
        label: 'Устройства',
        icon: Radio,
        keywords: 'подключения телефон часы коды pairing',
        run: () => navigate('/devices'),
      },
      {
        id: 'nav-settings',
        group: 'Переход',
        label: 'Настройки',
        icon: Settings,
        keywords: 'промпт контекст система',
        run: () => navigate('/settings'),
      },
      {
        id: 'act-chat',
        group: 'Действие',
        label: 'Новый чат',
        hint: 'Выбрать режим',
        icon: Plus,
        keywords: 'создать диалог',
        run: () => actions.newChat(null),
      },
      {
        id: 'act-upload',
        group: 'Действие',
        label: 'Загрузить источник',
        hint: 'PDF или изображение',
        icon: BookOpen,
        keywords: 'добавить файл pdf',
        run: () => actions.uploadSource(null),
      },
      {
        id: 'act-mode',
        group: 'Действие',
        label: 'Новый режим',
        hint: 'Модель и база знаний',
        icon: Layers,
        keywords: 'создать режим workspace',
        run: () => actions.createMode(),
      },
      {
        id: 'act-theme',
        group: 'Действие',
        label: theme === 'dark' ? 'Светлая тема' : 'Тёмная тема',
        icon: theme === 'dark' ? Sun : Moon,
        keywords: 'theme оформление тема переключить',
        run: () => {
          toggle();
          toast.toast({ title: theme === 'dark' ? 'Светлая тема включена' : 'Тёмная тема включена' });
        },
      },
    ];

    for (const mode of modes) {
      list.push({
        id: `mode-${mode.id}`,
        group: 'Режимы',
        label: mode.name,
        hint: mode.description,
        color: mode.color,
        keywords: `режим ${mode.name} ${mode.description}`,
        run: () => navigate(`/modes/${mode.id}`),
      });
    }

    for (const chat of chats.slice(0, 24)) {
      const mode = modes.find((m) => m.id === chat.mode_id);
      list.push({
        id: `chat-${chat.id}`,
        group: 'Чаты',
        label: chat.title,
        hint: mode?.name ?? 'Быстрый чат',
        icon: MessagesSquare,
        color: mode?.color,
        keywords: `чат диалог ${chat.title} ${mode?.name ?? ''}`,
        run: () => navigate(`/chats/${chat.id}`),
      });
    }

    for (const source of sources.slice(0, 24)) {
      const mode = modes.find((m) => m.id === source.mode_id);
      list.push({
        id: `source-${source.id}`,
        group: 'Источники',
        label: source.title,
        hint: `${mode?.name ?? 'Режим'} · ${source.status === 'ready' ? 'готово' : source.status === 'error' ? 'ошибка' : 'обработка'}`,
        icon: BookOpen,
        color: mode?.color,
        keywords: `источник документ ${source.title} ${source.filename}`,
        run: () => navigate(`/knowledge/sources/${source.id}`),
      });
    }

    return list;
  }, [modes, chats, sources, navigate, actions, theme, toggle, toast]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      // Without a query, show actions and navigation only — a stable starting point.
      return commands.filter((c) => c.group === 'Действие' || c.group === 'Переход').slice(0, 9);
    }
    const tokens = q.split(/\s+/);
    return commands
      .map((command) => {
        const haystack = `${command.label} ${command.hint ?? ''} ${command.keywords ?? ''}`.toLowerCase();
        let score = 0;
        for (const token of tokens) {
          const index = haystack.indexOf(token);
          if (index === -1) return { command, score: -1 };
          score += index === 0 ? 6 : 3 - Math.min(index / 40, 2);
          if (command.label.toLowerCase().startsWith(token)) score += 4;
        }
        return { command, score };
      })
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 24)
      .map((entry) => entry.command);
  }, [commands, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, Command[]>();
    for (const command of filtered) {
      const bucket = map.get(command.group) ?? [];
      bucket.push(command);
      map.set(command.group, bucket);
    }
    return [...map.entries()];
  }, [filtered]);

  useEffect(() => {
    setActiveIndex((index) => Math.min(index, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, filtered]);

  if (!open) return null;

  const runIndex = (index: number) => {
    const command = filtered[index];
    if (!command) return;
    close();
    command.run();
  };

  let flatIndex = -1;

  return createPortal(
    <div className={styles.overlay}>
      <div className={styles.scrim} onClick={close} />
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Поиск и команды" onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveIndex((i) => (filtered.length ? (i + 1) % filtered.length : 0));
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveIndex((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : 0));
          } else if (event.key === 'Enter') {
            event.preventDefault();
            runIndex(activeIndex);
          }
        }}
      >
        <div className={styles.searchRow}>
          <Search className={styles.searchIcon} />
          <input
            ref={inputRef}
            className={styles.search}
            value={query}
            placeholder="Команды, режимы, чаты, источники…" onChange={(e) => setQuery(e.target.value)}
            spellCheck={false}
            autoComplete="off" role="combobox"
            aria-expanded
            aria-controls="command-palette-results"
            aria-autocomplete="list"
            aria-activedescendant={
              filtered[activeIndex] ? `command-option-${filtered[activeIndex].id}` : undefined
            }
          />
          <Kbd>esc</Kbd>
        </div>

        <div
          className={styles.results}
          ref={listRef}
          id="command-palette-results" role="listbox"
          aria-label="Результаты поиска"
        >
          {filtered.length === 0 && (
            <div className={styles.noResults}>
              Ничего не найдено по запросу «{query}»
              <span>Попробуйте название режима, чата или источника</span>
            </div>
          )}
          {grouped.map(([group, items]) => (
            <div key={group} className={styles.group} role="group" aria-label={group}>
              <div className={styles.groupLabel}>{group}</div>
              {items.map((command) => {
                flatIndex += 1;
                const index = flatIndex;
                const Icon = command.icon;
                return (
                  <button
                    key={command.id}
                    type="button" role="option" id={`command-option-${command.id}`}
                    aria-selected={index === activeIndex}
                    className={styles.item}
                    data-active={index === activeIndex}
                    onMouseMove={() => setActiveIndex(index)}
                    onClick={() => runIndex(index)}
                  >
                    <span className={styles.itemIcon} data-mode-color={command.color}>
                      {command.color ? (
                        <ModeDot color={command.color} size="md" />
                      ) : Icon ? (
                        <Icon />
                      ) : (
                        <Watch />
                      )}
                    </span>
                    <span className={styles.itemLabel}>{command.label}</span>
                    {command.hint && <span className={styles.itemHint}>{command.hint}</span>}
                    {index === activeIndex && (
                      <span className={styles.enterHint}>
                        <CornerDownLeft />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div className={styles.footer}>
          <span className={styles.footerHint}>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> навигация
          </span>
          <span className={styles.footerHint}>
            <Kbd>↵</Kbd> открыть
          </span>
          <span className={cn(styles.footerHint, styles.footerRight)}>
            {filtered.length > 0 ? `${filtered.length} результатов` : 'нет результатов'}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
