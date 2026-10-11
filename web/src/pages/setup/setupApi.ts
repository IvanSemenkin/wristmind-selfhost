export type SetupStatus = { selfhost: true; admin_created: boolean; completed: boolean; demo: boolean; https: boolean };
export type WizardState = { mode_name: string; mode_prompt: string; model_configured: boolean; model_id: string; models: { id: string; label: string; provider: string }[]; mode_created: boolean; probe_passed: boolean; completed: boolean; demo: boolean };

export async function setupRequest<T>(path: string, body?: unknown, activation?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/v1/selfhost/${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-WristMind-CSRF': '1', ...(activation ? { 'X-WristMind-Setup': activation } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(40_000),
    });
  } catch {
    throw new Error('Не удалось связаться с сервером. Проверьте соединение и повторите.');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : 'Не удалось выполнить действие. Повторите.');
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
