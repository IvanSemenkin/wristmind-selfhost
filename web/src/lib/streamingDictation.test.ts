import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { inflateSync } from 'node:zlib';
import { encodePcm16, startStreamingDictation, type SpeechPacket } from './streamingDictation.ts';

test('stream while recording, replay lost acknowledgement, flush before finish', async () => {
  const packets: SpeechPacket[] = [];
  let lose = true;
  const session = startStreamingDictation(async (packet) => {
    packets.push(packet);
    if (packet.action === 'chunk' && lose) { lose = false; throw Object.assign(new Error('network'), { status: 0 }); }
    return { status: 'complete', text: '  Привет  ' };
  }, new AbortController().signal, 'test-session');
  const audio = new Uint8Array(16000).fill(3);
  session.push(audio);
  for (let i = 0; i < 100 && packets.length < 3; i++) await new Promise((r) => setTimeout(r, 5));
  assert.equal(packets.filter((p) => p.action === 'chunk').length, 2);
  assert.deepEqual(packets[1], packets[2]);
  session.push(new Uint8Array([4, 5]));
  assert.equal(await session.finish(), 'Привет');
  assert.deepEqual(packets.map((p) => p.action), ['start', 'chunk', 'chunk', 'chunk', 'finish']);
  const bytes = Buffer.from(packets[1].data!, 'base64');
  assert.deepEqual(new Uint8Array(packets[1].encoding === 'pcm_zlib' ? inflateSync(bytes) : bytes), audio);
  assert.equal(packets[3].seq, 1);
});

test('permanent HTTP failure is not retried', async () => {
  let calls = 0;
  const session = startStreamingDictation(async () => { calls++; throw Object.assign(new Error('denied'), { status: 403 }); }, new AbortController().signal, 'denied');
  await assert.rejects(session.finish(), /denied/); assert.equal(calls, 1);
});

test('cancel wakes wait and does not send finish or queued audio', async () => {
  const abort = new AbortController(); const packets: SpeechPacket[] = [];
  const session = startStreamingDictation(async (p) => { packets.push(p); return { status: 'listening' }; }, abort.signal, 'cancel');
  await new Promise((r) => setTimeout(r, 0)); abort.abort(); session.push(new Uint8Array(16000));
  await assert.rejects(session.finish()); assert.deepEqual(packets.map((p) => p.action), ['start']);
});

test('empty output produces visible error', async () => {
  const session = startStreamingDictation(async () => ({ status: 'complete', text: '' }), new AbortController().signal, 'empty');
  await assert.rejects(session.finish(), /Речь не распознана/);
});

test('PCM clamps signed little endian samples', () => {
  assert.deepEqual([...encodePcm16(new Float32Array([-2, 0, 2]), 16000)], [0, 128, 0, 0, 255, 127]);
});

test('slow server startup preserves the very first audio chunk in order', async () => {
  let ready!: () => void;
  const startup = new Promise<void>(resolve => { ready = resolve; });
  const packets: SpeechPacket[] = [];
  const session = startStreamingDictation(async packet => {
    packets.push(packet);
    if (packet.action === 'start') await startup;
    return { status: 'complete', text: 'Первые слова сохранены' };
  }, new AbortController().signal, 'slow-start');
  const first = new Uint8Array([1, 2, 3, 4]);
  session.push(first);
  session.push(new Uint8Array([5, 6]));
  const result = session.finish();
  assert.deepEqual(packets.map(p => p.action), ['start']);
  ready();
  assert.equal(await result, 'Первые слова сохранены');
  const chunk = packets.find(p => p.action === 'chunk')!;
  const wire = Buffer.from(chunk.data!, 'base64');
  assert.deepEqual([... (chunk.encoding === 'pcm_zlib' ? inflateSync(wire) : wire)], [1,2,3,4,5,6]);
  assert.deepEqual(packets.map(p => p.action), ['start','chunk','finish']);
});
