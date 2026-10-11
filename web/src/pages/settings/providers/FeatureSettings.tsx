import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { Button, Field, Select, Switch } from '@/components';
import { providerRequest, type Access, type Registry } from './providerApi';
import { SearchSettings } from './SearchSettings';
import styles from './Providers.module.css';
type Feature = 'web_search' | 'digitization' | 'rag' | 'voice';
type State = { search_provider?: string; features: Record<Feature, { enabled: boolean; available: boolean; reason: string }>; resources: { cpu: number; ram_gib: number; available_gib: number; disk_free_gib: number; tier: 'limited' | 'standard' | 'comfortable'; notice: string; recommendations: Record<Feature, boolean> } };
const labels: Record<Feature, string> = { web_search: 'Веб-поиск', digitization: 'Чтение документов', rag: 'Ответы по вашим документам', voice: 'Голосовой ввод' };
const descriptions: Record<Feature,string> = { web_search:'Ищет актуальную информацию в интернете', digitization:'Читает текст из PDF, фотографий и сканов', rag:'Использует загруженные источники при ответах', voice:'Преобразует вашу речь в текст' };
const roles: Partial<Record<Feature,string>> = { digitization:'vision', rag:'embedding', voice:'speech' };
const modelLabels: Record<string,string> = { vision:'Модель для понимания изображений', embedding:'Модель для улучшения поиска', speech:'Модель распознавания голоса' };
type AssignmentProps = { registry: Registry; disabled: boolean; onAssign: (role: string, identity: string) => void; onAdd: (role: string, local?: boolean) => void };
export function RolePicker({ role, registry, disabled, onAssign, onAdd }: AssignmentProps & {role: string}) {
  const models = registry.models.filter(m => m.enabled && m.roles?.includes(role) && registry.providers.some(p => p.id === m.provider && p.enabled));
  const assigned = registry.model_roles?.[role] ?? '';
  const selected = models.some(m => m.id === assigned) ? assigned : '';
  return <div className={styles.form}>
    {models.length > 0 && <Field label={modelLabels[role]} htmlFor={`assigned-${role}`}><Select id={`assigned-${role}`} className={styles.select} disabled={disabled} value={selected} options={[{value:'',label:role === 'vision' ? 'Без улучшения — обычное чтение текста' : role === 'embedding' ? 'Без улучшения — поиск по словам' : 'Системная диктовка на часах'}, ...models.map(m => ({value:m.id,label:`${m.label} · ${registry.providers.find(p => p.id === m.provider)?.label}`}))]} onChange={identity => onAssign(role,identity)} /></Field>}
    <div className={styles.actions}><Button disabled={disabled} onClick={() => onAdd(role)}>Подключить API</Button>{role === 'embedding' && <Button disabled={disabled} onClick={() => onAdd(role, true)}>{registry.selfhost ? 'Установить на сервере' : 'Подключить локально'}</Button>}</div>
  </div>;
}
export function FeatureSettings({ access, registry, disabled, onAssign, onAdd }: AssignmentProps & {access: Access}) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const load = () => { setError(''); void providerRequest<State>(access, 'selfhost/features').then(setState).catch(e => setError(e.message)); };
  useEffect(() => { const controller = new AbortController(); void providerRequest<State>(access, 'selfhost/features', undefined, 'GET', controller.signal).then(result => { if (!controller.signal.aborted) setState(result); }).catch(e => { if (!controller.signal.aborted) setError(e.message); }); return () => controller.abort(); }, [access.baseUrl, access.token, registry]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async (values: Record<Feature, boolean>) => {
    if (pending.current) return; pending.current = true;
    setBusy(true); setError('');
    try { setState(await providerRequest<State>(access, 'selfhost/features', values, 'PUT')); }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить настройки'); }
    finally { pending.current = false; setBusy(false); }
  };
  return <section className={styles.form} aria-label="Функции сервера">
    <p className={styles.hint}>Включайте только то, что нужно. Настройки сохраняются автоматически.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {!state ? error ? <Button onClick={load}>Повторить загрузку</Button> : <p role="status" className={styles.hint}>Загружаем функции сервера…</p> : <>

      {Object.entries(labels).map(([key,label]) => {
        const feature = key as Feature; const row = state.features[feature]; const role = roles[feature];
        const enhanced = role && registry.models.some(m => m.id === registry.model_roles?.[role] && m.enabled && m.roles?.includes(role) && registry.providers.some(p => p.id === m.provider && p.enabled));
        const basic = feature === 'digitization' || feature === 'rag';
        const explanation = basic && row.available ? enhanced ? feature === 'rag' ? 'Поиск по смыслу включён.' : 'Дополнительная модель помогает читать сложные документы.' : feature === 'rag' ? 'Поиск выполняется на сервере без дополнительной модели.' : 'Текст извлекается на сервере без дополнительной модели.' : feature === 'web_search' && !row.available ? 'Веб-поиск ещё не настроен. Ниже есть команда автоматической настройки.' : row.reason;
        return <div key={feature} className={styles.featureGroup}>
          <Switch label={label} checked={row.enabled} disabled={busy || disabled} description={descriptions[feature]} onChange={checked => { const values = Object.fromEntries(Object.entries(state.features).map(([k,v]) => [k,v.enabled])) as Record<Feature,boolean>; values[feature] = checked; void save(values); }} />
          <p className={styles.hint}><strong>{!row.enabled ? 'Выключено' : row.available ? 'Работает' : 'Нужна настройка'}</strong>{row.enabled && <> · {explanation}</>}</p>
          {feature === 'web_search' && <SearchSettings access={access} disabled={busy || disabled} onSaved={load} />}
          {feature === 'web_search' && row.enabled && !row.available && <details className={styles.improvement}><summary><ChevronDown size={16} /><span>Настроить веб-поиск</span></summary><div className={styles.form}><p className={styles.hint}>В новых установках веб-поиск настраивается автоматически. Для уже установленной системы откройте меню командой ниже и выберите пункт 8 «Настроить веб-поиск».</p><div className={styles.command}><code>{'bash <(curl -fsSL https://raw.githubusercontent.com/IvanSemenkin/wristmind-selfhost/main/install.sh)'}</code></div><p className={styles.hint}>При запуске меню укажите каталог существующей установки. После сообщения «Готово» обновите панель. Ключ и адрес сервиса вводить не нужно.</p></div></details>}
          {role && (row.enabled || role === 'vision') && (basic ? <details className={styles.improvement}>
            <summary><ChevronDown size={16} /><span>{feature === 'rag' ? 'Улучшить поиск по смыслу' : 'Улучшить чтение сложных документов'}<small className={styles.disclosureNote}>Необязательно</small></span></summary>
            <div className={styles.form}><p className={styles.hint}>{feature === 'rag' ? 'Обычный поиск находит совпадающие слова. Поиск по смыслу может найти «затраты» по запросу «расходы». Для этого нужна отдельная модель: локальная или подключённая через API. Она не устанавливается автоматически.' : 'Обычное чтение текста выполняется локально. Vision можно подключить независимо от переключателя чтения документов. Для понимания изображений, схем и сложных формул подключите Vision-модель внешнего провайдера; локально она не устанавливается.'}</p>
            <p className={styles.hint}>{feature === 'rag' ? 'При выборе внешнего сервиса ему передаются тексты фрагментов и поисковых запросов. После смены модели повторно обработайте документы.' : 'При выборе внешнего сервиса ему передаются изображения страниц.'} Запросы могут оплачиваться по тарифу провайдера.</p>
            <RolePicker role={role} registry={registry} disabled={busy || disabled} onAssign={onAssign} onAdd={onAdd} /></div>
          </details> : <RolePicker role={role} registry={registry} disabled={busy || disabled} onAssign={onAssign} onAdd={onAdd} />)}
        </div>;
      })}
      <details className={styles.resourceSummary}><summary><ChevronDown size={16} /><span>Мощность сервера: {{ limited:'ограниченная', standard:'базовая', comfortable:'с запасом' }[state.resources.tier]} · {state.resources.cpu} CPU · {state.resources.ram_gib} ГиБ RAM</span></summary><div className={styles.form}><p className={styles.hint}>Свободная RAM: {state.resources.available_gib} ГиБ. Свободный диск: {state.resources.disk_free_gib} ГиБ.</p><p className={styles.hint}>{state.resources.notice}</p><Button disabled={busy || disabled} onClick={() => void save({ ...state.resources.recommendations, voice:state.features.voice.enabled, web_search:state.search_provider && state.search_provider !== 'searxng' ? state.features.web_search.enabled : state.resources.recommendations.web_search })}>Применить рекомендации для локальных функций</Button></div></details>
      <p className={styles.hint}>Отключение функций сохраняет ваши чаты и документы.</p>
    </>}
  </section>;
}
