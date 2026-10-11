import { createRequestId } from './id.ts';
/** Ordered, bounded dictation packets; retries keep their session and sequence. */
export type SpeechPacket = {
  session_id: string;
  action: 'start' | 'chunk' | 'finish' | 'cancel';
  seq?: number;
  data?: string;
  encoding?: 'pcm' | 'pcm_zlib';
};
export type SpeechResult = { status: string; seq?: number; text?: string };
export type SpeechTransport = (packet: SpeechPacket, signal: AbortSignal) => Promise<SpeechResult>;

export function encodePcm16(samples: Float32Array, rate: number): Uint8Array {
  const buffer = new ArrayBuffer(Math.floor(samples.length * 16000 / rate) * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < buffer.byteLength / 2; i++) {
    const start = Math.floor(i * rate / 16000);
    const end = Math.min(samples.length, Math.max(start + 1, Math.floor((i + 1) * rate / 16000)));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    view.setInt16(i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Uint8Array(buffer);
}

async function audioPacket(audio: Uint8Array): Promise<Pick<SpeechPacket, 'data' | 'encoding'>> {
  let wire = audio;
  let encoding: SpeechPacket['encoding'] = 'pcm';
  if (typeof CompressionStream !== 'undefined') {
    try {
      const compressed = new Uint8Array(await new Response(new Blob([audio.slice().buffer as ArrayBuffer]).stream().pipeThrough(new CompressionStream('deflate'))).arrayBuffer());
      if (compressed.length < audio.length) { wire = compressed; encoding = 'pcm_zlib'; }
    } catch { /* Raw PCM works on browsers without deflate support. */ }
  }
  return { data: btoa(Array.from(wire, (byte) => String.fromCharCode(byte)).join('')), encoding };
}

export function startStreamingDictation(transport: SpeechTransport, signal: AbortSignal, sessionId: string = createRequestId()) {
  const queue: Uint8Array[] = [];
  let queuedBytes = 0;
  let totalBytes = 0;
  let finishing = false;
  let failed = false;
  let wake: (() => void) | undefined;
  const notify = () => { wake?.(); wake = undefined; };
  signal.addEventListener('abort', notify, { once: true });

  async function send(packet: SpeechPacket): Promise<SpeechResult> {
    for (let attempt = 0; ; attempt++) {
      signal.throwIfAborted();
      const controller = new AbortController();
      const abort = () => controller.abort(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      const timer = setTimeout(() => controller.abort(), packet.action === 'finish' ? 30_000 : 20_000);
      try {
        return await transport(packet, controller.signal);
      } catch (error) {
        signal.throwIfAborted();
        const status = typeof error === 'object' && error !== null && 'status' in error ? Number(error.status) : 0;
        if (attempt >= 1 || (status !== 0 && status !== 408 && status !== 429 && status < 500)) throw error;
      } finally {
        clearTimeout(timer);
        signal.removeEventListener('abort', abort);
      }
    }
  }

  const result = (async () => {
    try {
      await send({ session_id: sessionId, action: 'start' });
      let seq = 0;
      while (!finishing || queuedBytes > 0) {
        signal.throwIfAborted();
        if (queuedBytes < 12_800 && !finishing) {
          await new Promise<void>((resolve) => { wake = resolve; });
          continue;
        }
        if (!queuedBytes) break;
        const parts: Uint8Array[] = [];
        let size = 0;
        while (queue.length && size + queue[0].length <= 64_000) {
          const part = queue.shift()!;
          parts.push(part); size += part.length; queuedBytes -= part.length;
        }
        const audio = new Uint8Array(size);
        let offset = 0;
        for (const part of parts) { audio.set(part, offset); offset += part.length; }
        await send({ session_id: sessionId, action: 'chunk', seq, ...await audioPacket(audio) });
        seq++;
      }
      const complete = await send({ session_id: sessionId, action: 'finish' });
      const text = complete.text?.trim();
      if (!text) throw new Error('Речь не распознана. Попробуйте ещё раз.');
      return text;
    } finally {
      failed = true;
      signal.removeEventListener('abort', notify);
    }
  })();
  // Recording can continue while transport recovers; finish observes this error.
  void result.catch(() => {});
  return {
    push(audio: Uint8Array) {
      if (failed || finishing || signal.aborted) return;
      if (!audio.length || audio.length > 64_000 || audio.length % 2 || totalBytes + audio.length > 960_000) {
        throw new Error('Некорректный аудиофрагмент');
      }
      queue.push(audio); queuedBytes += audio.length; totalBytes += audio.length; notify();
    },
    finish() { finishing = true; notify(); return result; },
    sessionId,
  };
}
