import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import styles from './Talk.module.css';
interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}
export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(() => matchMedia('(display-mode: standalone)').matches);
  useEffect(() => {
    const offer = (event: Event) => { event.preventDefault(); setPrompt(event as InstallPrompt); };
    const done = () => { setInstalled(true); setPrompt(null); };
    window.addEventListener('beforeinstallprompt', offer); window.addEventListener('appinstalled', done);
    return () => { window.removeEventListener('beforeinstallprompt', offer); window.removeEventListener('appinstalled', done); };
  }, []);
  if (installed) return null;
  return prompt ? <button className={styles.panelLink} type="button" onClick={() => { void prompt.prompt().then(() => prompt.userChoice).catch(() => undefined).finally(() => setPrompt(null)); }}><Download size={16} />Установить приложение</button>
    : <details className={styles.install}><summary>Установить на телефон</summary><p>Android: откройте меню браузера и выберите «Установить приложение» или «Добавить на главный экран». iPhone: в Safari нажмите «Поделиться» → «На экран Домой».</p></details>;
}
