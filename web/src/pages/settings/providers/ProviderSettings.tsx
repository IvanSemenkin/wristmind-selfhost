import { useEffect, useRef, useState } from 'react';
import { Check, Plus, KeyRound, ChevronRight, ChevronDown, Server } from 'lucide-react';
import { Button, Field, Input, Select, Switch, Panel, PanelHeader, PanelBody, SegmentedControl, useConfirm } from '@/components';
import { useSession } from '@/session';
import { useActions } from '@/services';
import { useModels, useSettings } from '@/store';
import { providerRequest, supportsRole, type Access, type Registry, type Provider, type InstalledModel } from './providerApi';
import styles from './Providers.module.css';
import { LocalModelGuide, localPlans } from './LocalModelGuide';
import { FeatureSettings, RolePicker } from './FeatureSettings';
const roleLabels: Record<string, string> = { text: 'Ответы в чатах', vision: 'Понимание изображений', speech: 'Распознавание голоса', embedding: 'Поиск по смыслу' };

const message = (cause: unknown) => cause instanceof Error ? cause.message : 'Не удалось выполнить действие.';

export function ProviderForm({ access, registry, onSaved, onCancel, textOnly = false, localUrl = '', role = 'text' }: { access: Access; registry: Registry; onSaved: (p: Provider) => void; onCancel?: () => void; textOnly?: boolean; localUrl?: string; role?: string }) {
  const [kind, setKind] = useState(localUrl ? 'compatible' : 'openai');
  const [key, setKey] = useState('');
  const [url, setUrl] = useState(localUrl);
  const [label, setLabel] = useState('');
  const [local, setLocal] = useState(Boolean(localUrl));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  return <form className={styles.form} onSubmit={e => { e.preventDefault(); if (pending.current) return; pending.current = true; setBusy(true); setError('');
    void providerRequest<{ provider: Provider }>(access, 'providers', { kind, api_key: key, base_url: url.trim(), label: label.trim(), allow_local: kind === 'compatible' && local })
      .then(result => { setKey(''); onSaved(result.provider); }).catch(cause => setError(message(cause))).finally(() => { pending.current = false; setBusy(false); });
  }}>
    {!localUrl && <Field label="Провайдер" htmlFor="provider-kind"><Select className={styles.select} id="provider-kind" value={kind} onChange={value => { setKind(value); setKey(''); setUrl(''); setLocal(false); setError(''); }} options={registry.presets.filter(p => supportsRole(p.id,role) && (!textOnly || p.id !== 'yandex')).map(p => ({ value: p.id, label: p.label }))} disabled={busy} /></Field>}
    {localUrl && <p className={styles.hint}>Локальный сервер · адрес виден серверу WristMind. Ключ не нужен для сервисов, установленных нашим скриптом.</p>}
    {kind === 'compatible' && <><Field label={localUrl ? "Адрес локального сервиса" : "URL API"} htmlFor="provider-url" hint={localUrl ? "Адрес уже заполнен для установки нашим скриптом. Его использует сервер WristMind." : "Адрес совместимого API, например https://example.com/v1"}><Input className={styles.control} id="provider-url" type="url" value={url} onChange={e => setUrl(e.target.value)} required disabled={busy} maxLength={300} /></Field>{!localUrl && <Switch checked={local} onChange={setLocal} label="Локальный сервер без HTTPS" description="Разрешает HTTP и подключение без ключа. Используйте только в доверенной сети." />}</>}
    {!localUrl && <Field label="Ключ API" htmlFor="provider-key" hint={kind === 'compatible' && local ? 'Необязательно: заполните только если ваш локальный сервер требует авторизацию.' : registry.demo ? 'Демо-режим: ключ не нужен. В рабочей установке здесь вводится ключ из личного кабинета провайдера.' : 'Хранится зашифрованным на сервере. Не возвращается в браузер.'}><Input className={styles.control} id="provider-key" type="password" value={key} onChange={e => setKey(e.target.value)} autoComplete="off" required={!registry.demo && !(kind === 'compatible' && local)} disabled={busy || registry.demo} maxLength={1000} placeholder={registry.demo ? 'Не требуется в демо-режиме' : 'Ключ провайдера'} /></Field>}
    <details className={styles.optional}><summary><ChevronDown size={16} />Название подключения</summary><Field label="Название" htmlFor="provider-label"><Input className={styles.control} id="provider-label" value={label} onChange={e => setLabel(e.target.value)} placeholder="Необязательно" maxLength={80} disabled={busy} /></Field></details>
    {registry.demo && <p className={styles.hint}>Режим просмотра: ключ не нужен, платные запросы не выполняются.</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.actions}>{onCancel && <Button disabled={busy} onClick={onCancel}>Отмена</Button>}<Button type="submit" variant="primary" loading={busy} iconRight={<ChevronRight />}>{busy ? 'Проверяем подключение…' : localUrl ? 'Подключить локальный сервис' : 'Продолжить'}</Button></div>
  </form>;
}

export function ModelForm({ access, provider, demo, useDefault = false, initialRole = 'text', initialModel = '', onSaved, onCancel }: { access: Access; provider: Provider; demo: boolean; useDefault?: boolean; initialRole?: string; initialModel?: string; onSaved: (model: InstalledModel) => void; onCancel?: () => void }) {
  const [query, setQuery] = useState('');
  const [remote, setRemote] = useState(initialModel);
  const [role, setRole] = useState(provider.kind === 'yandex' ? 'speech' : initialRole);
  const [label, setLabel] = useState('');
  const [rows, setRows] = useState<{ id: string; label: string }[]>([]);
  const [warning, setWarning] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setWarning('');
      void providerRequest<{ models: typeof rows; total: number; warning: string }>(access, `providers/${provider.id}/catalog?query=${encodeURIComponent(query)}`, undefined, 'GET', controller.signal)
        .then(result => { if (!controller.signal.aborted) { setRows(result.models); setWarning(result.warning); } })
        .catch(cause => { if (!controller.signal.aborted) { setRows([]); setWarning(message(cause)); } })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  // Access values, not the temporary object, define this request boundary.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id, query, access.baseUrl, access.token]);
  return <form className={styles.form} onSubmit={e => { e.preventDefault(); if (pending.current) return; pending.current = true; setBusy(true); setError('');
    void providerRequest<InstalledModel>(access, 'models/installed', { provider_id: provider.id, model_id: remote.trim(), label: label.trim(), use_default: useDefault, roles: [role] })
      .then(onSaved).catch(cause => setError(message(cause))).finally(() => { pending.current = false; setBusy(false); });
  }}>
    <p className={styles.providerName}>{provider.allow_local ? <Server size={16} /> : <KeyRound size={16} />}{provider.label}</p>
    {!useDefault && initialRole === 'text' && <Field label="Для чего нужна модель" htmlFor="model-role" hint="Проверяем именно эту функцию. Для нескольких назначений добавьте модель повторно с другой ролью."><Select className={styles.select} id="model-role" value={role} disabled={busy} onChange={setRole} options={Object.entries(roleLabels).filter(([key]) => supportsRole(provider.kind,key)).map(([value,label]) => ({value,label}))} /></Field>}
    <Field label="Найти модель" htmlFor="model-search"><Input className={styles.control} id="model-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Название или ID модели" type="search" disabled={busy} maxLength={120} /></Field>
    <div className={styles.catalog} aria-label="Модели провайдера" aria-busy={loading}>
      {rows.slice(0, 12).map(row => <button key={row.id} type="button" className={styles.result} data-selected={remote === row.id || undefined} disabled={busy} onClick={() => { setRemote(row.id); setLabel(row.label.slice(0, 80)); }}><span><strong>{row.label}</strong><small>{row.id}</small></span>{remote === row.id && <Check size={16} />}</button>)}
      {loading && <p role="status" className={styles.hint}>Загружаем список…</p>}
      {!loading && !rows.length && !warning && <p className={styles.hint}>Не нашли модель? Введите её ID ниже.</p>}
      {!loading && rows.length > 12 && <p className={styles.hint}>Уточните поиск, чтобы увидеть другие модели.</p>}
    </div>
    {warning && <p className={styles.hint} role="status">{warning} Можно ввести ID ниже.</p>}
    <Field label="ID модели" htmlFor="model-id" hint="Выберите из списка или впишите ID самостоятельно."><Input className={styles.control} id="model-id" value={remote} onChange={e => { setRemote(e.target.value); setLabel(''); }} required disabled={busy} maxLength={120} /></Field>
    {!demo && <p className={styles.hint}>{provider.allow_local ? 'Проверим модель на вашем сервере. Ключ и плата за внешний API не нужны.' : 'Перед добавлением проверим выбранную функцию: текст, небольшое изображение, тестовое аудио или embeddings. Это платный API-запрос; стоимость зависит от провайдера.'}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.actions}>{onCancel && <Button disabled={busy} onClick={onCancel}>Назад</Button>}<Button type="submit" variant="primary" loading={busy} disabled={!remote.trim()}>{busy ? 'Проверяем модель…' : 'Проверить и добавить'}</Button></div>
  </form>;
}

/** The same provider-first flow is reused by the setup wizard and settings. */
export function AddModelFlow({ access, useDefault = false, initialRole = 'text', initialLocal = false, onSaved, onCancel }: { access: Access; useDefault?: boolean; initialRole?: string; initialLocal?: boolean; onSaved: (model: InstalledModel) => void; onCancel?: () => void }) {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [adding, setAdding] = useState(false);
  const [localMode, setLocalMode] = useState(initialLocal && initialRole === 'embedding');
  const [localReady, setLocalReady] = useState(false);
  const [error, setError] = useState('');
  const load = () => { setError(''); void providerRequest<Registry>(access, 'provider-settings').then(setRegistry).catch(cause => setError(message(cause))); };
  useEffect(load, [access.baseUrl, access.token]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className={styles.form}><p role="alert" className={styles.error}>{error}</p><Button onClick={load}>Повторить</Button></div>;
  if (!registry) return <p role="status" className={styles.hint}>Загружаем подключения…</p>;
  if (localMode && registry.selfhost) return <LocalModelGuide role="embedding" selfhost onContinue={() => onCancel?.()} onCancel={() => {setLocalMode(false); onCancel?.();}} />;
  if (localMode && !localReady) return <LocalModelGuide role={initialRole} selfhost={Boolean(registry.selfhost)} onContinue={() => {setLocalReady(true); const existing = registry.providers.find(p => p.enabled && p.allow_local && p.base_url.replace(/\/$/, '') === localPlans[initialRole].url); if(existing) setProvider(existing);}} onCancel={() => {setLocalMode(false); onCancel?.();}} />;
  if (localMode && !provider) return <ProviderForm access={access} registry={registry} textOnly localUrl={localPlans[initialRole].url} onSaved={setProvider} onCancel={() => setLocalReady(false)} />;
  if (provider) return <div className={styles.form}><p className={styles.hint}>Шаг 2 из 2 · Выберите модель для: {roleLabels[initialRole].toLowerCase()}</p><ModelForm key={provider.id} access={access} provider={provider} demo={registry.demo} useDefault={useDefault} initialRole={initialRole} initialModel={localMode ? localPlans[initialRole].model : ''} onSaved={onSaved} onCancel={() => { setProvider(null); setAdding(false); }} /></div>;
  const enabled = registry.providers.filter(p => p.enabled && supportsRole(p.kind,initialRole) && p.kind !== 'gigachat' && (!(useDefault || initialRole !== 'speech') || p.kind !== 'yandex'));
  if (adding) return <ProviderForm access={access} registry={registry} role={initialRole} textOnly={useDefault || initialRole !== 'speech'} onSaved={setProvider} onCancel={enabled.length ? () => setAdding(false) : onCancel} />;
  return <div className={styles.form}><p className={styles.hint}>Шаг 1 из 2 · Выберите сервис ИИ</p><p className={styles.hint}>Выберите подключение или добавьте нового провайдера.</p>{enabled.map(p => <Button key={p.id} iconLeft={<KeyRound />} iconRight={<ChevronRight />} onClick={() => setProvider(p)}>{p.label}</Button>)}<Button iconLeft={<Plus />} onClick={() => setAdding(true)}>Добавить провайдера</Button>{initialRole === 'embedding' && <Button onClick={() => setLocalMode(true)}>Установить поиск на сервере</Button>}{onCancel && <Button onClick={onCancel}>Отмена</Button>}</div>;
}

export function ProviderSettings() {
  const access = useSession();
  const actions = useActions();
  const models = useModels();
  const globalSettings = useSettings();
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [section, setSection] = useState<'connections' | 'models' | 'functions'>('functions');
  const confirm = useConfirm();
  const [newRole, setNewRole] = useState('text');
  const [localModel, setLocalModel] = useState(false);
  const [flow, setFlow] = useState<'provider' | 'model' | null>(null);
  const [editing, setEditing] = useState<Provider | null>(null);
  const flowHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (section === 'functions' && flow === 'model') flowHeading.current?.focus(); }, [section, flow]);
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const load = async () => { setRegistry(await providerRequest<Registry>(access, 'provider-settings')); };
  useEffect(() => { void load().catch(cause => setError(message(cause))); }, [access.baseUrl, access.token, models, globalSettings]); // eslint-disable-line react-hooks/exhaustive-deps
  const mutate = async (path: string, body: unknown, method = 'PATCH') => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try { await providerRequest(access, path, body, method); await load(); await actions.bootstrap(true); setEditing(null); setKey(''); }
    catch (cause) { setError(message(cause)); }
    finally { pending.current = false; setBusy(false); }
  };
  const saved = () => { setFlow(null); if (newRole !== 'text') setSection('functions'); void load().then(() => actions.bootstrap(true)).catch(cause => setError(message(cause))); };
  const addRole = (role: string, local = false) => { setLocalModel(local); setNewRole(role); setSection(role === 'text' ? 'models' : 'functions'); setFlow('model'); setEditing(null); };
  const assign = (role: string, identity: string) => { void mutate(`model-roles/${role}`, { identity }, 'PUT'); };
  return <Panel><PanelHeader title="Настройка ИИ" /><PanelBody><div className={styles.form}>
    <SegmentedControl className={styles.sections} aria-label="Раздел настроек ИИ" value={section} onChange={value => { setSection(value); setFlow(null); setEditing(null); setError(''); }} options={[{value:'functions',label:'Возможности'},{value:'connections',label:'Провайдеры'},{value:'models',label:'Модели'}]} />
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!registry ? <Button onClick={() => void load().catch(cause => setError(message(cause)))}>Загрузить настройки</Button> : <>
      {registry.demo && <p className={styles.demoNotice} role="status">Демо-режим: ответы и проверки моделей имитируются. Ключи не нужны, реальные API-запросы не выполняются.</p>}
      {section === 'connections' && <>
        <p className={styles.hint}>Провайдер — сервис, которому вы отправляете запросы: например, OpenAI или DeepSeek. Один ключ даёт доступ к нескольким его моделям.</p>
        {!registry.providers.length && <p className={styles.hint}>Провайдеров пока нет. Начните с подключения.</p>}
        {registry.providers.map(p => <div key={p.id} className={styles.row}><span className={styles.rowText}><strong>{p.label}</strong><small>{p.enabled ? p.has_key ? 'Подключён · ключ сохранён' : 'Подключён · без ключа' : 'Выключен'}</small></span><Button size="sm" disabled={busy} onClick={() => { setEditing(p); setKey(''); setFlow(null); }}>Настроить</Button></div>)}
        {editing && <form className={styles.edit} onSubmit={e => { e.preventDefault(); void mutate(`providers/${editing.id}`, { ...(key ? { api_key: key } : {}) }); }}><strong>{editing.label}</strong><p className={styles.hint}>Измените ключ или отключите подключение. Удаление уберёт и его модели; чаты и источники сохранятся.</p>{editing.kind !== 'gigachat' && <Field label="Новый ключ" htmlFor="provider-new-key" hint="Оставьте пустым, чтобы сохранить текущий."><Input className={styles.control} id="provider-new-key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} maxLength={1000} disabled={busy} /></Field>}<div className={styles.actions}><Button disabled={busy} onClick={() => void mutate(`providers/${editing.id}`, { enabled: !editing.enabled })}>{editing.enabled ? 'Выключить' : 'Включить'}</Button><Button disabled={busy} onClick={() => { setEditing(null); setKey(''); }}>Отмена</Button>{editing.kind !== 'gigachat' && <Button type="submit" variant="primary" disabled={busy || !key} loading={busy}>Сохранить ключ</Button>}</div><Button disabled={busy} onClick={async () => { const ok = await confirm({ title: `Удалить ${editing.label}?`, description: 'Подключение и его модели исчезнут из настроек. Чаты и источники сохранятся. Для моделей, используемых по умолчанию или в режимах, сначала потребуется выбрать замену.', confirmLabel: 'Удалить провайдера' }); if (ok) void mutate(`providers/${editing.id}`, {}, 'DELETE'); }}>Удалить провайдера</Button></form>}
        {!flow && !editing && <Button iconLeft={<Plus />} onClick={() => setFlow('provider')}>Добавить провайдера</Button>}
        {flow === 'provider' && <div className={styles.edit}><ProviderForm access={access} registry={registry} onSaved={() => { saved(); addRole('text'); }} onCancel={() => {setFlow(null); void load().then(() => actions.bootstrap(true)).catch(cause => setError(message(cause)));}} /></div>}
      </>}
      {section === 'models' && <>
        <p className={styles.hint}>Добавляйте только нужные модели и указывайте их назначение. Модель для ответов используется в чате; Изображения, голос и поиск настраиваются в «Возможностях».</p>
        {!registry.models.length && <p className={styles.hint}>Моделей пока нет. Добавьте модель для ответов.</p>}
        {!flow && <Button iconLeft={<Plus />} onClick={() => { setNewRole('text'); setFlow('model'); }}>Добавить модель</Button>}
        {flow === 'model' && <div className={styles.edit}><AddModelFlow access={access} initialRole={newRole} initialLocal={localModel} onSaved={saved} onCancel={() => {setFlow(null); void load().then(() => actions.bootstrap(true)).catch(cause => setError(message(cause)));}} /></div>}
        {registry.models.map(m => <div key={m.id} className={styles.row}><span className={styles.rowText}><strong>{m.label}</strong><small>{(m.roles ?? ['text']).map(r => roleLabels[r]).join(', ')} · {registry.providers.find(p => p.id === m.provider)?.label}{m.id === registry.default_model_id ? ' · Для ответов по умолчанию' : !m.enabled ? ' · Выключена' : ''}</small></span><div className={styles.actions}>{m.enabled && (m.roles ?? ['text']).includes('text') && m.id !== registry.default_model_id && <Button size="sm" disabled={busy} onClick={() => void mutate(`models/installed/${encodeURIComponent(m.id)}`, { use_default:true })}>Для ответов</Button>}{m.id !== registry.default_model_id && <Button size="sm" disabled={busy} onClick={() => void mutate(`models/installed/${encodeURIComponent(m.id)}`, { enabled:!m.enabled })}>{m.enabled ? 'Выключить' : 'Включить'}</Button>}</div></div>)}
      </>}
      {section === 'functions' && !flow && <section className={styles.form} aria-label="Основная настройка">
        <p className={styles.hint}>Чтобы начать общаться, достаточно подключить один сервис ИИ и выбрать модель для ответов.</p>
        <details className={styles.optional}><summary><ChevronDown size={16} />Как настроить и начать пользоваться</summary><ol className={styles.guide}><li><strong>Подключите помощника</strong><span>Выберите провайдера и введите его ключ. Если используете локальную модель, ключ не нужен.</span></li><li><strong>Выберите модель для ответов</strong><span>Проверьте модель, затем откройте чаты — уже можно общаться.</span></li><li><strong>Добавьте свои документы</strong><span>Загрузите файлы в «Базу знаний». Чтение текста и поиск по словам уже работают на сервере.</span></li><li><strong>Улучшите возможности, если нужно</strong><span>Поиск по смыслу и чтение сложных документов необязательны. Выберите API или установку модели на сервере.</span></li></ol></details>
        <div className={styles.row}><span className={styles.rowText}><strong>1. Подключите сервис ИИ</strong><small>{registry.providers.some(p => p.enabled) ? registry.providers.filter(p => p.enabled).map(p => p.label).join(', ') : 'Выберите провайдера и введите его ключ API'}</small></span><Button disabled={busy} onClick={() => {setSection('connections'); if (!registry.providers.length) setFlow('provider');}}>{registry.providers.some(p => p.enabled) ? 'Изменить' : 'Подключить'}</Button></div>
        <div className={styles.form}><strong className={styles.subheading}>2. Выберите модель для ответов</strong>
        {registry.models.some(m => m.enabled && (m.roles ?? ['text']).includes('text') && registry.providers.some(p => p.id === m.provider && p.enabled)) ? <Field label="Отвечает в новых чатах" htmlFor="chat-default"><Select className={styles.select} id="chat-default" value={registry.default_model_id} disabled={busy} options={registry.models.filter(m => m.enabled && (m.roles ?? ['text']).includes('text') && registry.providers.some(p => p.id === m.provider && p.enabled)).map(m => ({value:m.id,label:m.label}))} onChange={id => void mutate(`models/installed/${encodeURIComponent(id)}`, {use_default:true})} /></Field> : <Button disabled={busy} onClick={() => addRole('text')}>Добавить модель для ответов</Button>}
        </div><strong className={styles.subheading}>3. Дополнительные возможности</strong>
      </section>}
      {section === 'functions' && flow === 'model' && <div className={styles.edit}><h3 ref={flowHeading} tabIndex={-1} className={styles.subheading}>{roleLabels[newRole]}</h3><p className={styles.hint}>{localModel ? 'Команда установит и назначит локальный поиск автоматически. Выбирать провайдера и модель не нужно.' : 'Это дополнительная возможность. Сначала выберите сервис, затем модель. После проверки вернёмся к возможностям.'}</p><AddModelFlow access={access} initialRole={newRole} initialLocal={localModel} onSaved={model => {setFlow(null); void mutate(`model-roles/${newRole}`, {identity:model.id}, 'PUT');}} onCancel={() => {setFlow(null); void load().then(() => actions.bootstrap(true)).catch(cause => setError(message(cause)));}} /></div>}
      {section === 'functions' && !flow && (registry.selfhost ? <FeatureSettings access={access} registry={registry} disabled={busy} onAssign={assign} onAdd={addRole} /> : <><p className={styles.hint}>Выберите проверенные модели для дополнительных возможностей.</p>{['vision','speech','embedding'].map(role => <RolePicker key={role} role={role} registry={registry} disabled={busy} onAssign={assign} onAdd={addRole} />)}</>)}
    </>}
  </div></PanelBody></Panel>;
}
