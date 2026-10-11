import { isTalkPath } from '@/lib/chatSurface';
import { TalkSidebar } from '@/pages/talk/TalkSidebar';
import { useEffect, useRef, useState } from 'react';
import { RouterOutlet, useLocation, useNavigate } from '@/app/router';
import { CommandPalette } from './CommandPalette';
import { MobileNav } from './MobileNav';
import { QuickActionsProvider, useQuickActions } from './QuickActions';
import { Sidebar } from './Sidebar';
import styles from './AppShell.module.css';

/** Routes that manage their own internal scrolling (two-pane layouts). */
const FIXED_LAYOUT_PREFIXES = ['/chats', '/talk'];

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
  const talk = isTalkPath(location.pathname);
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);

  // Mobile keyboards shrink the visual viewport, while 100dvh may remain unchanged.
  useEffect(() => {
    const viewport = window.visualViewport;
    const shell = shellRef.current;
    if (!viewport || !shell || !isFixed) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (viewport.scale !== 1) {
          delete shell.dataset.chatViewport;
          delete shell.dataset.keyboard;
          return;
        }
        shell.dataset.chatViewport = 'true';
        shell.style.setProperty('--chat-viewport-height', `${viewport.height}px`);
        shell.style.setProperty('--chat-viewport-top', `${viewport.offsetTop}px`);
        const active = document.activeElement;
        const editing = active instanceof HTMLElement && (active.matches('input, textarea') || active.isContentEditable);
        if (editing && window.innerHeight - viewport.height > 140) shell.dataset.keyboard = 'true';
        else delete shell.dataset.keyboard;
      });
    };
    update();
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
      delete shell.dataset.chatViewport;
      delete shell.dataset.keyboard;
      shell.style.removeProperty('--chat-viewport-height');
      shell.style.removeProperty('--chat-viewport-top');
    };
  }, [isFixed]);

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
        if (talk) navigate('/talk');
        else actions.newChat(null);
      }
      if (event.key === '/') {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [actions, setCommandOpen, talk, navigate]);

  return (
    <div className={styles.shell} ref={shellRef} data-talk={talk || undefined}>
      {talk ? <TalkSidebar /> : <Sidebar />}
      <div className={styles.main}>
        {/* The top plate (search field, command shortcut, create menu, mini
            logo) was removed on the owner's request: none of it was ever used,
            and every page already carries its own primary action. The command
            palette stays reachable through QuickActions and its keyboard
            shortcut. */}
        <main className={styles.content} data-fixed={isFixed || undefined} ref={scrollRef}>
          <RouterOutlet />
        </main>
      </div>
      {!talk && <MobileNav />}
      <CommandPalette open={!talk && commandOpen} onOpenChange={setCommandOpen} />
    </div>
  );
}
