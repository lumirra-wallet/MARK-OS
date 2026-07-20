import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for MARK — backend-owned, not a frontend feature.
 *
 * Input:  the browser streams raw mic PCM16 (resampled to 16kHz) to the
 *         backend's /ws/voice, which runs it through a real local Silero
 *         VAD + Faster-Whisper pipeline (smartagent/server/voice_pipeline.py)
 *         and sends back {type:"speech_start"}, {type:"partial",text},
 *         {type:"final",text}. No browser SpeechRecognition — transcription
 *         happens in MARK's own runtime.
 * Output: MARK's replies are spoken by a real local Kokoro TTS engine in
 *         the backend (smartagent/server/{tts_engine,speech_runtime}.py),
 *         streamed as binary audio frames over the main /ws connection and
 *         played by markStore's SpeechPlayer (see lib/speechPlayer.ts). No
 *         browser speechSynthesis on this path.
 *
 * Echo cancellation approach (three layers):
 *   1. getUserMedia echoCancellation + noiseSuppression — browser AEC.
 *      Works best when AudioContext is at the native hardware rate (NOT at
 *      a forced 16kHz — that bypasses the browser's AEC pipeline).
 *   2. Mic gate — while MARK is speaking, PCM frames are only forwarded to
 *      the backend when the RMS amplitude crosses a barge-in threshold
 *      (BARGE_IN_RMS). This stops MARK's own voice (replayed through
 *      speakers) from reaching the VAD as a false speech event, at zero
 *      cost to intentional interruption — a real barge-in is louder.
 *   3. Backend VAD threshold (0.65) + Whisper no_speech_prob filter —
 *      see smartagent/server/voice_pipeline.py.
 *
 * The instant /ws/voice reports speech_start, this hook calls
 * stopMarkSpeech() directly — that's the fast path, a local call with no
 * network round trip. The backend also learns about the same interruption
 * (voice_websocket calls speech_runtime.interrupt()) and confirms it via a
 * SpeechInterrupted event on the main socket, which markStore handles too;
 * this hook's direct call just doesn't wait for that confirmation.
 *
 * window.speechSynthesis is kept ONLY as the explicit emergency fallback
 * for when the backend's real TTS engine couldn't initialize at all (see
 * speechEngineUnavailable in markStore, set from a real
 * SpeechEngineUnavailable event) — never used on the primary path.
 *
 * Opt-in by design, not auto-started: browsers require a user gesture
 * before granting microphone access, and starting to listen without one
 * being asked for would be a real consent violation even if it weren't
 * also technically blocked.
 */

const VOICE_SAMPLE_RATE = 16000; // must match smartagent/server/voice_pipeline.py's SAMPLE_RATE
const PROCESSOR_BUFFER_SIZE = 4096;

// RMS amplitude below which mic frames are suppressed while MARK is speaking.
// A real barge-in attempt (user talking over MARK) will be louder than this;
// MARK's own echo from the speakers will be softer after AEC.
const BARGE_IN_RMS = 0.015;

function resampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate === VOICE_SAMPLE_RATE) return input;
  const ratio = inputRate / VOICE_SAMPLE_RATE;
  const outLength = Math.floor(input.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const srcIdx = i * ratio;
    const lo = Math.floor(srcIdx);
    const hi = Math.min(lo + 1, input.length - 1);
    const frac = srcIdx - lo;
    out[i] = input[lo] * (1 - frac) + input[hi] * frac;
  }
  return out;
}

function floatTo16BitPCM(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

export function useVoice() {
  const { workspace, sendUserMessage, serverUrl, isMarkSpeaking, speechEngineUnavailable, stopMarkSpeech } = useMarkStore();

  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [micLevel, setMicLevel] = useState(0); // 0-1, real amplitude — not decorative
  const [interimTranscript, setInterimTranscript] = useState('');
  const [supported] = useState(() =>
    typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof WebSocket !== 'undefined'
  );

  const voiceWsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);
  const enabledRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceReconnectAttemptsRef = useRef(0);
  // Voice message queued while MARK was mid-run (interrupt scenario).
  // Flushed automatically once the run completes.
  const pendingVoiceMessageRef = useRef<string | null>(null);
  // Ref-copy of isRunning so the onmessage closure (captured once) can
  // read the live value without stale-closure issues.
  const isRunningRef = useRef(false);
  const isRunning = useMarkStore(s => s.running);
  useEffect(() => { isRunningRef.current = isRunning; }, [isRunning]);

  // ── Mic gate: synchronous isMarkSpeaking tracking ───────────────────────
  // The gate in onaudioprocess reads isMarkSpeakingRef. This MUST update
  // without waiting for a React render cycle — a useEffect sync introduces
  // a 50-100ms lag during which MARK's own TTS audio leaks to the backend
  // as a false mic signal.  Zustand's subscribe() fires synchronously on
  // state change (same tick), eliminating the render-cycle delay.
  //
  // Post-speech holdoff: keep the gate active for 350ms after MARK finishes
  // speaking so that room reverb and AEC settling don't trigger a false VAD.
  const isMarkSpeakingRef = useRef(false);
  const speakingHoldoffRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return useMarkStore.subscribe((state, prev) => {
      if (state.isMarkSpeaking === prev.isMarkSpeaking) return;

      // Clear any in-flight holdoff timer
      if (speakingHoldoffRef.current) {
        clearTimeout(speakingHoldoffRef.current);
        speakingHoldoffRef.current = null;
      }

      if (state.isMarkSpeaking) {
        // Gate the mic immediately — no render delay
        isMarkSpeakingRef.current = true;
        // Tell the backend to activate its echo guard
        const ws = voiceWsRef.current;
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'tts_start' }));
        }
      } else {
        // Keep gate + backend mute active during the reverb/AEC tail,
        // then open up after 350ms.
        speakingHoldoffRef.current = setTimeout(() => {
          isMarkSpeakingRef.current = false;
          speakingHoldoffRef.current = null;
          const ws = voiceWsRef.current;
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'tts_end' }));
          }
        }, 350);
      }
    });
  }, []);  // subscribe once — voiceWsRef is a ref, not a dep

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

  const teardownAudio = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    processorRef.current?.disconnect();
    processorRef.current = null;
    analyserRef.current = null;
    micStreamRef.current?.getTracks().forEach(t => t.stop());
    micStreamRef.current = null;
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      void audioCtxRef.current.close();
    }
    audioCtxRef.current = null;
    setMicLevel(0);
    setIsListening(false);
  }, []);

  const stopVoiceConnection = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
    voiceWsRef.current?.close();
    voiceWsRef.current = null;
    teardownAudio();
  }, [teardownAudio]);

  // ── /ws/voice: real mic streaming + real transcription + interruption ──
  const connectVoiceSocket = useCallback(() => {
    if (!enabledRef.current) return;
    const wsUrl = serverUrl.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws/voice';
    const socket = new WebSocket(wsUrl);
    voiceWsRef.current = socket;

    socket.onopen = async () => {
      voiceReconnectAttemptsRef.current = 0;   // reset backoff on successful connect
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression:  true,
            autoGainControl:   true,
          },
        });
        if (!enabledRef.current) { stream.getTracks().forEach(t => t.stop()); return; }
        micStreamRef.current = stream;

        // ── AudioContext at the native hardware rate ────────────────────────
        // Do NOT force sampleRate: 16000 here. The browser's AEC (echo
        // cancellation) requires the AudioContext to run at the hardware's
        // native rate (typically 44100 or 48000 Hz). Forcing 16kHz bypasses
        // the AEC pipeline even when echoCancellation: true is requested,
        // which is why MARK's own voice was being heard as user speech.
        // The resampleTo16k() call below handles the rate conversion.
        const ctx = new AudioContext();
        audioCtxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);

        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        analyserRef.current = analyser;
        rafRef.current = requestAnimationFrame(pollLevel);

        // ScriptProcessorNode: deprecated but universally supported and
        // sufficient for this — capturing mic audio isn't a hot path, and
        // it avoids the extra build complexity of a separate AudioWorklet
        // module file for a workspace already this large.
        const processor = ctx.createScriptProcessor(PROCESSOR_BUFFER_SIZE, 1, 1);
        processor.onaudioprocess = (e) => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const raw = e.inputBuffer.getChannelData(0);

          // ── Mic gate: suppress echo while MARK is speaking ─────────────
          // While MARK's audio is playing through the speakers, only forward
          // mic frames when the user is louder than the barge-in threshold.
          // This eliminates false VAD triggers from speaker echo without
          // blocking intentional interruption (which is louder than ambient).
          if (isMarkSpeakingRef.current) {
            let sum = 0;
            for (let i = 0; i < raw.length; i++) sum += raw[i] * raw[i];
            const rms = Math.sqrt(sum / raw.length);
            if (rms < BARGE_IN_RMS) return;   // not a real barge-in attempt
          }

          const resampled = resampleTo16k(raw, ctx.sampleRate);
          socket.send(floatTo16BitPCM(resampled));
        };
        source.connect(processor);
        // A ScriptProcessorNode must be connected to a destination to run
        // in some browsers, even though its output is silent/unused here.
        processor.connect(ctx.destination);
        processorRef.current = processor;

        setIsListening(true);
      } catch (err) {
        console.warn('MARK voice: microphone unavailable', err);
        setIsListening(false);
      }
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === 'speech_start') {
          // Fastest possible stop — local call, no round trip. The backend
          // reaches the same conclusion independently (VAD → interrupt()
          // → SpeechInterrupted), this just doesn't wait for it.
          stopMarkSpeech();
        } else if (msg.type === 'partial') {
          setInterimTranscript(msg.text || '');
        } else if (msg.type === 'final') {
          setInterimTranscript('');
          if (msg.text) {
            if (isRunningRef.current) {
              // MARK is still processing (inference was just cancelled by the
              // speech_start interrupt but _state.running hasn't cleared yet).
              // Queue the message — the useEffect below sends it the moment
              // the run completes, so the user's word is never dropped.
              pendingVoiceMessageRef.current = msg.text;
            } else {
              sendUserMessage(msg.text, workspace);
            }
          }
        }
      } catch {
        /* ignore malformed frame */
      }
    };

    socket.onclose = () => {
      teardownAudio();
      if (enabledRef.current) {
        // Exponential backoff: 500ms → 8s ceiling. Fast enough for a brief
        // network blip; backs off for a genuinely dead endpoint without
        // hammering it. Voice never gives up — reconnects until the user
        // explicitly turns the mic off.
        const delay = Math.min(500 * 2 ** voiceReconnectAttemptsRef.current, 8_000);
        voiceReconnectAttemptsRef.current += 1;
        reconnectTimerRef.current = setTimeout(connectVoiceSocket, delay);
      }
    };
    socket.onerror = () => { /* handled by close */ };
  }, [serverUrl, pollLevel, sendUserMessage, stopMarkSpeech, teardownAudio, workspace]);

  // When a run completes and there's a voice message that was queued during
  // the interrupt window, send it now. This is the "never lose a spoken
  // message" guarantee: speech_start cancels MARK's inference, but the
  // final transcript arrives before _state.running has fully cleared —
  // we queue it here and flush the moment the run is done.
  useEffect(() => {
    if (!isRunning && pendingVoiceMessageRef.current && enabledRef.current) {
      const queued = pendingVoiceMessageRef.current;
      pendingVoiceMessageRef.current = null;
      sendUserMessage(queued, workspace);
    }
  }, [isRunning, sendUserMessage, workspace]);

  const toggleVoice = useCallback(() => {
    setVoiceEnabled(v => {
      const next = !v;
      enabledRef.current = next;
      if (next) {
        connectVoiceSocket();
      } else {
        stopVoiceConnection();
        stopMarkSpeech();
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      }
      return next;
    });
  }, [connectVoiceSocket, stopVoiceConnection, stopMarkSpeech]);

  // ── Emergency-only fallback: the real backend engine could not start ──
  // (a genuine SpeechEngineUnavailable event, not a guess). Speaks MARK's
  // finished replies with the browser's own voice so he's never silent,
  // but this is explicitly the last resort the owner asked to keep, not
  // the primary path.
  const messages = useMarkStore(s => s.messages);
  const lastSpokenFallbackId = useRef<string | null>(null);
  useEffect(() => {
    if (!voiceEnabled || !speechEngineUnavailable || !('speechSynthesis' in window)) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'mark' || last.isActive) return;
    if (last.id === lastSpokenFallbackId.current) return;
    const text = last.blocks
      .filter(b => b.type === 'text' || b.type === 'summary')
      .map(b => (b as any).text as string)
      .join(' ')
      .trim();
    if (!text) return;
    lastSpokenFallbackId.current = last.id;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }, [messages, voiceEnabled, speechEngineUnavailable]);

  useEffect(() => () => {
    stopVoiceConnection();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, [stopVoiceConnection]);

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
