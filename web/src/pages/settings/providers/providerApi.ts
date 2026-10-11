import type { Session } from '@/session';
export type Provider = { id: string; kind: string; label: string; base_url: string; enabled: boolean; has_key: boolean; allow_local: boolean };
export type InstalledModel = { id: string; provider: string; label: string; enabled: boolean; roles?: string[] };
export type Registry = { presets: { id: string; label: string; url: string }[]; providers: Provider[]; models: InstalledModel[]; default_model_id: string; demo: boolean; selfhost?: boolean; model_roles?: Record<string, string> };
export type Access = Pick<Session, 'baseUrl' | 'token'>;
export async function providerRequest<T>(access: Access, path: string, body?: unknown, method = 'POST', signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${access.baseUrl.replace(/\/+$/, '')}/v1/${path}`, {
      method: body === undefined ? 'GET' : method, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-WristMind-CSRF': '1', ...(access.token ? { Authorization: `Bearer ${access.token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body), signal: signal ?? AbortSignal.timeout(40_000),
    });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new Error('Не удалось связаться с сервером. Проверьте соединение и повторите.');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : 'Не удалось сохранить настройки. Повторите.');
  }
  return response.json() as Promise<T>;
}
