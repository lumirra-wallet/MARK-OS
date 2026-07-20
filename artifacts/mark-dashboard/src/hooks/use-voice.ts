import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for MARK — WebSocket + ScriptProcessorNode mic transport.
 *
 * Audio pipeline
 * ──────────────
 *   Inbound (mic → MARK):
 *     getUserMedia (native sample rate, AEC + NS + AGC on)
 *     → ScriptProcessorNode
 *     → resampleTo16k (linear interpolation)
 *     → floatTo16BitPCM
 *     → binary WebSocket frames → /ws/voice
 *     → VoiceSession (Silero VAD → faster-whisper) on the server
 *   Outbound (MARK → browser):
 *     Kokoro TTS on the server
 *     → binary PCM16 frames on the main /ws connection
 *     → SpeechPlayer (AudioContext) in markStore.ts
 *
 * Turn-taking (mirrors the server-side state machine in voice_pipeline.py)
 * ────────────────────────────────────────────────────────────────────────
 *   The server is the source of truth for when to mute.  speech_runtime
 *   calls mute_active_session() BEFORE the first audio byte is sent, so
 *   VoiceSession's VAD is already hard-muted by the time sound leaves the
 *   speakers.  The frontend mic gate (micMutedRef) provides a secondary
 *   layer: we stop sending PCM frames while MARK is speaking, reducing
 *   unnecessary network traffic and providing defence-in-depth.
 *
 *   Client-side mute state is driven by Zustand's isMarkSpeaking flag via
 *   a synchronous subscribe() call (not a useEffect) so the ref updates
 *   in the same tick as the store change — no render-cycle delay.
 *
 *   tts_start / tts_end are sent to the server as a SECONDARY / safety-net
 *   signal.  The primary mute path is server-proactive (speech_runtime →
 *   voice_pipeline directly).  Both paths are needed for robustness.
 *
 * Barge-in
 * ────────
 *   1. User starts talking → VAD fires speech_start on the server
 *   2. Server sends {"type":"speech_start"} back over /ws/voice
 *   3. Frontend calls stopMarkSpeech() — audio stops instantly
 *   4. micMutedRef ← false — mic opens immediately
 *   5. Server VAD transitions to LISTENING — next words are transcribed
 *   6. When VAD fires "end" → "final" event → browser POSTs /voice/message
 *
 * Echo cancellation layers
 * ────────────────────────
 *   1. getUserMedia echoCancellation + noiseSuppression — browser AEC
 *   2. Client mic gate (micMutedRef) — stops PCM frames during TTS
 *   3. Server-proactive mute (speech_runtime → VoiceSession) — VAD off
 *   4. Server POST_SPEECH holdoff (900ms, sample-accurate) — no transcripts
 *      after TTS even if residual echo sneaks through
 *   5. Backend Whisper no_speech_prob filter — rejects non-speech segments
 */

// ── PCM helpers ────────────────────────────────────────────────────────────

function resampleTo16k(floatPCM: Float32Array, srcRate: number): Float32Array {
  if (srcRate === 16000) return floatPCM;
  const ratio  = srcRate / 16000;
  const outLen = Math.floor(floatPCM.length / ratio);
  const out    = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const src = i * ratio;
    const lo  = Math.floor(src);
    const hi  = Math.min(lo + 1, floatPCM.length - 1);
    const t   = src - lo;
    out[i]    = floatPCM[lo] * (1 - t) + floatPCM[hi] * t;
  }
  return out;
}

function floatTo16BitPCM(floatPCM: Float32Array): ArrayBuffer {
  const buf  = new ArrayBuffer(floatPCM.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < floatPCM.length; i++) {
    const s = Math.max(-1, Math.min(1, floatPCM[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

// ── Hook ───────────────────────────────────────────────────────────────────

export function useVoice() {
  const {
    workspace, sendVoiceMessage, serverUrl,
    isMarkSpeaking, speechEngineUnavailable, stopMarkSpeech,
  } = useMarkStore();

  const [voiceEnabled,      setVoiceEnabled]     = useState(false);
  const [isListening,       setIsListening]       = useState(false);
  const [micLevel,          setMicLevel]          = useState(0);
  const [interimTranscript, setInterimTranscript] = useState('');
  const [supported] = useState(() =>
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioContext !== 'undefined',
  );

  // ── Refs (stable across renders, no re-render cost) ───────────────────────
  const wsRef              = useRef<WebSocket | null>(null);
  const audioCtxRef        = useRef<AudioContext | null>(null);
  const processorRef       = useRef<ScriptProcessorNode | null>(null);
  const analyserRef        = useRef<AnalyserNode | null>(null);
  const streamRef          = useRef<MediaStream | null>(null);
  const rafRef             = useRef(0);
  const enabledRef         = useRef(false);

  // micMutedRef — true while MARK is speaking; stops PCM frames from being sent.
  // Updated synchronously via Zustand subscribe (below), never via useEffect.
  const micMutedRef        = useRef(false);

  const pendingMsgRef      = useRef<string | null>(null);
  const isRunningRef       = useRef(false);
  const reconnectTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef  = useRef(1000);

  // Mirror zustand scalars into refs so closures stay current without stale captures
  const isRunning = useMarkStore(s => s.running);
  useEffect(() => { isRunningRef.current = isRunning; }, [isRunning]);

  // ── Synchronous mic-mute tracking ────────────────────────────────────────
  // Zustand subscribe fires in the same tick as the store change — no render
  // cycle delay.  This means micMutedRef flips the moment isMarkSpeaking
  // changes, so the VERY NEXT onaudioprocess invocation (~85ms later) already
  // sees the correct value.
  useEffect(() => {
    return useMarkStore.subscribe(
      (state) => state.isMarkSpeaking,
      (speaking) => {
        micMutedRef.current = speaking;

        if (wsRef.current?.readyState === WebSocket.OPEN) {
          if (speaking) {
            // Secondary/safety-net mute signal to the server.
            // The primary mute already happened inside speech_runtime before
            // the first audio byte — this is belt-and-suspenders.
            wsRef.current.send(JSON.stringify({ type: 'tts_start' }));
          } else {
            // Secondary unmute signal.  Server's VoiceSession already started
            // its 900ms sample-accurate holdoff via speech_runtime.unmute_active_session().
            // This is belt-and-suspenders.
            wsRef.current.send(JSON.stringify({ type: 'tts_end' }));
          }
        }
      },
    );
  }, []);

  // Keep the exposed `isMarkSpeaking` prop in sync too (used by return value)
  // via the normal useEffect path — rendering doesn't need sub-tick accuracy.
  useEffect(() => { micMutedRef.current = isMarkSpeaking; }, [isMarkSpeaking]);

  // ── Mic level polling ─────────────────────────────────────────────────────
  const pollLevel = useCallback(() => {
    const analyser = analyserRef.current;
    if (analyser) {
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      setMicLevel(Math.min(1, avg / 90));
    }
    rafRef.current = requestAnimationFrame(pollLevel);
  }, []);

  // ── Build the WebSocket URL ───────────────────────────────────────────────
  const buildWsUrl = useCallback(() => {
    const wsBase = serverUrl
      .replace(/^http/, 'ws')
      .replace(/\/$/, '');
    const qs = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
    return `${wsBase}/ws/voice${qs}`;
  }, [serverUrl, workspace]);

  // ── Stop mic capture + close audio graph ─────────────────────────────────
  const stopMic = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    processorRef.current?.disconnect();
    analyserRef.current?.disconnect();
    processorRef.current = null;
    analyserRef.current  = null;
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      void audioCtxRef.current.close();
    }
    audioCtxRef.current = null;
    setMicLevel(0);
    setIsListening(false);
  }, []);

  // ── WebSocket voice connection ─────────────────────────────────────────────
  const connectVoiceSocket = useCallback(() => {
    if (!enabledRef.current) return;

    const url = buildWsUrl();
    const ws  = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = async () => {
      if (!enabledRef.current) { ws.close(); return; }
      reconnectDelayRef.current = 1000;   // reset backoff on successful open

      // Acquire mic
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation:   true,
            noiseSuppression:   true,
            autoGainControl:    true,
            // Hint to Chrome's AEC that this is a voice call (not music capture).
            // Makes browser AEC more aggressive about suppressing speaker echo.
            googEchoCancellation:      true,
            googNoiseSuppression:      true,
            googAutoGainControl:       true,
            googHighpassFilter:        true,
            googTypingNoiseDetection:  true,
          } as MediaTrackConstraints,
        });
      } catch (err) {
        console.warn('[MARK voice] mic unavailable:', err);
        setIsListening(false);
        ws.close();
        return;
      }
      streamRef.current = stream;

      // Audio graph: source → analyser → processor → silence sink
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source    = ctx.createMediaStreamSource(stream);
      const analyser  = ctx.createAnalyser();
      analyser.fftSize = 256;
      // 4096-sample buffer = ~85ms at 48kHz — fine granularity for voice
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const srcRate   = ctx.sampleRate;

      processor.onaudioprocess = (ev: AudioProcessingEvent) => {
        // ── Client-side mic gate ─────────────────────────────────────────
        // Stop sending PCM while MARK is speaking.  This is a secondary echo
        // cancellation layer — the server's proactive mute is the primary one.
        // micMutedRef is updated synchronously via Zustand subscribe above.
        if (micMutedRef.current) return;
        if (ws.readyState !== WebSocket.OPEN) return;

        const pcm16k = resampleTo16k(ev.inputBuffer.getChannelData(0), srcRate);
        ws.send(floatTo16BitPCM(pcm16k));
      };

      source.connect(analyser);
      analyser.connect(processor);
      // Processor must be connected to destination to fire onaudioprocess
      processor.connect(ctx.destination);

      analyserRef.current  = analyser;
      processorRef.current = processor;
      rafRef.current       = requestAnimationFrame(pollLevel);

      setIsListening(true);
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data !== 'string') return;  // audio on /ws, not here
      let msg: { type: string; text?: string };
      try {
        msg = JSON.parse(ev.data as string) as { type: string; text?: string };
      } catch {
        return;
      }

      switch (msg.type) {
        case 'speech_start':
          // User started speaking (or barged in) — stop MARK's audio NOW.
          // The server's VAD fired this; the mic gate will open automatically
          // via the isMarkSpeaking → false path in the Zustand subscribe above.
          stopMarkSpeech();
          setInterimTranscript('');
          break;

        case 'partial':
          setInterimTranscript(msg.text ?? '');
          break;

        case 'final':
          setInterimTranscript('');
          if (msg.text) {
            if (isRunningRef.current) {
              // MARK is running a task — queue; flush when run completes.
              pendingMsgRef.current = msg.text;
            } else {
              // Fast path: POST /voice/message → direct LLM → TTS
              void sendVoiceMessage(msg.text, workspace);
            }
          }
          break;
      }
    };

    ws.onclose = () => {
      stopMic();
      if (!enabledRef.current) return;
      // Exponential back-off reconnect (cap at 30s)
      const delay = reconnectDelayRef.current;
      reconnectDelayRef.current = Math.min(delay * 2, 30_000);
      console.log(`[MARK voice] reconnecting in ${delay}ms`);
      reconnectTimerRef.current = setTimeout(() => {
        if (enabledRef.current) connectVoiceSocket();
      }, delay);
    };

    ws.onerror = () => {
      // onclose fires next; reconnect handled there
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildWsUrl, pollLevel, sendVoiceMessage, stopMarkSpeech, stopMic, workspace]);

  // ── Disconnect voice ──────────────────────────────────────────────────────
  const disconnectVoice = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    stopMic();
    setInterimTranscript('');
  }, [stopMic]);

  // ── Toggle voice on/off ────────────────────────────────────────────────────
  const toggleVoice = useCallback(() => {
    setVoiceEnabled(v => {
      const next = !v;
      enabledRef.current = next;
      if (next) {
        connectVoiceSocket();
      } else {
        disconnectVoice();
        stopMarkSpeech();
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      }
      return next;
    });
  }, [connectVoiceSocket, disconnectVoice, stopMarkSpeech]);

  // ── Flush queued message when run completes ───────────────────────────────
  useEffect(() => {
    if (!isRunning && pendingMsgRef.current && enabledRef.current) {
      const queued = pendingMsgRef.current;
      pendingMsgRef.current = null;
      void sendVoiceMessage(queued, workspace);
    }
  }, [isRunning, sendVoiceMessage, workspace]);

  // ── Emergency fallback: browser TTS when Kokoro unavailable ──────────────
  const messages       = useMarkStore(s => s.messages);
  const lastFallbackId = useRef<string | null>(null);
  useEffect(() => {
    if (!voiceEnabled || !speechEngineUnavailable || !('speechSynthesis' in window)) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'mark' || last.isActive) return;
    if (last.id === lastFallbackId.current) return;
    const text = last.blocks
      .filter(b => b.type === 'text' || b.type === 'summary')
      .map(b => (b as { text: string }).text)
      .join(' ')
      .trim();
    if (!text) return;
    lastFallbackId.current = last.id;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }, [messages, voiceEnabled, speechEngineUnavailable]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────
  useEffect(() => () => {
    enabledRef.current = false;
    disconnectVoice();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, [disconnectVoice]);

  return {
    supported,
    voiceEnabled,
    isListening,
    isSpeaking:        isMarkSpeaking,
    micLevel,
    interimTranscript,
    toggleVoice,
  };
}
