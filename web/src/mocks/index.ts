import { MockWristMindService } from './MockWristMindService';
import type { WristMindService } from '@/services/types';
import type { Session } from '@/session';

/* =============================================================================
   Mock transport wiring.

   `createMockService(session)` is the only export the composition root needs.
   When the backend is ready this becomes:

       export const createService = (session: Session): WristMindService =>
         new ApiWristMindService(session);

   and nothing else in the console changes.
   ========================================================================== */

export function createMockService(session: Session): WristMindService {
  return new MockWristMindService(session);
}

export { MockWristMindService };
export { composeAnswer, deriveChatTitle } from './answers';
