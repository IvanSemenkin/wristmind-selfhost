import { Link, NavLink } from '@/app/router';
import { Plus, Watch } from 'lucide-react';
import { useServiceHealth, useSettings } from '@/store';
import { useIsMobile } from '@/lib/hooks';
import { isNavItemActive, NAV_GROUPS } from '@/app/navigation';
import { useQuickActions } from '@/app/QuickActions';
import { IconButton, Tooltip } from '@/components';
import { useLocation, useParams } from '@/app/router';
import { ChatList } from '@/pages/chats/ChatListPane';
import styles from './AppShell.module.css';

export function Sidebar() {
  const location = useLocation();
  const params = useParams<{ chatId?: string }>();
  const settings = useSettings();
  const services = useServiceHealth();
  const quick = useQuickActions();
  const isMobile = useIsMobile();

  const degraded = services.filter((s) => s.status !== 'operational').length;
  /* The conversation list belongs to the chat workspace only. On every other
     page the rail stays a navigation rail. */
  const onChats = location.pathname === '/chats' || location.pathname.startsWith('/chats/');
  const showChatList = onChats && !isMobile;

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark} aria-hidden>
          <Watch />
        </span>
        <span className={styles.brandText}>
          <span className={styles.brandName}>WristMind</span>
          <span className={styles.brandSub}>Console</span>
        </span>
      </div>

      <Link to="/talk" className={styles.navItem}><Plus className={styles.navIcon} />Открыть приложение чатов</Link>
      <nav className={styles.nav} aria-label="Основная навигация">
        {NAV_GROUPS.map((group) => (
          <div key={group.id} className={styles.navGroup}>
            {group.label && <div className={styles.navGroupLabel}>{group.label}</div>}
            <ul className={styles.navList}>
              {group.items.filter((item) => item.to !== '/prompts' || settings?.developer_mode).map((item) => {
                const active = isNavItemActive(item, location.pathname);
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      className={styles.navItem}
                      data-active={active || undefined}
                      title={item.description}
                    >
                      <Icon className={styles.navIcon} />
                      <span className={styles.navLabel}>{item.label}</span>
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* ChatGPT's information architecture: the conversation list is the
          rail's own content, not a second column beside it. The per-mode
          shortcut list that used to live here was removed to make room — modes
          have their own page, a picker in the new-chat flow, and a colour dot
          on every chat row. */}
      {showChatList && (
        <section className={styles.railChats} aria-label="Чаты">
          <div className={styles.navGroupLabelRow}>
            <span className={styles.navGroupLabel}>Чаты</span>
            <Tooltip label="Новый чат">
              <IconButton
                size="xs" label="Новый чат" icon={<Plus />}
                onClick={() => quick.newChat(null)}
                className={styles.navGroupAction}
              />
            </Tooltip>
          </div>
          <ChatList variant="rail" activeChatId={params.chatId} />
        </section>
      )}

      {/* No theme switch here by the owner's request: the desktop rail is for
          navigation. The theme is still switchable in Настройки and from the
          command palette (Ctrl/⌘+K), and the mobile "Ещё" sheet keeps its own
          control. */}
      <div className={styles.sidebarFooter}>
        {degraded > 0 && (
          <Link to="/devices" className={styles.degradedNotice}>
            {degraded === 1 ? 'Одно устройство требует внимания' : `${degraded} сервиса требуют внимания`}
          </Link>
        )}
      </div>
    </aside>
  );
}
