import { useEffect, useMemo, useState } from 'react';
import type { Session } from '@/session';
import { enrollWebSession } from '@/services';
import { Button, Field, Input, Panel, PanelBody } from '@/components';
import {
  checkProviderKey,
  completeSetup,
  fetchSetupStatus,
  type SetupStatus,
} from '@/services/setup';

/* =============================================================================
   First-run wizard.

   Shown whenever the panel has no session. It answers the three questions a
   new owner actually has, in order: is this installation reachable and empty,
   who owns it, and can it already answer. Everything is checked live against
   `/v1/setup/*`; nothing is claimed without evidence.

   The visual shell is intentionally plain: this screen is a gate, not a page
   of the console, and it is rendered before the router exists.
   ========================================================================== */

const SESSION_KEY = 'wristmind.web.session';

export function FirstRunWizard({ onEnrolled }: { onEnrolled: (session: Session) => void }) {
  const [baseUrl, setBaseUrl] = useState(() => window.location.origin);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [probing, setProbing] = useState(false);
  // `enroll` collects credentials; `verify` stays on screen after the session
  // exists so the owner can check a model key before entering the console.
  const [stage, setStage] = useState<'enroll' | 'verify'>('enroll');

  const [method, setMethod] = useState<'code' | 'secret'>('code');
  const [credential, setCredential] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);

  const [provider, setProvider] = useState<'openrouter' | 'deepseek'>('openrouter');
  const [apiKey, setApiKey] = useState('');
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<{ ok: boolean; message: string } | null>(null);

  const probe = async (url: string) => {
    setProbing(true);
    setStatus(await fetchSetupStatus(url));
    setProbing(false);
  };

  useEffect(() => {
    void probe(window.location.origin);
    // Probing only the initial address is intended: the user can re-probe with
    // the button after editing the field.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const enrolled = await enrollWebSession(baseUrl, method, credential.trim());
      setSession(enrolled);
      // Persist right away: the panel is already usable, and access must
      // survive a reload even if the owner stops before the console opens.
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(enrolled));
      setStage('verify');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось подключить панель');
      void probe(baseUrl);
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setChecking(true);
    setCheck(null);
    const result = await checkProviderKey(baseUrl, provider, apiKey);
    setCheck({ ok: result.ok, message: result.message });
    setChecking(false);
    if (result.ok && session) void completeSetup(baseUrl, session.token);
  };

  const ownerReady = status?.instance_claimed === true;

  const headline = useMemo(() => {
    if (status === null) return 'Проверяем сервер…';
    if (!status.database_ok) return 'Сервер отвечает, но база данных недоступна';
    if (status.instance_claimed) return 'WristMind уже подключён';
    return 'Первый запуск WristMind';
  }, [status]);

  return (
    <main style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 24 }}>
      <div style={{ width: 'min(100%, 520px)' }}>
        <Panel>
          <PanelBody>
            <div style={{ display: 'grid', gap: 8, marginBottom: 20 }}>
              <h1 style={{ margin: 0 }}>{headline}</h1>
              <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                {ownerReady
                  ? 'Этот сервер уже закреплён за владельцем. Подключите новую сессию одноразовым кодом из работающей панели.'
                  : 'Проверьте состояние сервера и подключите панель. Первое подключение использует bootstrap-секрет из server/.env.'}
              </p>
            </div>

            <SetupChecklist status={status} probing={probing} />

            <Field label="Адрес API" htmlFor="api-url">
              <Input
                id="api-url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                mono
              />
            </Field>
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void probe(baseUrl)}
                loading={probing}
              >
                Проверить адрес
              </Button>
            </div>

            {stage === 'enroll' ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void submit();
                }}
                style={{ display: 'grid', gap: 16 }}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <Button
                    type="button"
                    variant={method === 'code' ? 'primary' : 'secondary'}
                    onClick={() => setMethod('code')}
                  >
                    Код доступа
                  </Button>
                  <Button
                    type="button"
                    variant={method === 'secret' ? 'primary' : 'secondary'}
                    onClick={() => setMethod('secret')}
                  >
                    Bootstrap secret
                  </Button>
                </div>
                <Field
                  label={method === 'code' ? 'Одноразовый код' : 'Bootstrap secret'}
                  htmlFor="credential"
                  error={error ?? undefined}
                >
                  <Input
                    id="credential"
                    type={method === 'secret' ? 'password' : 'text'}
                    value={credential}
                    onChange={(event) => setCredential(event.target.value)}
                    mono
                    autoComplete="off"
                  />
                </Field>
                <Button
                  type="submit"
                  variant="primary"
                  loading={busy}
                  disabled={!baseUrl.trim() || !credential.trim()}
                  block
                >
                  {ownerReady ? 'Подключить панель' : 'Закрепить сервер за собой'}
                </Button>
              </form>
            ) : (
              <div style={{ display: 'grid', gap: 16 }}>
                <div
                  style={{
                    display: 'grid',
                    gap: 6,
                    padding: 12,
                    border: '1px solid var(--border-subtle, #333)',
                    borderRadius: 10,
                  }}
                >
                  <strong style={{ fontSize: 14 }}>Панель подключена</strong>
                  <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                    Дальше — ключ модели. Без него сервер отвечает тестовыми
                    заготовками: это режим проверки, а не рабочий.
                  </span>
                </div>

                <div style={{ display: 'flex', gap: 8 }}>
                  <Button
                    type="button"
                    variant={provider === 'openrouter' ? 'primary' : 'secondary'}
                    onClick={() => setProvider('openrouter')}
                  >
                    OpenRouter
                  </Button>
                  <Button
                    type="button"
                    variant={provider === 'deepseek' ? 'primary' : 'secondary'}
                    onClick={() => setProvider('deepseek')}
                  >
                    DeepSeek
                  </Button>
                </div>
                <Field
                  label="Ключ провайдера"
                  htmlFor="api-key"
                  error={check && !check.ok ? check.message : undefined}
                >
                  <Input
                    id="api-key"
                    type="password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    mono
                    autoComplete="off"
                  />
                </Field>
                <Button
                  type="button"
                  variant="primary"
                  loading={checking}
                  disabled={apiKey.trim().length < 8}
                  onClick={() => void verify()}
                  block
                >
                  Проверить ключ
                </Button>
                {check?.ok && (
                  <p style={{ margin: 0, color: 'var(--accent-success, #65F5C2)', fontSize: 13 }}>
                    {check.message}
                  </p>
                )}
                <Button
                  type="button"
                  variant="secondary"
                  block
                  onClick={() => {
                    if (session) void completeSetup(baseUrl, session.token);
                    onEnrolled(session!);
                  }}
                >
                  Продолжить в панель
                </Button>
              </div>
            )}
          </PanelBody>
        </Panel>

        <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>
          Мастер первого запуска пока охватывает подключение владельца и проверку ключа.
          Первый режим, загрузка источника и тестовый вопрос ещё не перенесены в мастер.
        </p>
      </div>
    </main>
  );
}

function SetupChecklist({ status, probing }: { status: SetupStatus | null; probing: boolean }) {
  const rows: Array<{ label: string; value: string; tone: 'ok' | 'wait' | 'bad' }> = [];

  if (probing && status === null) {
    rows.push({ label: 'Сервер', value: 'проверяем…', tone: 'wait' });
  } else if (status === null) {
    rows.push({ label: 'Сервер', value: 'не ответил', tone: 'bad' });
  } else {
    rows.push({
      label: 'База данных',
      value: status.database_ok ? 'доступна' : 'недоступна',
      tone: status.database_ok ? 'ok' : 'bad',
    });
    rows.push({
      label: 'Владелец',
      value: status.instance_claimed
        ? `закреплён (${status.admin_devices})`
        : 'ещё не подключён',
      tone: status.instance_claimed ? 'ok' : 'wait',
    });
    rows.push({
      label: 'Модель',
      value:
        status.provider_mode === 'mock'
          ? 'тестовые ответы (моки), ключа нет'
          : status.provider_ready
            ? `ключ настроен: ${status.providers_with_keys.join(', ') || 'неизвестно'}`
            : 'ключ не настроен',
      tone: status.provider_mode === 'live' && status.provider_ready ? 'ok' : 'wait',
    });
    rows.push({
      label: 'Содержимое',
      value: `${status.active_modes} режимов, ${status.knowledge_sources} источников`,
      tone: 'ok',
    });
  }

  const color = (tone: 'ok' | 'wait' | 'bad') =>
    tone === 'ok'
      ? 'var(--accent-success, #65F5C2)'
      : tone === 'bad'
        ? 'var(--accent-danger, #FF6B6B)'
        : 'var(--text-secondary)';

  return (
    <div
      style={{
        display: 'grid',
        gap: 6,
        marginBottom: 20,
        padding: 12,
        border: '1px solid var(--border-subtle, #333)',
        borderRadius: 10,
      }}
    >
      {rows.map((row) => (
        <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{row.label}</span>
          <span style={{ color: color(row.tone), fontSize: 13 }}>{row.value}</span>
        </div>
      ))}
      {status?.first_run_completed && (
        <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
          Первый запуск уже отмечался как завершённый.
        </span>
      )}
    </div>
  );
}
