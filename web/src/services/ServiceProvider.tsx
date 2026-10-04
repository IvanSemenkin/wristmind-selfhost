import { createContext, useContext, useEffect, useMemo } from 'react';
import type { ReactNode } from 'react';
import { WristMindClientStore } from '@/store/clientStore';
import type { WristMindService } from './types';
import type { Session } from '@/session';

/* =============================================================================
   Composition root for the data layer.

   The provider receives a `Session` and a `WristMindService` — nothing else.
   Swapping `createMockService(session)` for `createApiService(session)` is the
   entire backend integration; pages and components are untouched.
   ========================================================================== */

const ServiceContext = createContext<WristMindService | null>(null);
const StoreContext = createContext<WristMindClientStore | null>(null);

export interface WristMindProviderProps {
  session: Session;
  service: WristMindService;
  children: ReactNode;
}

export function WristMindProvider({ session, service, children }: WristMindProviderProps) {
  const store = useMemo(
    () => new WristMindClientStore(service, session),
    [service, session],
  );

  useEffect(() => {
    void store.bootstrap();
    return () => store.dispose();
  }, [store]);

  return (
    <ServiceContext.Provider value={service}>
      <StoreContext.Provider value={store}>{children}</StoreContext.Provider>
    </ServiceContext.Provider>
  );
}

/** The transport itself, for the rare caller that needs it directly. */
export function useService(): WristMindService {
  const service = useContext(ServiceContext);
  if (!service) throw new Error('useService должен вызываться внутри WristMindProvider');
  return service;
}

/** The cache and its actions. */
export function useStore(): WristMindClientStore {
  const store = useContext(StoreContext);
  if (!store) throw new Error('useStore должен вызываться внутри WristMindProvider');
  return store;
}

/**
 * Bound actions. The store instance is stable for the lifetime of the session,
 * so this object is safe in dependency arrays.
 */
export function useActions(): WristMindClientStore {
  return useStore();
}
