/* First-run setup API.
 *
 * These calls deliberately do not go through `WristMindService`: they happen
 * before any session exists and must work when the panel is only half
 * connected. The shape mirrors `enrollWebSession` in ApiWristMindService.
 */

export interface SetupStatus {
  first_run_completed: boolean;
  instance_claimed: boolean;
  admin_devices: number;
  active_modes: number;
  knowledge_sources: number;
  database_ok: boolean;
  provider_mode: 'mock' | 'live';
  provider_ready: boolean;
  providers_with_keys: string[];
  setup_required: boolean;
}

export interface ProviderKeyCheck {
  ok: boolean;
  provider: string;
  latency_ms: number | null;
  message: string;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

/** Reads the installation state. Never throws: the panel must still open. */
export async function fetchSetupStatus(baseUrl: string): Promise<SetupStatus | null> {
  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/setup/status`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    return (await response.json()) as SetupStatus;
  } catch {
    return null;
  }
}

/** Makes one real provider call with a candidate key. The key is not stored. */
export async function checkProviderKey(
  baseUrl: string,
  provider: 'openrouter' | 'deepseek',
  apiKey: string,
): Promise<ProviderKeyCheck> {
  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/setup/provider/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey.trim() }),
    });
    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('json') ? await response.json().catch(() => null) : null;
    if (!response.ok) {
      return {
        ok: false,
        provider,
        latency_ms: null,
        message: payload?.detail ?? `Проверка не удалась (${response.status})`,
      };
    }
    return payload as ProviderKeyCheck;
  } catch (cause) {
    return {
      ok: false,
      provider,
      latency_ms: null,
      message: cause instanceof Error ? cause.message : 'Нет связи с сервером',
    };
  }
}

/** Marks the first run as done. Returns false when it could not be saved. */
export async function completeSetup(baseUrl: string, token: string): Promise<boolean> {
  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/setup/complete`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.ok || response.status === 204;
  } catch {
    return false;
  }
}
