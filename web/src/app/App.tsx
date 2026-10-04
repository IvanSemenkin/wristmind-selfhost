import { useEffect, useState } from 'react';
import { SessionContext, type Session, type SessionState } from '@/session';
import { createApiService, enrollWebSession, WristMindProvider } from '@/services';
import { ConfirmProvider, ToastProvider, Button, Field, Input, Panel, PanelBody } from '@/components';
import { ThemeProvider } from './ThemeProvider';
import { AppShell } from './AppShell';
import { BootError, BootScreen, NotFoundPage } from './Chrome';
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
  if (!session) return <EnrollmentScreen onEnrolled={(next) => {
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

function EnrollmentScreen({ onEnrolled }: { onEnrolled: (session: Session) => void }) {
  const [baseUrl, setBaseUrl] = useState(() => window.location.origin);
  const [method, setMethod] = useState<'code' | 'secret'>('code');
  const [credential, setCredential] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const session = await enrollWebSession(baseUrl, method, credential.trim());
      onEnrolled(session);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось подключить панель');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 24 }}>
      <div style={{ width: 'min(100%, 440px)' }}><Panel><PanelBody>
        <div style={{ display: 'grid', gap: 12, marginBottom: 24 }}>
          <h1 style={{ margin: 0 }}>Подключить WristMind</h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Введите адрес API и одноразовый код из уже подключённой панели.</p>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); void submit(); }} style={{ display: 'grid', gap: 16 }}>
          <Field label="Адрес API" htmlFor="api-url">
            <Input id="api-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} mono />
          </Field>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <Button type="button" variant={method === 'code' ? 'primary' : 'secondary'} onClick={() => setMethod('code')}>Код доступа</Button>
            <Button type="button" variant={method === 'secret' ? 'primary' : 'secondary'} onClick={() => setMethod('secret')}>Bootstrap secret</Button>
          </div>
          <Field label={method === 'code' ? 'Одноразовый код' : 'Bootstrap secret'} htmlFor="credential" error={error ?? undefined}>
            <Input id="credential" type={method === 'secret' ? 'password' : 'text'} value={credential} onChange={(event) => setCredential(event.target.value)} mono autoComplete="off" />
          </Field>
          <Button type="submit" variant="primary" loading={busy} disabled={!baseUrl.trim() || !credential.trim()} block>Подключить панель</Button>
        </form>
      </PanelBody></Panel></div>
    </main>
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
