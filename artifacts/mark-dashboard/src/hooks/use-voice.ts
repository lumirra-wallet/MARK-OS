import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for MARK — WebSocket + ScriptProcessorNode mic transport.
 *
 * Audio pipeline:
 *   Inbound (mic → MARK):
 *     getUserMedia (native sample rate, AEC on)
 *     → ScriptProcessorNode
 *     → resampleTo16k (linear interpolation)
 *     → floatTo16BitPCM
 *     → binary WebSocket frames → /ws/voice
 *     → VoiceSession (Silero VAD → faster-whisper) on the server
 *   Outbound (MARK → browser):
 *     Kokoro TTS on the server
 *     → binary PCM16 frames on the main /ws connection
 *     → SpeechPlayer (AudioContext) — see markStore.ts
 *
 * Transcript events (text frames over /ws/voice):
 *   server → browser : { type: "speech_start" }       — barge-in detected
 *   server → browser : { type: "partial", text }       — interim transcript
 *   server → browser : { type: "final",   text }       — final transcript
 *   browser → server : { type: "tts_start" }           — mute echo guard
 *   browser → server : { type: "tts_end"   }           — unmute echo guard
 *
 * Voice final transcripts are sent via POST /voice/message (fast path)
 * instead of /execute — the server responds in 1-3 s rather than minutes.
 *
 * Three-layer echo cancellation:
 *   1. getUserMedia echoCancellation + noiseSuppression — browser AEC.
 *   2. Mic gate — ScriptProcessorNode output is zeroed while MARK speaks,
 *      with a 350 ms holdoff for room reverb / AEC settling.
 *   3. Backend VAD threshold (0.65) + Whisper no_speech_prob filter.
 *
 * LiveKit is kept running alongside for real-time session presence and
 * coordination but carries NO audio — the WebSocket pipeline here handles
 * all audio transport.
 *
 * window.speechSynthesis is kept ONLY as the explicit emergency fallback
 * when the backend's real TTS engine couldn't initialise (SpeechEngineUnavailable).
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
  const isMarkSpeakingRef  = useRef(false);
  const holdoffTimerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingMsgRef      = useRef<string | null>(null);
  const isRunningRef       = useRef(false);
  const reconnectTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef  = useRef(1000);

  // Mirror zustand scalars into refs so closures stay current without stale captures
  const isRunning = useMarkStore(s => s.running);
  useEffect(() => { isRunningRef.current = isRunning; }, [isRunning]);
  useEffect(() => { isMarkSpeakingRef.current = isMarkSpeaking; }, [isMarkSpeaking]);

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
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (err) {
        console.warn('[MARK voice] mic unavailable:', err);
        setIsListening(false);
        ws.close();
        return;
      }
      streamRef.current = stream;

      // Audio graph: source → analyser → processor → silence
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source   = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const srcRate   = ctx.sampleRate;

      processor.onaudioprocess = (ev: AudioProcessingEvent) => {
        // Gate: zero out mic while MARK is speaking (echo cancellation layer 2)
        if (isMarkSpeakingRef.current) return;
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
      if (typeof ev.data !== 'string') return;  // audio comes on /ws, not here
      try {
        const msg = JSON.parse(ev.data as string) as { type: string; text?: string };
        if (msg.type === 'speech_start') {
          // User started speaking — stop MARK's audio immediately
          stopMarkSpeech();
        } else if (msg.type === 'partial') {
          setInterimTranscript(msg.text ?? '');
        } else if (msg.type === 'final') {
          setInterimTranscript('');
          if (msg.text) {
            if (isRunningRef.current) {
              // MARK is still running (rare race after interrupt); queue it.
              pendingMsgRef.current = msg.text;
            } else {
              // Fast path: POST /voice/message → direct LLM → TTS
              void sendVoiceMessage(msg.text, workspace);
            }
          }
        }
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = () => {
      stopMic();
      if (!enabledRef.current) return;
      // Exponential back-off reconnect (cap at 30 s)
      const delay = reconnectDelayRef.current;
      reconnectDelayRef.current = Math.min(delay * 2, 30_000);
      console.log(`[MARK voice] reconnecting in ${delay} ms`);
      reconnectTimerRef.current = setTimeout(() => {
        if (enabledRef.current) connectVoiceSocket();
      }, delay);
    };

    ws.onerror = (ev) => {
      console.warn('[MARK voice] WebSocket error:', ev);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildWsUrl, pollLevel, sendVoiceMessage, stopMarkSpeech, stopMic, workspace]);

  // ── Echo gate: pause mic while MARK is speaking ───────────────────────────
  // Zustand subscribe() is synchronous — no render-cycle delay.
  useEffect(() => {
    return useMarkStore.subscribe((state, prev) => {
      if (state.isMarkSpeaking === prev.isMarkSpeaking) return;

      if (holdoffTimerRef.current) {
        clearTimeout(holdoffTimerRef.current);
        holdoffTimerRef.current = null;
      }

      if (state.isMarkSpeaking) {
        // MARK started speaking — send tts_start so server mutes VAD
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'tts_start' }));
        }
      } else {
        // 350 ms holdoff — room reverb + AEC settling
        holdoffTimerRef.current = setTimeout(() => {
          holdoffTimerRef.current = null;
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'tts_end' }));
          }
        }, 350);
      }
    });
  }, []);

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

  // ── Flush queued message when run completes ──────────────────────────────
  useEffect(() => {
    if (!isRunning && pendingMsgRef.current && enabledRef.current) {
      const queued = pendingMsgRef.current;
      pendingMsgRef.current = null;
      void sendVoiceMessage(queued, workspace);
    }
  }, [isRunning, sendVoiceMessage, workspace]);

  // ── Emergency fallback: browser TTS when Kokoro unavailable ──────────────
  // Only activates on a real SpeechEngineUnavailable event — never the primary path.
  const messages        = useMarkStore(s => s.messages);
  const lastFallbackId  = useRef<string | null>(null);
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
    isSpeaking: isMarkSpeaking,
    micLevel,
    interimTranscript,
    toggleVoice,
  };
}
