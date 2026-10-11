import { useState } from 'react';
import { Button } from '@/components';
import { Copy, Check } from 'lucide-react';
import styles from './Providers.module.css';
export const localPlans: Record<string, { model: string; url: string; label: string; ram: number }> = {
  embedding: {model:'embeddinggemma',url:'http://ollama:11434/v1',label:'Поиск по смыслу',ram:4},

};
export function LocalModelGuide({role,selfhost,onContinue,onCancel}:{role:string;selfhost:boolean;onContinue:()=>void;onCancel?:()=>void}) {
  const [copied,setCopied] = useState(false);
  const [error,setError] = useState('');
  const plan = localPlans[role];
  const command = `./wristmind local-model --role ${role} --install-dir /opt/wristmind`;
  return <section className={styles.form} aria-label="Установка локальной модели">
    <h3 className={styles.subheading}>На вашем сервере · {plan.label}</h3>
    <p className={styles.hint}>Без платы за API. Вычисления выполняются на сервере WristMind, а не на телефоне. Для установки нужен интернет; модель скачивается один раз и занимает место на диске.</p>
    {selfhost ? <><ol className={styles.guide}><li>Откройте терминал сервера и перейдите в каталог WristMind.</li><li>Выполните команду ниже. Если установили систему в другом каталоге, замените /opt/wristmind на свой путь.</li><li>Дождитесь сообщения «Готово». Скрипт сам проверит модель и подключит её к поиску. Вернитесь в настройки — больше ничего выбирать не нужно.</li></ol>
      <div className={styles.command}><code>{command}</code><Button aria-label="Скопировать команду установки" iconLeft={copied ? <Check /> : <Copy />} onClick={() => {void navigator.clipboard.writeText(command).then(() => {setCopied(true);setError('');}).catch(() => setError('Не удалось скопировать. Выделите команду и скопируйте вручную.'));}}>{copied ? 'Скопировано' : 'Копировать'}</Button></div>
      <p className={styles.hint}>Минимум {plan.ram} ГиБ RAM и 6 ГиБ свободного диска. Скрипт проверит ресурсы и запросит подтверждение. Скорость зависит от CPU и нагрузки; большие документы могут обрабатываться дольше, чем через API.</p></> : <p className={styles.hint}>Установка этой командой доступна в SelfHost-версии. Здесь можно подключить уже запущенный локальный сервер с совместимым API.</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.actions}>{onCancel && <Button onClick={onCancel}>Назад</Button>}<Button variant="primary" onClick={onContinue}>{selfhost ? 'Вернуться в настройки' : 'Подключить локальный сервер'}</Button></div>
    <p className={styles.hint}>Открытие инструкции ничего не устанавливает. В SelfHost всё выполняет команда: загрузку, проверку и назначение модели. Ключ не нужен.</p>
  </section>;
}
