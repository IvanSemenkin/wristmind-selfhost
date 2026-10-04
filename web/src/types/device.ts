import type { IsoDateTime } from './common';

/* =============================================================================
   Devices & pairing.

   The system is single-administrator: there are no users, roles or
   per-user workspaces. `user_id` exists in the contract only because the
   backend carries it; it is never surfaced as a management concept.
   ========================================================================== */

export type DeviceKind = 'PHONE' | 'WATCH' | 'WEB';

export const DEVICE_KINDS: DeviceKind[] = ['PHONE', 'WATCH', 'WEB'];

export const DEVICE_KIND_LABELS: Record<DeviceKind, string> = {
  PHONE: 'Телефон',
  WATCH: 'Часы',
  WEB: 'Веб-панель',
};

export interface Device {
  id: string;
  name: string;
  kind: DeviceKind;
  is_admin: boolean;
  user_id: string | null;
  created_at: IsoDateTime;
  last_seen_at: IsoDateTime;
  revoked_at: IsoDateTime | null;
  enrolled_ip?: string | null;
  last_ip?: string | null;
  user_agent?: string | null;
  /**
   * Presentation-only metadata. Optional: when the backend does not provide it
   * the corresponding table columns fall back to a dash.
   */
  meta?: {
    platform?: string;
    app_version?: string;
    battery_level?: number | null;
    ip_address?: string | null;
  };
}

/** Connection state derived on the client from timestamps. */
export type DevicePresence = 'online' | 'idle' | 'revoked';

/** Presence is a view concern, so it is derived rather than stored. */
export function devicePresence(device: Device, now = Date.now()): DevicePresence {
  if (device.revoked_at) return 'revoked';
  const lastSeen = new Date(device.last_seen_at).getTime();
  if (!Number.isFinite(lastSeen)) return 'idle';
  const age = now - lastSeen;
  if (age < 5 * 60_000) return 'online';
  return 'idle';
}

/* -------------------------------------------------------------------------- */
/* Pairing                                                                    */
/* -------------------------------------------------------------------------- */

/** A short-lived, single-use code that enrols a new device. */
export interface PairingCode {
  code: string;
  /** Restricted to one device kind when set. */
  target_kind: DeviceKind | null;
  created_at: IsoDateTime;
  expires_at: IsoDateTime;
  claimed_at: IsoDateTime | null;
}

export const PAIRING_CODE_TTL_MS = 10 * 60_000;
export const PAIRING_CODE_LENGTH = 6;

export function isPairingCodeActive(code: PairingCode, now = Date.now()): boolean {
  return code.claimed_at === null && new Date(code.expires_at).getTime() > now;
}
