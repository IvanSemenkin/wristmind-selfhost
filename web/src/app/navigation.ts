import {
  BookOpen,
  LayoutDashboard,
  Layers,
  MessagesSquare,
  FileText,
  Radio,
  Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  shortLabel?: string;
  icon: LucideIcon;
  /** Match the path exactly (used for the index route). */
  end?: boolean;
  /** Extra path prefixes that should keep this item active. */
  match?: string[];
  description: string;
}

export interface NavGroup {
  id: string;
  label: string | null;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'work',
    label: 'Работа',
    items: [
      {
        to: '/',
        label: 'Обзор',
        icon: LayoutDashboard,
        end: true,
        description: 'Состояние системы, активность и быстрые действия',
      },
      {
        to: '/chats',
        label: 'Чаты',
        match: ['/chats'],
        icon: MessagesSquare,
        description: 'Диалоги с помощником, история и потоковые ответы',
      },
      {
        to: '/modes',
        label: 'Режимы',
        match: ['/modes'],
        icon: Layers,
        description: 'Рабочие пространства: модель, промпт, база знаний',
      },
      {
        to: '/knowledge',
        label: 'База знаний',
        match: ['/knowledge'],
        icon: BookOpen,
        description: 'Источники, обработка PDF и изображений, фрагменты',
      },
    ],
  },
  {
    id: 'system',
    label: 'Система',
    items: [
      {
        to: '/devices',
        label: 'Устройства',
        icon: Radio,
        description: 'Подключённые устройства, коды подключения и доступ',
      },
      {
        to: '/settings',
        label: 'Настройки',
        icon: Settings,
        description: 'Контекст диалога и параметры системы',
      },
      {
        to: '/prompts',
        label: 'Промпты',
        icon: FileText,
        description: 'Системные и внутренние промпты',
      },
    ],
  },
];

/** True when the given pathname should highlight the nav item. */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.to === '/' && pathname === '/main') return true;
  if (item.end) return pathname === item.to;
  const prefixes = item.match ?? [item.to];
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
