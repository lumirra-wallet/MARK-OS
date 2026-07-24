import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for Elena — always active from page load.
 *
 * Design principle: Elena is ALWAYS listening, like a phone call that starts
 * the moment you open the tab.  The mic connects automatically on mount
 * (after the browser grants permission).  The toggle button mutes/unmutes
 * rather than enabling/disabling.
 *
 * Audio pipeline
 * ──────────────
 *   Inbound (mic → Elena):
 *     getUserMedia (mono, 48 kHz hint, AEC + NS + AGC on)
 *     → DynamicsCompressorNode (hardware broadcast-style compression)
 *     → AudioWorkletNode (mark-audio-processor.js, audio render thread):
 *         stereo→mono downmix, pre-emphasis y[n]=x[n]−0.97·x[n−1],
 *         4-point cubic Hermite resample to 16 kHz (1024-sample chunks)
 *     → floatTo16BitPCM (main thread — worklet already at 16 kHz)
 *     → binary WebSocket frames → /ws/voice
 *     → VoiceSession (Silero VAD → faster-whisper) on the server
 *   Outbound (Elena → browser):
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
 * Noise cancellation layers (defence in depth)
 * ─────────────────────────────────────────────
 *   1. getUserMedia echoCancellation + noiseSuppression + AGC — browser AEC
 *   2. DynamicsCompressorNode — hardware broadcast compression normalises
 *      speech level and suppresses loud transients before the worklet sees them
 *   3. Worklet pre-emphasis — lifts consonant band (2–8 kHz), suppresses hum
 *   4. Client mic gate (micMutedRef) — stops PCM frames during TTS
 *   5. Server Silero VAD — speech-activity detection rejects non-speech frames
 *   6. Server-proactive mute (speech_runtime → VoiceSession) — VAD hard-off
 *   7. Server POST_SPEECH holdoff (900ms) — no transcripts after TTS
 *   8. Backend RMS normalisation + Whisper no_speech_prob filter
 *
 * Single-connection guarantee
 * ───────────────────────────
 *   The server evicts any existing /ws/voice when a new one connects, so
 *   only one tab sends audio at a time.  The frontend mirrors this: if a
 *   connect is in flight it is aborted before opening a new one.
 */

// ── PCM helpers ─────────────────────────────────────────────────────────────
// Note: resampling to 16 kHz is now handled inside the AudioWorklet on the
// audio render thread (mark-audio-processor.js) using a 4-point cubic Hermite
// interpolator. The main thread only receives already-16 kHz float32 chunks
// and converts them to PCM16 for WebSocket transmission.

function floatTo16BitPCM(floatPCM: Float32Array): ArrayBuffer {
  const buf  = new ArrayBuffer(floatPCM.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < floatPCM.length; i++) {
    const s = Math.max(-1, Math.min(1, floatPCM[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useVoice() {
  const {
    workspace, addSpokenUserMessage, serverUrl,
    isMarkSpeaking, speechEngineUnavailable, stopMarkSpeech,
  } = useMarkStore();

  // voiceEnabled = mic is live and transmitting (not muted by the user).
  // Starts TRUE — MARK always listens from page load.
  const [voiceEnabled,      setVoiceEnabled]     = useState(true);
  const [isListening,       setIsListening]       = useState(false);
  const [micLevel,          setMicLevel]          = useState(0);
  const [interimTranscript, setInterimTranscript] = useState('');
  const [isThinking,        setIsThinking]        = useState(false);
  const [supported] = useState(() =>
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioContext !== 'undefined',
  );

  // ── Refs (stable across renders, no re-render cost) ──────────────────────
  const wsRef              = useRef<WebSocket | null>(null);
  const audioCtxRef        = useRef<AudioContext | null>(null);
  const processorRef       = useRef<AudioWorkletNode | null>(null);
  const analyserRef        = useRef<AnalyserNode | null>(null);
  const streamRef          = useRef<MediaStream | null>(null);
  const rafRef             = useRef(0);

  // enabledRef — mirrors voiceEnabled in a ref so closures stay current.
  // Starts TRUE to match the initial useState(true).
  const enabledRef         = useRef(true);

  // micMutedRef — true while MARK is speaking; stops PCM frames being sent.
  // Updated synchronously via Zustand subscribe (below), never via useEffect.
  const micMutedRef        = useRef(false);

  const pendingMsgRef      = useRef<string | null>(null);
  const isRunningRef       = useRef(false);
  const reconnectTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef  = useRef(1000);
  const heartbeatRef       = useRef<ReturnType<typeof setInterval> | null>(null);

  // autoStartedRef — ensures we only auto-connect once on mount, even if
  // connectVoiceSocket identity changes (e.g. workspace change).
  const autoStartedRef     = useRef(false);

  // ── Utterance accumulator (frontend safety net) ───────────────────────────
  // The server already stitches fragments with a 2-second window, but if the
  // server fires multiple rapid "final" events (edge case), the frontend
  // debounce here ensures they collapse into one LLM call.
  // accumulatedRef  — transcript text collected since last send
  // stitchTimerRef  — 1.5 s debounce timer; fires the actual sendVoiceMessage
  const accumulatedRef  = useRef<string>('');
  const stitchTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Mirror zustand scalars into refs so closures stay current without stale captures
  const isRunning = useMarkStore(s => s.running);
  useEffect(() => { isRunningRef.current = isRunning; }, [isRunning]);

  // ── Synchronous mic-mute tracking ────────────────────────────────────────
  // Zustand subscribe fires in the same tick as the store change — no render
  // cycle delay.  This means micMutedRef flips the moment isMarkSpeaking
  // changes, so the VERY NEXT onaudioprocess invocation (~85ms later) already
  // sees the correct value.
  useEffect(() => {
    return useMarkStore.subscribe((state, prevState) => {
      const speaking = state.isMarkSpeaking;
      if (speaking === prevState.isMarkSpeaking) return;

      micMutedRef.current = speaking;

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        if (speaking) {
          // Secondary/safety-net mute signal to the server.
          wsRef.current.send(JSON.stringify({ type: 'tts_start' }));
        } else {
          // Secondary unmute signal.
          wsRef.current.send(JSON.stringify({ type: 'tts_end' }));
        }
      }
    });
  }, []);

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

  // ── WebSocket voice connection ──────────────────────────────────────────
  const connectVoiceSocket = useCallback(() => {
    // Only connect when enabled (not muted by user).
    if (!enabledRef.current) return;
    // Don't stack connections — if one is already open or connecting, bail.
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) return;

    const url = buildWsUrl();
    const ws  = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = async () => {
      if (!enabledRef.current) { ws.close(); return; }
      reconnectDelayRef.current = 1000;   // reset backoff on successful open
      // Clear any transcript that was queued before the reconnect.
      pendingMsgRef.current = null;
      accumulatedRef.current = '';

      // ── Heartbeat ping every 15 s ─────────────────────────────────────
      // Keeps the /ws/voice WebSocket alive through proxy idle-connection
      // timeouts (Nginx default: 60 s; Replit proxy: ~30 s).  Without this,
      // silences longer than ~30 s caused a silent disconnect — MARK stopped
      // hearing the user until the next onaudioprocess frame triggered a
      // reconnect, adding a full reconnect round-trip of latency.
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 15_000);

      // ── Acquire mic ────────────────────────────────────────────────────
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            // ── Channel / rate hints ────────────────────────────────────
            // Mono eliminates stereo phase cancellation on mics that have
            // left/right slight timing differences. The worklet downmixes
            // anyway, but constraining to mono at the source reduces the
            // codec/processing work the OS does before we ever see data.
            channelCount:             1,
            sampleRate:               48000, // hint — browser may ignore but
            //                               // most modern hardware honours it
            // ── Browser-native AEC / NS / AGC ───────────────────────────
            echoCancellation:         true,
            noiseSuppression:         true,
            autoGainControl:          true,
            // Chrome / Chromium extended constraints for voice-call quality
            googEchoCancellation:     true,
            googNoiseSuppression:     true,
            googHighpassFilter:       true,    // 80 Hz DC / hum removal
            googTypingNoiseDetection: true,
            googAudioMirroring:       false,   // no feedback-mirror artefacts
          } as MediaTrackConstraints,
        });
      } catch (err) {
        console.warn('[MARK voice] mic unavailable:', err);
        setIsListening(false);
        // Mic denied / unavailable (permission not yet granted, or a
        // non-secure origin like a LAN IP). Back off to 10 s before retrying
        // so we don't reconnect-storm every second while waiting for the user
        // to grant the microphone. A successful open later resets this to 1 s.
        reconnectDelayRef.current = 10_000;
        ws.close();
        return;
      }
      streamRef.current = stream;

      // ── Audio graph: source → analyser → worklet → silence sink ─────────
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source   = ctx.createMediaStreamSource(stream);

      // ── DynamicsCompressorNode — broadcast-style compression ─────────────
      // Normalises speech level before the worklet sees it: quiet voices are
      // lifted, loud transients are tamed. Parameters match a standard voice
      // broadcast chain: soft knee, fast attack to catch consonants, slow
      // release to avoid pumping on sustained vowels.
      const compressor = ctx.createDynamicsCompressor();
      compressor.threshold.value = -24;   // dBFS — start compressing here
      compressor.knee.value       = 10;   // soft knee width in dB
      compressor.ratio.value      = 4;    // 4:1 ratio — voice standard
      compressor.attack.value     = 0.003; // 3 ms — catches hard consonants
      compressor.release.value    = 0.15;  // 150 ms — avoids pumping

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;

      // Load the AudioWorklet processor from the public folder.
      // import.meta.env.BASE_URL resolves to e.g. "/mark-dashboard/" so the
      // full URL is "/mark-dashboard/mark-audio-processor.js" — correct under
      // Vite's configured base path.
      // AudioWorkletNode replaces the deprecated ScriptProcessorNode: it runs
      // on the dedicated audio render thread (no main-thread jitter) and uses
      // zero-copy ArrayBuffer transfer for the PCM chunks.
      await ctx.audioWorklet.addModule(
        `${import.meta.env.BASE_URL}mark-audio-processor.js`,
      );
      const processor = new AudioWorkletNode(ctx, 'mark-audio-processor');

      // ── Energy gate state ─────────────────────────────────────────────
      // Only transmit audio when there is actual signal (plus a hangover
      // window). Without this the mic streamed raw silence 24/7, which:
      // (a) kept the server's VAD busy around the clock (real CPU),
      // (b) held conversation ownership forever, so a newer tab could
      //     never take over, and
      // (c) wasted bandwidth. The threshold is far below speech level;
      //     the hangover keeps VAD context around soft speech onsets.
      let gateOpenUntil = 0;

      // The worklet transfers a 4096-sample Float32Array chunk (~85 ms at
      // 48 kHz) via its MessagePort.  Energy gating and WebSocket dispatch
      // stay on the main thread so they can read micMutedRef without any
      // cross-thread messaging overhead.
      processor.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
        // ── Client-side mic gate ──────────────────────────────────────
        // Stop sending PCM while MARK is speaking OR while the user has
        // muted (enabledRef = false).  Secondary echo-cancellation layer;
        // the server's proactive mute is the primary.
        if (micMutedRef.current) return;
        if (!enabledRef.current) return;
        if (ws.readyState !== WebSocket.OPEN) return;

        // The AudioWorklet already outputs 16 kHz float32 chunks — no
        // main-thread resampling needed. Just gate on energy and send.
        const raw = new Float32Array(ev.data);
        // RMS energy of this 64 ms block (1024 samples @ 16 kHz)
        let sum = 0;
        for (let i = 0; i < raw.length; i += 4) sum += raw[i] * raw[i];
        const rms = Math.sqrt(sum / (raw.length / 4));
        const now = performance.now();
        // Hangover must exceed the server's VAD end-of-speech window (0.8 s)
        // PLUS its LONGEST stitch window (2.8 s for an unfinished-sounding
        // thought), because both tick on RECEIVED samples — the trailing
        // silence we transmit is what lets the server finish the utterance.
        // 4.5 s = 0.8 + 2.8 + margin.
        if (rms > 0.006) gateOpenUntil = now + 4500;
        if (now > gateOpenUntil) return;              // silence → transmit nothing

        ws.send(floatTo16BitPCM(raw));
      };

      // Audio graph: source → compressor → analyser → worklet → silence sink
      // The compressor normalises speech level before the worklet sees it.
      // Analyser sits between compressor and worklet so the mic-level meter
      // reflects the compressed (post-normalisation) signal, not raw spikes.
      source.connect(compressor);
      compressor.connect(analyser);
      analyser.connect(processor);
      // Connect to destination so Chrome's audio graph keeps the worklet
      // alive (AudioWorkletNode.process() returns true to self-sustain, but
      // an unconnected output graph can still be garbage-collected in some
      // versions).  The worklet outputs silence so there is no audible effect.
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
          stopMarkSpeech();
          setInterimTranscript('');
          setIsThinking(false);
          // Cancel any pending stitch debounce — user is still talking.
          if (stitchTimerRef.current) {
            clearTimeout(stitchTimerRef.current);
            stitchTimerRef.current = null;
          }
          break;

        case 'thinking':
          // VAD just detected you stopped talking — MARK is now transcribing
          // and about to start thinking.  This fires ~300-800 ms BEFORE the
          // LLM call starts, so there's a visual cue within 100 ms of speech
          // end with zero dead silence.
          setIsThinking(true);
          setInterimTranscript('');
          break;

        case 'partial':
          setInterimTranscript(msg.text ?? '');
          break;

        case 'speculative_final':
          // Complete-sounding thought: server dispatched LLM immediately
          // (no stitch-window wait).  Display it as a user message now.
          setIsThinking(false);
          setInterimTranscript('');
          if (msg.text) addSpokenUserMessage(msg.text, workspace);
          break;

        case 'final':
          setIsThinking(false);
          setInterimTranscript('');
          // Display only. The server dispatched MARK's brain the instant the
          // VAD closed this utterance (see voice_websocket in api.py) — the
          // old final → 1.5 s debounce → POST /voice/message round-trip is
          // gone, and with it its latency and its tab-throttling dropouts.
          if (msg.text) addSpokenUserMessage(msg.text, workspace);
          break;
      }
    };

    ws.onclose = (ev: CloseEvent) => {
      // Clear heartbeat when the connection closes.
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      setIsThinking(false);
      stopMic();
      if (!enabledRef.current) return;
      // Code 4000 = evicted: another tab started streaming mic audio and now
      // owns the conversation. Give it a short pause then try to reclaim —
      // the other tab may have closed. 3 s is enough to avoid a ping-pong
      // without a noticeable hole in presence.
      if (ev.code === 4000) {
        console.log('[MARK voice] evicted by another tab — reclaiming in 3 s');
        reconnectDelayRef.current = 3_000;
      }
      // Exponential back-off reconnect (cap at 30 s)
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
  }, [buildWsUrl, pollLevel, addSpokenUserMessage, stopMarkSpeech, stopMic, workspace]);

  // ── Fully stop voice (no reconnect) ──────────────────────────────────────
  const disconnectVoice = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (stitchTimerRef.current) {
      clearTimeout(stitchTimerRef.current);
      stitchTimerRef.current = null;
    }
    accumulatedRef.current = '';
    wsRef.current?.close();
    wsRef.current = null;
    stopMic();
    setInterimTranscript('');
  }, [stopMic]);

  // ── Toggle: mute/unmute the mic (voice stays connected to the server) ────
  // When the user clicks "mute", we stop sending PCM frames but keep the WS
  // open so the server session stays warm — no VAD re-init on unmute.
  const toggleVoice = useCallback(() => {
    setVoiceEnabled(v => {
      const next = !v;
      enabledRef.current = next;
      if (next) {
        // Re-open mic if it was closed
        stopMarkSpeech();
        connectVoiceSocket();
      } else {
        // Muted — stop mic capture + clear stitch buffer, keep WS alive
        if (stitchTimerRef.current) {
          clearTimeout(stitchTimerRef.current);
          stitchTimerRef.current = null;
        }
        accumulatedRef.current = '';
        pendingMsgRef.current  = null;
        stopMic();
        stopMarkSpeech();
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      }
      return next;
    });
  }, [connectVoiceSocket, stopMarkSpeech, stopMic]);

  // ── Auto-start on mount ───────────────────────────────────────────────────
  // MARK is always listening from the moment the page loads.  We request mic
  // permission automatically rather than waiting for a manual toggle click.
  useEffect(() => {
    if (autoStartedRef.current || !supported) return;
    autoStartedRef.current = true;
    // enabledRef is already true (default); just kick off the connection.
    connectVoiceSocket();
  // connectVoiceSocket is stable enough for this mount-once effect.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported]);

  // (The old "flush queued message when run completes" effect is gone: the
  // browser no longer owns turn dispatch at all — the server dispatches
  // MARK's brain directly from the VAD 'final', and its own voice-chat lock
  // serialises overlapping turns. Nothing to queue client-side.)

  // ── Emergency fallback: browser TTS when Kokoro unavailable ──────────────
  // IMPORTANT: mute the mic gate before speak() so MARK's browser voice
  // cannot be picked up by the mic and transcribed back to MARK.
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
    const utterance = new SpeechSynthesisUtterance(text);
    // Mute mic before browser TTS starts so the speaker output cannot loop
    // back into the mic → Whisper → /voice/message chain.
    micMutedRef.current = true;
    utterance.onend = () => {
      // Restore mic gate after playback — small extra delay matches the
      // server-side POST_SPEECH holdoff so room reverb settles first.
      setTimeout(() => { micMutedRef.current = false; }, 1200);
    };
    utterance.onerror = () => { micMutedRef.current = false; };
    window.speechSynthesis.speak(utterance);
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
    isThinking,
    micLevel,
    interimTranscript,
    toggleVoice,
  };
}
