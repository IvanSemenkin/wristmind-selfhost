import { chatBase } from '@/lib/chatSurface';
import { useLocation } from '@/app/router';

/** Keep shared chat actions inside the surface that opened them. */
export function useChatBase() {
  return chatBase(useLocation().pathname);
}
