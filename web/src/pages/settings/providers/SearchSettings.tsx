import { useEffect, useRef, useState } from 'react';
import { Button, Field, Input, Select } from '@/components';
import { providerRequest, type Access } from './providerApi';
import styles from './Providers.module.css';
type Config = {provider:string; has_key:boolean; folder_id:string};
export function SearchSettings({access, disabled, onSaved}: {access:Access; disabled:boolean; onSaved:()=>void}) {
  const [config,setConfig] = useState<Config|null>(null);
  const [provider,setProvider] = useState('searxng');
  const [key,setKey] = useState('');
  const [folder,setFolder] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [saved,setSaved] = useState(false);
  const pending = useRef(false);
  useEffect(() => {
    const controller=new AbortController();
    void providerRequest<Config>(access,'selfhost/search',undefined,'GET',controller.signal).then(result => {setConfig(result);setProvider(result.provider);setFolder(result.folder_id);}).catch(e => {if(!controller.signal.aborted)setError(e.message);});
    return () => controller.abort();
  },[access.baseUrl,access.token]);
  return <div className={styles.form}>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {config && <>
      <Field label="Где выполнять веб-поиск" htmlFor="search-provider"><Select id="search-provider" value={provider} disabled={disabled||busy} onChange={value=>{setProvider(value);setKey('');setSaved(false);}} options={[{value:'searxng',label:'На сервере · SearXNG'},{value:'yandex',label:'Yandex Search API'},{value:'brave',label:'Brave Search API'},{value:'tavily',label:'Tavily API'}]} /></Field>
      <p className={styles.hint}>{provider==='searxng'?'Используется локальный поисковый сервис. Ключ не нужен.':'Поиск выполняет внешний сервис: локальный SearXNG не используется. Запросы передаются провайдеру и могут оплачиваться. Чтение найденных страниц по-прежнему выполняется сервером.'}</p>
      {provider!=='searxng' && <Field label="Ключ поискового API" htmlFor="search-key" hint={config.has_key&&config.provider===provider?'Ключ сохранён. Оставьте пустым, чтобы не менять его.':'Получите ключ в личном кабинете поискового провайдера.'}><Input id="search-key" type="password" autoComplete="off" value={key} maxLength={1000} disabled={disabled||busy} onChange={e=>{setKey(e.target.value);setSaved(false);}} /></Field>}
      {provider==='yandex' && <Field label="ID каталога Yandex Cloud (folder ID)" htmlFor="search-folder"><Input id="search-folder" value={folder} maxLength={50} disabled={disabled||busy} onChange={e=>{setFolder(e.target.value);setSaved(false);}} /></Field>}
      <Button disabled={disabled||busy} loading={busy} onClick={async()=>{
        if(pending.current)return;pending.current=true;setBusy(true);setError('');setSaved(false);
        try {const result=await providerRequest<Config>(access,'selfhost/search',{provider,api_key:key||undefined,folder_id:folder},'PUT');setConfig(result);setKey('');setSaved(true);onSaved();}
        catch(e){setError(e instanceof Error?e.message:'Не удалось сохранить поиск');}
        finally{pending.current=false;setBusy(false);}
      }}>Сохранить способ поиска</Button>
      {saved&&<p role="status" className={styles.hint}>Сохранено. Следующий поиск использует выбранный сервис.</p>}
    </>}
  </div>;
}
