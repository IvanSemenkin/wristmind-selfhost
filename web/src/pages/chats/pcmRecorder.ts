import { encodePcm16 } from '../../lib/streamingDictation.ts';
export interface PcmRecording {
  finish(): Blob;
  cancel(): void;
}

/** Capture mono audio and encode the SpeechKit PCM contract without a codec dependency. */
export async function startPcmRecording(onLevel: (level: number) => void, onChunk?: (pcm: Uint8Array) => void): Promise<PcmRecording> {
  let stream: MediaStream | undefined;
  let context: AudioContext | undefined;
  try {
    // Unlock audio synchronously in the click gesture, while the microphone opens.
    context = new AudioContext();
    const ready = context.resume();
    void ready.catch(() => {});
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const microphone = stream;
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(1024, 1, 1);
    const mute = context.createGain();
    mute.gain.value = 0;
    const frames: Float32Array[] = [];
    let count = 0;
    const rate = context.sampleRate;
    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const part = input.slice(0, Math.max(0, Math.min(input.length, rate * 30 - count)));
      if (!part.length) return;
      frames.push(part);
      count += part.length;
      const pcm = encodePcm16(part, rate);
      if (pcm.length) onChunk?.(pcm);
      onLevel(Math.min(1, Math.sqrt(part.reduce((sum, sample) => sum + sample * sample, 0) / part.length) * 6));
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(context.destination);
    await ready;
    const close = () => {
      processor.onaudioprocess = null;
      source.disconnect(); processor.disconnect(); mute.disconnect();
      microphone.getTracks().forEach((track) => track.stop());
      void context?.close();
    };
    return {
      cancel: close,
      finish() {
        close();
        const samples = new Float32Array(count);
        let position = 0;
        for (const part of frames) { samples.set(part, position); position += part.length; }
        return new Blob([encodePcm16(samples, rate).buffer as ArrayBuffer], { type: 'application/octet-stream' });
      },
    };
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    void context?.close();
    throw error;
  }
}
