import { Link, NavLink } from '@/app/router';
import { Moon, Plus, Sun, Watch } from 'lucide-react';
import { useModes, useServiceHealth, useSettings } from '@/store';
import { cn } from '@/lib/cn';
import { useTheme } from '@/app/ThemeProvider';
import { isNavItemActive, NAV_GROUPS } from '@/app/navigation';
import { useQuickActions } from '@/app/QuickActions';
import { IconButton, Tooltip } from '@/components';
import { ModeDot } from '@/components/Entities';
import { useLocation } from '@/app/router';
import styles from './AppShell.module.css';

export function Sidebar() {
  const location = useLocation();
  const { createMode } = useQuickActions();
  const modes = useModes();
  const settings = useSettings();
  const services = useServiceHealth();
  const { theme, toggle } = useTheme();

  const degraded = services.filter((s) => s.status !== 'operational').length;

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

        <div className={styles.navGroup}>
          <div className={styles.navGroupLabelRow}>
            <span className={styles.navGroupLabel}>Режимы</span>
            <Tooltip label="Новый режим">
              <IconButton
                size="xs" label="Новый режим" icon={<Plus />}
                onClick={createMode}
                className={styles.navGroupAction}
              />
            </Tooltip>
          </div>
          <ul className={styles.modeNavList}>
            {modes.slice(0, 7).map((mode) => (
              <li key={mode.id}>
                <NavLink
                  to={`/modes/${mode.id}`}
                  className={styles.modeNavItem}
                  data-active={location.pathname.startsWith(`/modes/${mode.id}`) || undefined}
                  data-mode-color={mode.color}
                  title={mode.description}
                >
                  <ModeDot color={mode.color} size="sm" />
                  <span className={styles.modeNavLabel}>{mode.name}</span>
                  {!mode.hidden_on_watch && <Watch className={styles.modeNavWatch} />}
                </NavLink>
              </li>
            ))}
            {modes.length === 0 && <li className={styles.modeNavEmpty}>Пока нет режимов</li>}
          </ul>
        </div>
      </nav>

      <div className={styles.sidebarFooter}>
        <div className={styles.footerRow}>
          <Tooltip label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
            <IconButton
              size="sm" label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
              icon={theme === 'dark' ? <Sun /> : <Moon />}
              onClick={toggle}
            />
          </Tooltip>
        </div>
        {degraded > 0 && (
          <Link to="/devices" className={styles.degradedNotice}>
            {degraded === 1 ? 'Одно устройство требует внимания' : `${degraded} сервиса требуют внимания`}
          </Link>
        )}
      </div>
    </aside>
  );
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn(styles.brandMark, className)} aria-hidden>
      <Watch />
    </span>
  );
}
