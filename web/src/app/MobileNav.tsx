import { useState } from 'react';
import { NavLink, useLocation, useNavigate } from '@/app/router';
import { LayoutDashboard, MessagesSquare, Layers, BookOpen, MoreHorizontal, Moon, Sun, Radio, Settings, Watch, FileText } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useModes, useSettings } from '@/store';
import { isNavItemActive } from '@/app/navigation';
import { useTheme } from '@/app/ThemeProvider';
import { useQuickActions } from '@/app/QuickActions';
import { Drawer, IconButton } from '@/components';
import { ModeDot } from '@/components/Entities';
import styles from './AppShell.module.css';

interface TabDef {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  match?: string[];
}

const PRIMARY_TABS: TabDef[] = [
  { to: '/', label: 'Обзор', icon: LayoutDashboard, end: true },
  { to: '/chats', label: 'Чаты', icon: MessagesSquare, match: ['/chats'] },
  { to: '/modes', label: 'Режимы', icon: Layers, match: ['/modes'] },
  { to: '/knowledge', label: 'Знания', icon: BookOpen, match: ['/knowledge'] },
];

export function MobileNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const [moreOpen, setMoreOpen] = useState(false);
  const modes = useModes();
  const settings = useSettings();
  const { theme, toggle } = useTheme();
  const actions = useQuickActions();

  const moreActive =
    isNavItemActive({ to: '/devices', label: '', icon: Radio, description: '' }, location.pathname) ||
    isNavItemActive({ to: '/settings', label: '', icon: Settings, description: '' }, location.pathname) ||
    (settings?.developer_mode && isNavItemActive({ to: '/prompts', label: '', icon: FileText, description: '' }, location.pathname));

  return (
    <>
      <nav className={styles.mobileNav} aria-label="Навигация">
        {PRIMARY_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = isNavItemActive({ ...tab, description: '' }, location.pathname);
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={styles.mobileTab}
              data-active={active || undefined}
            >
              <Icon />
              <span>{tab.label}</span>
            </NavLink>
          );
        })}
        <button
          type="button" className={styles.mobileTab}
          data-active={moreActive || undefined}
          onClick={() => setMoreOpen(true)}
        >
          <MoreHorizontal />
          <span>Ещё</span>
        </button>
      </nav>

      <Drawer
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title="Ещё"
      >
        <div className={styles.moreSheet}>
          <div className={styles.moreActions}>
            <button
              type="button" className={styles.moreAction}
              onClick={() => {
                setMoreOpen(false);
                actions.newChat(null);
              }}
            >
              <MessagesSquare />
              Новый чат
            </button>
            <button
              type="button" className={styles.moreAction}
              onClick={() => {
                setMoreOpen(false);
                actions.uploadSource(null);
              }}
            >
              <BookOpen />
              Загрузить источник
            </button>
          </div>

          <div className={styles.moreSection}>
            <div className={styles.moreSectionLabel}>Система</div>
            <button
              type="button" className={styles.moreLink}
              onClick={() => {
                setMoreOpen(false);
                void navigate('/devices');
              }}
            >
              <Radio />
              <span className={styles.moreLinkText}>
                <span>Устройства</span>
                <span className={styles.moreLinkSub}>Подключения, коды, отзыв доступа</span>
              </span>
            </button>
            <button
              type="button" className={styles.moreLink}
              onClick={() => {
                setMoreOpen(false);
                void navigate('/settings');
              }}
            >
              <Settings />
              <span className={styles.moreLinkText}>
                <span>Настройки</span>
                <span className={styles.moreLinkSub}>Контекст и параметры</span>
              </span>
            </button>
            {settings?.developer_mode && (
              <button type="button" className={styles.moreLink} onClick={() => { setMoreOpen(false); void navigate('/prompts'); }}>
                <FileText />
                <span className={styles.moreLinkText}>
                  <span>Промпты</span>
                  <span className={styles.moreLinkSub}>Системные и внутренние инструкции</span>
                </span>
              </button>
            )}
          </div>

          {modes.length > 0 && (
            <div className={styles.moreSection}>
              <div className={styles.moreSectionLabel}>Режимы</div>
              {modes.map((mode) => (
                <button
                  key={mode.id}
                  type="button" className={styles.moreLink}
                  data-mode-color={mode.color}
                  onClick={() => {
                    setMoreOpen(false);
                    void navigate(`/modes/${mode.id}`);
                  }}
                >
                  <ModeDot color={mode.color} size="md" />
                  <span className={styles.moreLinkText}>
                    <span>{mode.name}</span>
                    <span className={styles.moreLinkSub}>{mode.description || 'Без описания'}</span>
                  </span>
                  {!mode.hidden_on_watch && <Watch className={styles.moreWatch} />}
                </button>
              ))}
            </div>
          )}

          <div className={styles.moreFooter}>
            <span className={styles.moreFooterText}>Тема оформления</span>
            <IconButton
              size="md" label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
              icon={theme === 'dark' ? <Sun /> : <Moon />}
              outlined
              onClick={toggle}
            />
          </div>
        </div>
      </Drawer>
    </>
  );
}
