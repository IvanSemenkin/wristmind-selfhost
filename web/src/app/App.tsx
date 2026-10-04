import { useEffect, useState } from 'react';
import { SessionContext, type Session, type SessionState } from '@/session';
import { createApiService, WristMindProvider } from '@/services';
import { ConfirmProvider, ToastProvider } from '@/components';
import { ThemeProvider } from './ThemeProvider';
import { AppShell } from './AppShell';
import { BootError, BootScreen, NotFoundPage } from './Chrome';
import { FirstRunWizard } from './FirstRunWizard';
import { RouterProvider } from './router';
import { ROUTES } from './routes';
import { useStoreStatus } from '@/store';

/* =============================================================================
   Application root.

   Composition order: theme → feedback → session → data → router. The data layer
   receives a `Session` and a `WristMindService`; swapping the mock service for
   the HTTP adapter is a one-line change in this file.
   ========================================================================== */

const SESSION_KEY = 'wristmind.web.session';

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SESSION_KEY);
      if (raw) setSession(JSON.parse(raw) as Session);
    } catch {
      window.localStorage.removeItem(SESSION_KEY);
    } finally {
      setHydrated(true);
    }
  }, []);

  if (!hydrated) return <BootScreen />;
  if (!session) return <FirstRunWizard onEnrolled={(next) => {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    setSession(next);
  }} />;

  const sessionState: SessionState = { status: 'authenticated', session };
  const service = createApiService(session, () => {
    window.localStorage.removeItem(SESSION_KEY);
    setSession(null);
  });

  return (
    <ThemeProvider>
      <ToastProvider>
        <ConfirmProvider>
          <SessionContext.Provider value={sessionState}>
            {
              <WristMindProvider session={session} service={service}>
                <RouterProvider routes={ROUTES} fallback={<NotFoundPage />}>
                  <DataGate />
                </RouterProvider>
              </WristMindProvider>
            }
          </SessionContext.Provider>
        </ConfirmProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

/** Holds the boot skeleton until the first dataset has loaded. */
function DataGate() {
  const { status, error } = useStoreStatus();

  if (status === 'error') {
    return (
      <BootError
        message={error ?? 'Не удалось загрузить панель'}
        onRetry={() => window.location.reload()}
      />
    );
  }

  if (status === 'idle' || status === 'loading') return <BootScreen />;

  return <AppShell />;
}
