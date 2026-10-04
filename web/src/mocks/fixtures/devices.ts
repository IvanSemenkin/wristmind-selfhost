import type { Device, PairingCode } from '@/types';
import { DAY, HOUR, MINUTE, ago, ahead } from './random';

/* =============================================================================
   Devices and pairing codes.

   `MOCK_SESSION_DEVICE_ID` mirrors the id carried by the mock session, which is
   how the console recognises "this panel" without a server-side flag.
   ========================================================================== */

export const MOCK_SESSION_DEVICE_ID = 'dev_console';

export const SEED_DEVICES: Device[] = [
  {
    id: MOCK_SESSION_DEVICE_ID,
    name: 'MacBook Pro 14″',
    kind: 'WEB',
    is_admin: true,
    user_id: null,
    created_at: ago(18 * DAY),
    last_seen_at: ago(0.02 * HOUR),
    revoked_at: null,
    meta: {
      platform: 'macOS 15.2 · Chrome 132',
      app_version: 'Console 0.1.0',
      ip_address: '10.14.2.31',
      battery_level: null,
    },
  },
  {
    id: 'dev_pixel',
    name: 'Pixel 8 Pro',
    kind: 'PHONE',
    is_admin: false,
    user_id: null,
    created_at: ago(96 * DAY),
    last_seen_at: ago(0.05 * HOUR),
    revoked_at: null,
    meta: {
      platform: 'Android 15',
      app_version: 'WristMind 3.4.1',
      ip_address: '10.14.2.77',
      battery_level: 74,
    },
  },
  {
    id: 'dev_galaxy_watch',
    name: 'Galaxy Watch 6',
    kind: 'WATCH',
    is_admin: false,
    user_id: null,
    created_at: ago(96 * DAY),
    last_seen_at: ago(0.08 * HOUR),
    revoked_at: null,
    meta: {
      platform: 'Wear OS 5',
      app_version: 'WristMind 3.4.1',
      battery_level: 58,
    },
  },
  {
    id: 'dev_ipad',
    name: 'iPad Air',
    kind: 'WEB',
    is_admin: true,
    user_id: null,
    created_at: ago(7 * DAY),
    last_seen_at: ago(9 * HOUR),
    revoked_at: null,
    meta: {
      platform: 'iPadOS 18.2 · Safari',
      app_version: 'Console 0.1.0',
      ip_address: '10.14.2.104',
      battery_level: 41,
    },
  },
  {
    id: 'dev_pixel_watch',
    name: 'Pixel Watch 2',
    kind: 'WATCH',
    is_admin: false,
    user_id: null,
    created_at: ago(210 * DAY),
    last_seen_at: ago(4 * DAY),
    revoked_at: null,
    meta: {
      platform: 'Wear OS 5',
      app_version: 'WristMind 3.3.9',
    },
  },
];

export const SEED_PAIRING_CODES: PairingCode[] = [
  {
    code: '704213',
    target_kind: 'WATCH',
    created_at: ago(6 * MINUTE),
    expires_at: ahead(4 * MINUTE),
    claimed_at: null,
  },
];
