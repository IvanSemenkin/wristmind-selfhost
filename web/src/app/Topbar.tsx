import { Link, useNavigate } from '@/app/router';
import { BookOpen, ChevronDown, Layers, Moon, Plus, Search, Sun, Watch, Zap } from 'lucide-react';
import { useServiceHealth } from '@/store';
import { useTheme } from '@/app/ThemeProvider';
import { useQuickActions } from '@/app/QuickActions';
import { Button, IconButton, Kbd, Menu, Tooltip } from '@/components';
import { SERVICE_STATUS_META } from '@/components/Entities';
import styles from './AppShell.module.css';

export function Topbar() {
  const { theme, toggle } = useTheme();
  const actions = useQuickActions();
  const services = useServiceHealth();
  const navigate = useNavigate();

  const problems = services.filter((s) => s.status !== 'operational');

  return (
    <header className={styles.topbar}>
      <div className={styles.topbarLeft}>
        <Link to="/" className={styles.mobileBrand} aria-label="WristMind Console">
          <span className={styles.brandMark} aria-hidden>
            <Watch />
          </span>
          <span className={styles.mobileBrandName}>WristMind</span>
        </Link>
        <button
          type="button" className={styles.commandTrigger}
          onClick={actions.openCommandPalette}
          aria-label="Поиск и команды"
        >
          <Search />
          <span className={styles.commandTriggerLabel}>Поиск</span>
          <Kbd className={styles.commandTriggerKbd}>⌘K</Kbd>
        </button>
      </div>

      <div className={styles.topbarRight}>
        {problems.length > 0 && (
          <Tooltip label={problems.map((p) => `${p.label}: ${SERVICE_STATUS_META[p.status].label}`).join(' · ')}>
            <Link to="/devices" className={styles.problemPill}>
              <span className={styles.problemDot} />
              <span className={styles.problemText}>{problems.length}</span>
            </Link>
          </Tooltip>
        )}

        <Tooltip label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
          <IconButton
            size="sm" label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
            icon={theme === 'dark' ? <Sun /> : <Moon />}
            onClick={toggle}
            className={styles.topbarIcon}
          />
        </Tooltip>

        <Menu
          align="end" width={252}
          entries={[
            {
              type: 'item',
              id: 'chat',
              label: 'Новый чат',
              description: 'Выбрать режим или быстрый чат',
              icon: <Plus />,
              shortcut: 'C',
              onSelect: () => actions.newChat(null),
            },
            {
              type: 'item',
              id: 'upload',
              label: 'Загрузить источник',
              description: 'PDF или изображение в базу знаний',
              icon: <BookOpen />,
              onSelect: () => actions.uploadSource(null),
            },
            {
              type: 'item',
              id: 'mode',
              label: 'Новый режим',
              description: 'Модель, промпт и своя база знаний',
              icon: <Layers />,
              onSelect: () => actions.createMode(),
            },
            { type: 'separator' },
            {
              type: 'item',
              id: 'quick',
              label: 'Быстрый вопрос на часах',
              description: 'Открыть быстрый чат без базы знаний',
              icon: <Zap />,
              onSelect: () => {
                void navigate('/chats?quick=1');
              },
            },
          ]}
          trigger={
            <Button variant="primary" size="sm" iconRight={<ChevronDown />} iconLeft={<Plus />}>
              <span className={styles.createLabel}>Создать</span>
            </Button>
          }
        />
      </div>
    </header>
  );
}
