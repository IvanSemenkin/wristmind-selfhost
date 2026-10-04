import { useEffect, useRef, useState } from 'react';
import { RouterOutlet, useLocation } from '@/app/router';
import { CommandPalette } from './CommandPalette';
import { MobileNav } from './MobileNav';
import { QuickActionsProvider, useQuickActions } from './QuickActions';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import styles from './AppShell.module.css';

/** Routes that manage their own internal scrolling (two-pane layouts). */
const FIXED_LAYOUT_PREFIXES = ['/chats'];

export function AppShell() {
  const [commandOpen, setCommandOpen] = useState(false);
  const location = useLocation();

  const isFixed = FIXED_LAYOUT_PREFIXES.some(
    (prefix) => location.pathname === prefix || location.pathname.startsWith(`${prefix}/`),
  );

  return (
    <QuickActionsProvider onCommandPaletteOpenChange={setCommandOpen}>
      <AppShellChrome
        commandOpen={commandOpen}
        setCommandOpen={setCommandOpen}
        isFixed={isFixed}
      />
    </QuickActionsProvider>
  );
}

function AppShellChrome({
  commandOpen,
  setCommandOpen,
  isFixed,
}: {
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  isFixed: boolean;
}) {
  const actions = useQuickActions();
  const location = useLocation();
  const scrollRef = useRef<HTMLElement | null>(null);

  // Each route starts at the top of the content area.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [location.pathname]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target != null &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable === true);

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen(true);
        return;
      }
      if (typing) return;
      if (event.key === 'c' && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        actions.newChat(null);
      }
      if (event.key === '/') {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [actions, setCommandOpen]);

  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={styles.main}>
        <Topbar />
        <main className={styles.content} data-fixed={isFixed || undefined} ref={scrollRef}>
          <RouterOutlet />
        </main>
      </div>
      <MobileNav />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
    </div>
  );
}
