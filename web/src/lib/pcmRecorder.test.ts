import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { startPcmRecording } from '../pages/chats/pcmRecorder.ts';

test('audio is unlocked in the click turn and first PCM is captured before startup resolves', async () => {
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const originalAudio = Object.getOwnPropertyDescriptor(globalThis, 'AudioContext');
  const events: string[] = [], chunks: Uint8Array[] = [];
  let ready!: () => void;
  const resumed = new Promise<void>(resolve => { ready = resolve; });
  let stopped = 0, closed = 0;
  const processor = {
    onaudioprocess: null as null | ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void),
    connect() {}, disconnect() {},
  };
  class AudioMock {
    sampleRate = 16000;
    destination = {};
    resume() { events.push('resume'); return resumed; }
    createMediaStreamSource() { return { connect() { events.push('capture'); }, disconnect() {} }; }
    createScriptProcessor(size: number) { assert.equal(size,1024); return processor; }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} }; }
    close() { closed++; return Promise.resolve(); }
  }
  Object.defineProperty(globalThis, 'AudioContext', { configurable:true, value:AudioMock });
  Object.defineProperty(globalThis, 'navigator', { configurable:true, value:{mediaDevices:{
    getUserMedia() { events.push('microphone'); return Promise.resolve({getTracks:()=>[{stop(){stopped++;}}]}); },
  }} });
  try {
    const started = startPcmRecording(()=>{}, pcm=>chunks.push(pcm));
    assert.deepEqual(events,['resume','microphone']);
    await Promise.resolve();
    assert.ok(processor.onaudioprocess, 'capture must not wait for resume resolution');
    processor.onaudioprocess!({inputBuffer:{getChannelData:()=>new Float32Array([.5,-.5])}});
    assert.deepEqual([...chunks[0]],[0,64,0,192]);
    ready();
    const recording=await started;
    assert.deepEqual([...new Uint8Array(await recording.finish().arrayBuffer())],[0,64,0,192]);
    assert.equal(stopped,1); assert.equal(closed,1);
  } finally {
    ready();
    if(originalNavigator)Object.defineProperty(globalThis,'navigator',originalNavigator);else Reflect.deleteProperty(globalThis,'navigator');
    if(originalAudio)Object.defineProperty(globalThis,'AudioContext',originalAudio);else Reflect.deleteProperty(globalThis,'AudioContext');
  }
});
