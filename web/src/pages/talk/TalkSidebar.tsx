import { Link, useParams } from '@/app/router';
import { MessageSquarePlus, Settings2 } from 'lucide-react';
import { ChatList } from '@/pages/chats/ChatListPane';
import { useIsMobile } from '@/lib/hooks';
import styles from './Talk.module.css';
import { InstallApp } from './InstallApp';

export function TalkSidebar() {
  const { chatId } = useParams<{ chatId?: string }>();
  const mobile = useIsMobile();
  if (mobile) return null;
  return <aside className={styles.sidebar} aria-label="История разговоров">
    <Link to="/talk" className={styles.brand}><img src="/wristmind-mark.svg" width="28" height="28" alt="" />WristMind</Link>
    <Link to="/talk" className={styles.newChat}><MessageSquarePlus aria-hidden />Новый чат</Link>
    <ChatList variant="rail" activeChatId={chatId} />
    <InstallApp />
    <Link to="/main" className={styles.panelLink}><Settings2 aria-hidden />Панель управления</Link>
  </aside>;
}
