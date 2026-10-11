import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { ArrowUp, Square, Mic, X } from 'lucide-react';
import { useService } from '@/services';
import { startPcmRecording, type PcmRecording } from './pcmRecorder';
import { startStreamingDictation } from '@/lib/streamingDictation';
import styles from './Chats.module.css';
import { useSession } from '@/session';
import { providerRequest } from '@/pages/settings/providers/providerApi';

export function VoiceDictation({ disabled, onText, onSend, onBusy, onError }: {
  disabled: boolean;
  onText: (text: string) => void;
  onSend: (text: string) => void;
  onBusy: (busy: boolean) => void;
  onError: (message: string) => void;
}) {
  const service = useService();
  const access = useSession();
  const [voiceUnavailable, setVoiceUnavailable] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      void providerRequest<{ selfhost: boolean; features: { voice: { available: boolean; reason: string } } }>(access, 'capabilities', undefined, 'GET', controller.signal)
        .then(result => { if (!controller.signal.aborted) setVoiceUnavailable(result.selfhost && !result.features.voice.available ? result.features.voice.reason : ''); }).catch(() => {});
    };
    load(); window.addEventListener('focus', load);
    return () => { controller.abort(); window.removeEventListener('focus', load); };
  }, [access.baseUrl, access.token]); // eslint-disable-line react-hooks/exhaustive-deps
  const [phase, setPhase] = useState<'idle' | 'starting' | 'recording' | 'transcribing'>('idle');
  const [seconds, setSeconds] = useState(0);
  const meter = useRef<HTMLCanvasElement | null>(null);
  const amplitude = useRef(0);
  const recording = useRef<PcmRecording | null>(null);
  const request = useRef<AbortController | null>(null);
  const streaming = useRef<ReturnType<typeof startStreamingDictation> | null>(null);
  const generation = useRef(0);
  const active = useRef(false);
  const done = useRef<() => void>(() => {});

  useEffect(() => () => {
    generation.current += 1;
    recording.current?.cancel();
    request.current?.abort();
    stopStream();
  }, []);

  useEffect(() => {
    if (phase !== 'recording') return;
    const started = performance.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((performance.now() - started) / 1000);
      setSeconds(elapsed);
      if (elapsed >= 29) done.current();
    }, 250);
    return () => clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    if ((phase !== 'recording' && phase !== 'starting') || !meter.current) return;
    const canvas = meter.current;
    const context = canvas.getContext('2d');
    if (!context) return;
    const samples: number[] = Array.from({ length: 64 }, () => 0);
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const color = getComputedStyle(canvas).getPropertyValue('--accent').trim();
    let width = 0;
    const resize = () => {
      width = canvas.getBoundingClientRect().width;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(36 * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    let frame = 0;
    let previous = performance.now();
    const draw = (now: number) => {
      if (now - previous >= 100) {
        samples.push(amplitude.current);
        if (samples.length > 64) samples.shift();
        amplitude.current = 0;
        previous = now;
      }
      const offset = reducedMotion ? 0 : (now - previous) / 100 * 6;
      context.clearRect(0, 0, width, 36);
      context.strokeStyle = color;
      context.lineWidth = 3;
      context.lineCap = 'round';
      context.beginPath();
      for (let index = samples.length - 1; index >= 0; index--) {
        const x = width - 2 - (samples.length - 1 - index) * 6 - offset;
        const height = Math.sqrt(samples[index]) * 31;
        context.moveTo(x, 18 - height / 2);
        context.lineTo(x, 18 + Math.max(0.1, height / 2));
      }
      context.stroke();
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [phase]);

  function stopStream() {
    const session = streaming.current; streaming.current = null;
    if (session && service.speechStream) {
      void service.speechStream({ session_id: session.sessionId, action: 'cancel' }, AbortSignal.timeout(5000)).catch(() => {});
    }
  }

  function cancel() {
    generation.current += 1;
    active.current = false;
    recording.current?.cancel(); recording.current = null;
    request.current?.abort(); request.current = null; stopStream();
    setPhase('idle'); onBusy(false); onError('');
  }

  async function start() {
    if (disabled || active.current) return;
    active.current = true;
    const current = ++generation.current;
    // Commit the startup feedback before browser audio/device initialization.
    flushSync(() => { onError(''); setPhase('starting'); onBusy(true); setSeconds(0); });
    amplitude.current = 0;
    try {
      if (voiceUnavailable) throw new Error(voiceUnavailable);
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
        throw new Error('Браузер не поддерживает запись. Откройте панель по HTTPS в Chrome или Safari.');
      }
      const controller = new AbortController(); request.current = controller;
      let session: ReturnType<typeof startStreamingDictation> | null = null;
      const earlyChunks: Uint8Array[] = [];
      // Request the device first, in the original pointer/keyboard gesture.
      // Network startup runs alongside it, never before the microphone request.
      const capture = startPcmRecording((level) => {
        if (current !== generation.current) return;
        amplitude.current = Math.max(amplitude.current, level);
      }, (pcm) => {
        if (current !== generation.current || !service.speechStream) return;
        if (session) session.push(pcm);
        else earlyChunks.push(pcm);
      });
      session = service.speechStream
        ? startStreamingDictation((packet, signal) => service.speechStream!(packet, signal), controller.signal)
        : null;
      streaming.current = session;
      for (const chunk of earlyChunks) session?.push(chunk);
      const audio = await capture;
      if (current !== generation.current) { audio.cancel(); return; }
      recording.current = audio;
      setPhase('recording');
    } catch (error) {
      if (current !== generation.current) return;
      request.current?.abort(); request.current = null; stopStream();
      onError(error instanceof DOMException && error.name === 'NotAllowedError'
        ? 'Разрешите доступ к микрофону в настройках браузера.'
        : error instanceof Error ? error.message : 'Не удалось включить микрофон.');
      active.current = false; setPhase('idle'); onBusy(false);
    }
  }

  async function finish(action: 'draft' | 'send' = 'draft') {
    const audio = recording.current;
    if (!audio || !service.transcribeAudio) return;
    recording.current = null;
    const current = generation.current;
    const controller = request.current ?? new AbortController(); request.current = controller;
    setPhase('transcribing');
    try {
      const clip = audio.finish();
      let text: string;
      try {
        if (!streaming.current) throw new Error('Streaming unavailable');
        text = await streaming.current.finish();
      } catch {
        controller.signal.throwIfAborted();
        stopStream();
        text = await service.transcribeAudio(clip, AbortSignal.any([controller.signal, AbortSignal.timeout(40_000)]));
      }
      if (!text.trim()) throw new Error('Речь не распознана. Попробуйте ещё раз.');
      if (current === generation.current) {
        if (action === 'send') onSend(text);
        else onText(text);
      }
    } catch (error) {
      if (current === generation.current) {
        const message = error instanceof Error ? error.message : 'Не удалось распознать речь.';
        onError(message);
      }
    } finally {
      if (current === generation.current) { active.current = false; setPhase('idle'); onBusy(false); request.current = null; stopStream(); }
    }
  }
  done.current = () => { void finish(); };

  if (!service.transcribeAudio) return null;
  return <div className={styles.dictation} data-active={phase !== 'idle' || undefined} data-phase={phase}>
    {phase === 'idle' ? <button type="button" className={styles.voiceButton} aria-label="Голосовой ввод" title={voiceUnavailable || "Голосовой ввод"} onPointerDown={event => { if (event.isPrimary && event.button === 0) void start(); }} onClick={() => void start()} disabled={disabled}><Mic /></button> : <>
      <button type="button" className={styles.voiceButton} aria-label="Отменить запись" title="Отменить запись" onClick={cancel}><X /></button>
      <div className={styles.dictationStatus} role="status" aria-label={phase === 'starting' ? 'Включаем микрофон' : phase === 'recording' ? 'Микрофон записывает' : 'Распознаём речь'}>
        {phase === 'recording' || phase === 'starting' ? <>
          <canvas ref={meter} className={styles.voiceMeter} aria-hidden="true" />
          <span className={styles.voiceTime}>{phase === 'starting' ? 'Включаем…' : `0:${String(seconds).padStart(2, '0')}`}</span>
        </> : <span>Распознаём…</span>}
      </div>
      {phase === 'recording' && <>
        <button type="button" className={`${styles.voiceButton} ${styles.voiceStop}`} aria-label="Остановить запись и вставить текст" title="Остановить и вставить текст" onClick={() => void finish('draft')}><Square /></button>
        <button type="button" className={`${styles.voiceButton} ${styles.voiceConfirm}`} aria-label="Отправить голосовое сообщение" title="Распознать и отправить" onClick={() => void finish('send')}><ArrowUp /></button>
      </>}
    </>}
  </div>;
}
