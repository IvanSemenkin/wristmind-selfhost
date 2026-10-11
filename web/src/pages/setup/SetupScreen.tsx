import { useEffect, useRef, useState } from 'react';
import { Button, Field, Input, Textarea } from '@/components';
import type { Session } from '@/session';
import { setupRequest, type SetupStatus, type WizardState } from './setupApi';
import styles from './Setup.module.css';
import { AddModelFlow } from '../settings/providers/ProviderSettings';

function Frame({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <main className={styles.page}><div className={styles.flow}>
    <div className={styles.brand}><img src="/wristmind-mark.svg" width="32" height="32" alt="" />WristMind</div>
    <header className={styles.heading}><h1 tabIndex={-1}>{title}</h1><p className={styles.muted}>{description}</p></header>
    {children}
  </div></main>;
}

export function SelfHostAccess({ status, onSession }: { status: SetupStatus; onSession: (session: Session) => void }) {
  const creating = !status.admin_created;
  const [activation] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('activate') ?? '');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  useEffect(() => {
    if (creating) window.history.replaceState(null, '', '/setup');
    else if (window.location.hash.startsWith('#activate=')) window.history.replaceState(null, '', window.location.pathname);
  }, [creating]);
  const submit = async () => {
    if (pending.current) return;
    if (creating && password !== repeat) { setError('Пароли не совпадают.'); return; }
    pending.current = true; setBusy(true); setError(null);
    try {
      const session = await setupRequest<Session>(creating ? 'admin' : 'login', { login: login.trim(), password }, creating ? activation : undefined);
      setPassword(''); setRepeat(''); onSession(session);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось войти.'); }
    finally { pending.current = false; setBusy(false); }
  };
  return <Frame title={creating ? 'Ваш WristMind' : 'Войти в WristMind'} description={creating ? 'Создайте учётную запись владельца. Чаты и материалы будут храниться на вашем сервере.' : 'Введите имя и пароль владельца сервера.'}>
    {creating && !activation ? <div className={styles.note}>Для безопасного первого входа откройте ссылку из команды <code>./wristmind setup-link</code> с каталогом вашей установки. Это защищает сервер от создания чужого администратора.</div> : null}
    <form className={styles.form} onSubmit={e => { e.preventDefault(); void submit(); }}>
      <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0, display: 'contents' }}>
        <Field label="Имя" htmlFor="owner-login"><Input className={styles.control} id="owner-login" value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" required maxLength={80} /></Field>
        <Field label="Пароль" htmlFor="owner-password" hint={creating ? 'Не менее 12 символов.' : undefined}><Input className={styles.control} id="owner-password" value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete={creating ? 'new-password' : 'current-password'} required minLength={creating ? 12 : 1} maxLength={256} /></Field>
        {creating && <Field label="Повторите пароль" htmlFor="owner-repeat"><Input className={styles.control} id="owner-repeat" value={repeat} onChange={e => setRepeat(e.target.value)} type="password" autoComplete="new-password" required minLength={12} /></Field>}
      </fieldset>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!login.trim() || !password || (creating && (!activation || !repeat))}>{busy ? 'Подключаемся…' : creating ? 'Создать аккаунт' : 'Войти'}</Button>
    </form>
    {!status.https && <p className={styles.muted}>Сейчас соединение локальное. Доступ через интернет и подключение часов потребуют HTTPS.</p>}
  </Frame>;
}

export function SetupWizard({ onComplete }: { onComplete: () => void }) {
  const [state, setState] = useState<WizardState | null>(null);
  const [step, setStep] = useState(0);
  const [modeName, setModeName] = useState('Помощник');
  const [prompt, setPrompt] = useState('Помогай понятно и по делу. Объясняй решение, когда это полезно.');
  const [text, setText] = useState('Сколько будет 2 + 2?');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const load = async () => {
    setError(null);
    try {
      const next = await setupRequest<WizardState>('wizard'); setState(next);
      if (next.mode_name) { setModeName(next.mode_name); setPrompt(next.mode_prompt); }
      setStep(next.completed ? 3 : !next.model_configured ? 0 : !next.mode_created ? 1 : 2);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось загрузить настройку.'); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => { document.querySelector<HTMLElement>('h1')?.focus(); }, [step]);
  const act = async (action: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось выполнить действие.'); }
    finally { pending.current = false; setBusy(false); }
  };
  const titles = ['Подключите ИИ', 'Ваш помощник', 'Проверьте ответ', 'Всё готово'];
  const descriptions = ['Выберите сервис ИИ, введите его ключ и выберите модель для ответов. Дополнительные модели для документов пока не нужны.', 'Задайте имя помощника и расскажите, как ему отвечать. Готовую инструкцию можно оставить.', 'Задайте вопрос до подключения часов.', 'Можно начать разговор или открыть панель управления.'];
  return <Frame title={titles[step]} description={descriptions[step]}>
    <ol className={styles.steps} aria-label="Этапы настройки">{['ИИ', 'Помощник', 'Проверка'].map((label, i) => <li key={label} className={styles.step} aria-current={step === i ? 'step' : undefined}>{i + 1}. {label}</li>)}</ol>
    {!state && !error && <p role="status" className={styles.muted}>Загружаем настройки…</p>}
    {!state && error && <Button onClick={() => void load()}>Повторить</Button>}
    {state && step === 0 && <div className={styles.modelFlow}><AddModelFlow access={{ baseUrl: '', token: '' }} useDefault onSaved={model => { setState({ ...state, model_configured: true, model_id: model.id, probe_passed: false }); setStep(1); }} /></div>}
    {state && step === 1 && <form className={styles.form} onSubmit={e => { e.preventDefault(); void act(async () => {
      await setupRequest('mode', { name: modeName.trim(), prompt }); setState({ ...state, mode_created: true }); setStep(2);
    }); }}>
      <Field label="Название" htmlFor="setup-mode"><Input className={styles.control} id="setup-mode" value={modeName} onChange={e => setModeName(e.target.value)} required maxLength={80} disabled={busy} /></Field>
      <Field label="Инструкция помощнику" htmlFor="setup-prompt"><Textarea id="setup-prompt" value={prompt} onChange={e => setPrompt(e.target.value)} rows={4} maxLength={8000} disabled={busy} /></Field>
      <div className={styles.actions}><Button disabled={busy} onClick={() => setStep(0)}>Назад</Button><Button type="submit" variant="primary" loading={busy} disabled={!modeName.trim()}>{busy ? 'Сохраняем…' : state.mode_created ? 'Сохранить режим' : 'Создать режим'}</Button></div>
    </form>}
    {state && step === 2 && <form className={styles.form} onSubmit={e => { e.preventDefault(); void act(async () => {
      const result = await setupRequest<{ answer: string }>('question', { text }); setAnswer(result.answer); setState({ ...state, probe_passed: true });
    }); }}>
      <Field label="Ваш вопрос" htmlFor="setup-question"><Input className={styles.control} id="setup-question" value={text} onChange={e => { setText(e.target.value); }} required maxLength={500} disabled={busy} /></Field>
      <div className={styles.actions}><Button disabled={busy} onClick={() => setStep(1)}>Назад</Button><Button type="submit" loading={busy} disabled={!text.trim()}>{busy ? 'Модель отвечает…' : 'Задать вопрос'}</Button></div>
      {answer && <div className={`${styles.note} ${styles.answer}`} role="status">{state.demo && <strong>Тестовый режим<br /></strong>}{answer}</div>}
      {state.probe_passed && <Button variant="primary" loading={busy} onClick={() => void act(async () => { await setupRequest('complete', {}); setStep(3); })}>Завершить настройку</Button>}
    </form>}
    {state && step === 3 && <div className={styles.form}>
      <p className={styles.muted}>Панель<span className={styles.address}>{window.location.origin}/talk</span></p><details><summary>Адрес API для интеграций</summary><p className={styles.muted}><span className={styles.address}>{window.location.origin}/v1</span></p></details>
      <Button variant="primary" size="lg" onClick={onComplete}>Открыть чаты</Button>
      <Button onClick={() => setStep(0)}>Изменить модель для ответов</Button>
      <p className={styles.muted}>Чтение документов и поиск по словам работают на вашем сервере без дополнительных моделей. Загрузить файлы можно в «Базу знаний». Настройки и ключ сервиса можно менять в панели. Домен и HTTPS настраиваются через меню на сервере или команду wristmind access. Мастер подключения часов появится позже.</p>
    </div>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </Frame>;
}
