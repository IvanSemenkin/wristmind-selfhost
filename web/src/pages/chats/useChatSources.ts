import { useCallback, useEffect, useState } from 'react';
import { useService } from '@/services';
import { describeError } from '@/services/errors';
import type { ChatSources } from '@/types';
import { useSnapshot } from '@/store/hooks';

/* =============================================================================
   Loads the chat-scoped source index from the read-only endpoint.

   Deliberately not cached in the shared store: chat sources are only needed
   while one conversation is on screen, and they change as new answers land.
   ========================================================================== */

export interface ChatSourcesState {
  sources: ChatSources | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * @param chatId   the conversation whose index is requested;
 * @param revision cheap dependency (e.g. the message count) that re-fetches the
 *                 index after a new answer may have created Working Sources.
 */
export function useChatSources(chatId: string | undefined, revision?: unknown): ChatSourcesState {
  const service = useService();
  const { chatSourcesRevision } = useSnapshot();
  const [sources, setSources] = useState<ChatSources | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!chatId) {
      setSources(null);
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);

    service.chats
      .sources(chatId)
      .then((value) => {
        if (active) setSources(value);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setSources(null);
        setError(describeError(cause, 'Не удалось загрузить источники чата'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [service, chatId, nonce, revision, chatSourcesRevision]);

  return { sources, loading, error, reload };
}
