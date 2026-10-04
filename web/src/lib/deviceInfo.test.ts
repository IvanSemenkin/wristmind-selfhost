import assert from 'node:assert/strict';
import test from 'node:test';
import { deviceSessionLabel } from './deviceInfo.ts';

test('device labels distinguish web sessions without inventing a model', () => {
  assert.equal(deviceSessionLabel('WEB', 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0'), 'Chrome · Windows');
  assert.equal(deviceSessionLabel('WEB', 'Mozilla/5.0 (Macintosh) Version/18 Safari/605'), 'Safari · macOS');
  assert.equal(deviceSessionLabel('WEB', null), 'Браузер');
  assert.equal(deviceSessionLabel('WATCH', 'okhttp/4'), 'Wear OS');
});
