/** Two interfaces, one set of server chat IDs. Never rewrite API endpoints. */
export function isTalkPath(path: string): boolean {
  return path === '/talk' || path.startsWith('/talk/');
}
export function chatBase(path: string): '/talk' | '/chats' {
  return isTalkPath(path) ? '/talk' : '/chats';
}
export function chatListPath(path: string): string {
  return isTalkPath(path) ? '/talk/history' : '/chats';
}
