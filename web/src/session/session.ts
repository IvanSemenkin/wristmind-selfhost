/* =============================================================================
   Session boundary.

   The real backend will authenticate the console with a session that carries a
   base URL, an access token and the id of the device the panel runs on. This
   module defines that shape and the provider the UI reads it from, so swapping
   the mock session for a real one touches exactly one place.

   Nothing here stores or models secrets: no bootstrap secret, no API keys.
   ========================================================================== */

import { createContext, useContext } from 'react';

export interface Session {
  /** Origin of the WristMind API the console talks to. */
  baseUrl: string;
  /** Access token issued to this web panel on pairing. */
  token: string;
  /** Id of the device record representing this panel. */
  deviceId: string;
  /** The console is administator-only; kept for completeness of the boundary. */
  isAdmin: boolean;
}

export interface SessionState {
  status: 'anonymous' | 'authenticated';
  session: Session | null;
}

export const ANONYMOUS_SESSION: SessionState = { status: 'anonymous', session: null };

export const SessionContext = createContext<SessionState>(ANONYMOUS_SESSION);

/** Reads the current session. Throws when used outside the provider. */
export function useSession(): Session {
  const state = useContext(SessionContext);
  if (!state.session) {
    throw new Error('Сессия не установлена: оберните приложение в SessionProvider');
  }
  return state.session;
}

export function useSessionState(): SessionState {
  return useContext(SessionContext);
}

/**
 * Mock session used while the backend is not connected.
 *
 * The token is a placeholder that never leaves the browser: the mock service
 * ignores it. It is deliberately not a realistic-looking credential.
 */
export function createMockSession(): Session {
  return {
    baseUrl: '/api',
    token: 'mock-session',
    deviceId: 'dev_console',
    isAdmin: true,
  };
}
