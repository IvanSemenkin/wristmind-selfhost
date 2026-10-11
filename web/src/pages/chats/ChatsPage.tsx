import { useEffect } from 'react';
import { useParams, useSearchParams } from '@/app/router';
import { useIsMobile } from '@/lib/hooks';
import { useQuickActions } from '@/app/QuickActions';
import { ChatListPane, ConversationPlaceholder } from './ChatListPane';
import { Conversation } from './Conversation';
import styles from './Chats.module.css';

/**
 * The conversation surface. On desktop the conversation list lives inside the
 * navigation rail, so this route renders only the dialog; below the rail
 * breakpoint the list becomes its own screen and the two swap places.
 */
export function ChatsPage() {
  const { chatId } = useParams<{ chatId?: string }>();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();
  const actions = useQuickActions();

  useEffect(() => {
    if (searchParams.get('quick') !== '1') return;
    actions.newChat(null);
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, actions]);

  const showList = isMobile && !chatId;
  const showConversation = !isMobile || Boolean(chatId);

  return (
    <div className={styles.layout}>
      {showList && <ChatListPane activeChatId={chatId} />}
      {showConversation &&
        (chatId ? (
          <Conversation chatId={chatId} key={chatId} />
        ) : (
          <ConversationPlaceholder />
        ))}
    </div>
  );
}
