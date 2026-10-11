import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { useStore } from '@/services';
import type { AppSnapshot } from './clientStore';
import type {
  ApiPath,
  Chat,
  Device,
  KnowledgeSource,
  Message,
  Mode,
  Model,
  OverviewStats,
  PairingCode,
  ServiceHealth,
  Settings,
  SourceContent,
} from '@/types';

/* =============================================================================
   Store selectors.

   Pages import from here and never from a concrete service implementation, so
   the UI has no knowledge of mock vs. real data.
   ========================================================================== */

export function useSnapshot(): AppSnapshot {
  const store = useStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

export function useStoreStatus(): { status: AppSnapshot['status']; error: string | null } {
  const snapshot = useSnapshot();
  return { status: snapshot.status, error: snapshot.error };
}

/** Sources may omit `updated_at`; fall back to their creation time. */
const lastTouched = (entity: { updated_at?: string; created_at: string }): number =>
  new Date(entity.updated_at ?? entity.created_at).getTime();

const updatedDesc = (
  a: { updated_at?: string; created_at: string },
  b: { updated_at?: string; created_at: string },
) => lastTouched(b) - lastTouched(a);

/* -------------------------------------------------------------------------- */
/* Modes                                                                      */
/* -------------------------------------------------------------------------- */

export function useModes(): Mode[] {
  const { modes } = useSnapshot();
  return useMemo(() => [...modes].sort((a, b) => a.name.localeCompare(b.name, 'ru')), [modes]);
}

export function useMode(id: string | undefined): Mode | undefined {
  const { modes } = useSnapshot();
  return useMemo(() => modes.find((m) => m.id === id), [modes, id]);
}

/* -------------------------------------------------------------------------- */
/* Chats & messages                                                           */
/* -------------------------------------------------------------------------- */

export function useChats(): Chat[] {
  const { chats } = useSnapshot();
  return useMemo(
    () => [...chats].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || updatedDesc(a, b)),
    [chats],
  );
}

export function useChat(id: string | undefined): Chat | undefined {
  const { chats } = useSnapshot();
  return useMemo(() => chats.find((c) => c.id === id), [chats, id]);
}

/** Loads a chat's history on first use; subsequent renders read the cache. */
export function useChatMessages(chatId: string | undefined): Message[] {
  const snapshot = useSnapshot();
  const store = useStore();

  useEffect(() => {
    if (!chatId) return;
    void store.loadMessages(chatId);
  }, [chatId, store]);

  return useMemo(() => (chatId ? (snapshot.messages[chatId] ?? []) : []), [snapshot, chatId]);
}

/* -------------------------------------------------------------------------- */
/* Knowledge base                                                             */
/* -------------------------------------------------------------------------- */

export function useSources(modeId?: string | null): KnowledgeSource[] {
  const { sources } = useSnapshot();
  return useMemo(() => {
    const list = modeId ? sources.filter((s) => s.mode_id === modeId) : sources;
    return [...list].sort(updatedDesc);
  }, [sources, modeId]);
}

export function useSource(id: string | undefined): KnowledgeSource | undefined {
  const { sources } = useSnapshot();
  return useMemo(() => sources.find((s) => s.id === id), [sources, id]);
}

/**
 * Extracted pages and chunks. Loaded lazily, so opening a source shows a
 * skeleton while the content request is in flight.
 */
export function useSourceContent(sourceId: string | undefined): {
  content: SourceContent | undefined;
  loading: boolean;
} {
  const snapshot = useSnapshot();
  const store = useStore();

  useEffect(() => {
    if (!sourceId) return;
    void store.loadSourceContent(sourceId);
  }, [sourceId, store]);

  const content = sourceId ? snapshot.sourceContent[sourceId] : undefined;
  return { content, loading: Boolean(sourceId) && content === undefined };
}

/* -------------------------------------------------------------------------- */
/* Devices & pairing                                                          */
/* -------------------------------------------------------------------------- */

export function useDevices(): Device[] {
  const { devices } = useSnapshot();
  return useMemo(
    () => [...devices].sort((a, b) => a.name.localeCompare(b.name, 'ru')),
    [devices],
  );
}

export function usePairingCodes(): PairingCode[] {
  const { pairingCodes } = useSnapshot();
  return useMemo(
    () => [...pairingCodes].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
    [pairingCodes],
  );
}

/* -------------------------------------------------------------------------- */
/* Models, settings, statistics, health                                       */
/* -------------------------------------------------------------------------- */

export function useModels(): Model[] {
  return useSnapshot().models;
}

export function useSettings(): Settings | null {
  return useSnapshot().settings;
}

export function useStats(): OverviewStats | null {
  return useSnapshot().stats;
}

export function useServiceHealth(): ServiceHealth[] {
  return useSnapshot().health?.services ?? [];
}

/** Which path currently answers: the local backend or the reserved VPS one. */
export function useApiPath(): ApiPath {
  return useSnapshot().health?.api_path ?? 'local';
}

/**
 * Counters derived from the cache. Server-provided statistics stay in
 * `useStats()`; anything that is a pure function of the loaded entities is
 * computed here so it can never drift from what the UI displays.
 */
export function useDerivedStats() {
  const snapshot = useSnapshot();
  return useMemo(() => {
    const { modes, sources, chats, devices, stats } = snapshot;
    const readySources = sources.filter((s) => s.status === 'ready');
    const processing = sources.filter((s) => s.status === 'processing' || s.status === 'uploading');
    const failed = sources.filter((s) => s.status === 'error');

    return {
      modeCount: modes.length,
      hiddenOnWatchCount: modes.filter((m) => m.hidden_on_watch).length,
      watchModeCount: modes.filter((m) => !m.hidden_on_watch).length,
      chatCount: chats.length,
      deviceCount: devices.length,
      activeDeviceCount: devices.filter((d) => !d.revoked_at).length,
      readySources,
      processing,
      failed,
      totalTokens: readySources.reduce((sum, s) => sum + s.token_count, 0),
      totalChunks: readySources.reduce((sum, s) => sum + s.chunk_count, 0),
      totalPages: readySources.reduce((sum, s) => sum + s.page_count, 0),
      totalAiRequests: stats?.total_ai_requests ?? 0,
      requestsToday: stats?.requests_today ?? 0,
      requestsYesterday: stats?.requests_yesterday ?? 0,
      errorRateToday: stats?.error_rate_today ?? 0,
      activity: stats?.activity ?? [],
      usage: stats?.usage ?? [],
    };
  }, [snapshot]);
}
