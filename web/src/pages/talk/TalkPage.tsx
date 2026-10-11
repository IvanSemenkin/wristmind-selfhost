import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useLocation } from '@/app/router';
import { PanelLeft, MessageSquarePlus, Settings2, WifiOff } from 'lucide-react';
import { useActions } from '@/services';
import { useIsMobile } from '@/lib/hooks';
import { Conversation } from '@/pages/chats/Conversation';
import { Composer } from '@/pages/chats/Composer';
import { ChatList } from '@/pages/chats/ChatListPane';
import { Drawer, useToast } from '@/components';
import styles from './Talk.module.css';
import { InstallApp } from './InstallApp';

export function TalkPage({ history = false }: { history?: boolean }) {
  const { chatId } = useParams<{ chatId?: string }>();
  const mobile = useIsMobile();
  const location = useLocation();
  const [historyOpen, setHistoryOpen] = useState(false);
  useEffect(() => { setHistoryOpen(false); }, [location.pathname]);
  const navigate = useNavigate();
  const actions = useActions();
  const toast = useToast();
  const [research, setResearch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recovery, setRecovery] = useState<{chatId:string;text:string} | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const submitting = useRef(false);
  const firstRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    document.title = 'WristMind — чаты';
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update); window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  const send = async (text: string) => {
    if (submitting.current) return false;
    submitting.current = true; setBusy(true);
    let createdId: string | undefined;
    try {
      const chat = await actions.createChat(null);
      // Store commits the optimistic turn before navigation; the same live stream
      // powers Conversation. No second backend or independent history is created.
      createdId = chat.id;
      const controller = new AbortController(); firstRequest.current = controller;
      const result = actions.sendMessage({ chat_id: chat.id, content: text, research_mode: research, signal: controller.signal });
      navigate(`/talk/${chat.id}`);
      await result;
    } catch {
      try { sessionStorage.setItem(`wristmind.draft.${createdId ?? 'talk-new'}`, text); } catch { /* optional */ }
      if (createdId) setRecovery({chatId:createdId,text});
      toast.error('Не удалось отправить сообщение', 'Текст сохранён в черновике. Проверьте соединение и повторите отправку.');
      return false;
    } finally { submitting.current = false; firstRequest.current = null; setBusy(false); }
  };
  return <div className={styles.workspace}>
    {!online && <div className={styles.offline} role="status"><WifiOff size={16} />Нет соединения. Черновик сохраняется; история обновится после подключения.</div>}
    {mobile && !chatId && <nav className={styles.mobileHeader} aria-label="Чаты">
      <button type="button" onClick={() => setHistoryOpen(true)} aria-label="История чатов" title="История чатов"><PanelLeft aria-hidden /></button>
      <Link to="/talk" className={styles.mobileBrand}>WristMind</Link>
      <Link to="/talk" aria-label="Новый чат" title="Новый чат"><MessageSquarePlus /></Link>
    </nav>}
    {history ? <section className={styles.history} aria-label="История чатов"><h1>Чаты</h1><ChatList variant="rail" />{mobile && <footer className={styles.historyFooter}><InstallApp /><Link to="/main" className={styles.panelLink}><Settings2 size={16} />Панель управления</Link></footer>}</section>
      : chatId ? <Conversation key={chatId} chatId={chatId} onOpenHistory={() => setHistoryOpen(true)} onExternalStop={() => firstRequest.current?.abort()} recoveryText={recovery?.chatId === chatId ? recovery.text : undefined} />
      : <section className={styles.welcome} aria-label="Новый разговор">
        <div className={styles.intro} data-talk-intro><h1>Чем могу помочь?</h1></div>
        <div className={styles.startInput}>
          <Composer draftKey="talk-new" onSend={send} streaming={busy} onStop={() => firstRequest.current?.abort()} researchMode={research} onResearchModeToggle={setResearch} placeholder="Спросите что-нибудь…" />
        </div>
      </section>}
    <Drawer side="left" size="sm" bodyScroll={false} title="WristMind" open={mobile && historyOpen} onClose={() => setHistoryOpen(false)}>
      <div className={styles.historyDrawer}>
        <button type="button" className={styles.historyNewChat} onClick={() => { setHistoryOpen(false); navigate('/talk'); }}><MessageSquarePlus aria-hidden /><span>Новый чат</span></button>
        <div className={styles.drawerList} onClick={event => { if ((event.target as HTMLElement).closest('a')) setHistoryOpen(false); }}><ChatList variant="rail" activeChatId={chatId} /></div>
        <footer className={styles.historyFooter}><InstallApp /><Link to="/main" className={styles.panelLink}><Settings2 size={16} />Панель управления</Link></footer>
      </div>
    </Drawer>
  </div>;
}
