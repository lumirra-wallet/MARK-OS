import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for MARK — LiveKit WebRTC transport.
 *
 * Replaces the previous WebSocket + ScriptProcessorNode approach with a
 * LiveKit Room, which gives us:
 *
 *   • Tab-background resilience: WebRTC audio tracks keep playing and
 *     publishing even when the tab is hidden (ScriptProcessorNode stops).
 *   • Automatic reconnection: the LiveKit SDK handles network drops without
 *     any manual backoff code.
 *   • Proper echo cancellation: the browser's native AEC runs at hardware
 *     sample rate (not forced 16kHz) and LiveKit publishes the track
 *     natively — no manual resampling needed.
 *   • Clean mute gate: `localTrack.mute()` stops audio from being encoded
 *     and published rather than filtering PCM frames in JavaScript.
 *
 * Echo cancellation (three layers, same as before):
 *   1. getUserMedia echoCancellation + noiseSuppression — browser AEC.
 *   2. Mic mute gate — localTrack.mute() while MARK is speaking,
 *      with 350ms holdoff for room reverb / AEC settling.
 *   3. Backend VAD threshold (0.65) + Whisper no_speech_prob filter.
 *
 * Audio transport:
 *   Inbound (mic → MARK): browser publishes a LocalAudioTrack to the
 *     LiveKit room; MARK's backend agent subscribes and feeds frames to
 *     VoiceSession (VAD+STT) unchanged.
 *   Outbound (MARK → browser): MARK's backend publishes a RemoteAudioTrack
 *     (Kokoro TTS PCM at 24 kHz); the LiveKit SDK attaches it to an
 *     <audio> element and plays it natively.
 *
 * Control messages travel as LiveKit data channel packets (reliable):
 *   backend  → browser : { type: "speech_start" }  — barge-in detected
 *   backend  → browser : { type: "partial", text }  — interim transcript
 *   backend  → browser : { type: "final",   text }  — final transcript
 *   browser  → backend : { type: "tts_start" }      — mute echo guard
 *   browser  → backend : { type: "tts_end"   }      — unmute echo guard
 *
 * window.speechSynthesis is kept ONLY as the explicit emergency fallback
 * when the backend's real TTS engine couldn't initialise (SpeechEngineUnavailable).
 */

import {
  Room,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  type LocalAudioTrack,
  type RemoteAudioTrack,
  type RemoteTrack,
} from 'livekit-client';

export function useVoice() {
  const {
    workspace, sendUserMessage, serverUrl,
    isMarkSpeaking, speechEngineUnavailable, stopMarkSpeech,
  } = useMarkStore();

  const [voiceEnabled,       setVoiceEnabled]       = useState(false);
  const [isListening,        setIsListening]         = useState(false);
  const [micLevel,           setMicLevel]            = useState(0);
  const [interimTranscript,  setInterimTranscript]   = useState('');
  const [supported] = useState(() =>
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof RTCPeerConnection !== 'undefined'
  );

  const roomRef             = useRef<Room | null>(null);
  const localTrackRef       = useRef<LocalAudioTrack | null>(null);
  const audioCtxRef         = useRef<AudioContext | null>(null);
  const analyserRef         = useRef<AnalyserNode | null>(null);
  const rafRef              = useRef(0);
  const enabledRef          = useRef(false);
  const pendingMsgRef       = useRef<string | null>(null);
  const isRunningRef        = useRef(false);
  const markAudioEls        = useRef<HTMLAudioElement[]>([]);
  const speakingHoldoffRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isRunning = useMarkStore(s => s.running);
  useEffect(() => { isRunningRef.current = isRunning; }, [isRunning]);

  // ── Data channel sender (fire-and-forget) ────────────────────────────────
  const sendData = useCallback((msg: object) => {
    const room = roomRef.current;
    if (!room || room.state !== 'connected') return;
    try {
      room.localParticipant.publishData(
        new TextEncoder().encode(JSON.stringify(msg)),
        { reliable: true },
      );
    } catch { /* room disconnected, ignore */ }
  }, []);

  // ── Echo gate: mute local track while MARK is speaking ──────────────────
  // Zustand subscribe() fires synchronously — no render-cycle delay.
  useEffect(() => {
    return useMarkStore.subscribe((state, prev) => {
      if (state.isMarkSpeaking === prev.isMarkSpeaking) return;

      if (speakingHoldoffRef.current) {
        clearTimeout(speakingHoldoffRef.current);
        speakingHoldoffRef.current = null;
      }

      if (state.isMarkSpeaking) {
        localTrackRef.current?.mute();
        sendData({ type: 'tts_start' });
      } else {
        // 350 ms holdoff — room reverb + AEC settling time
        speakingHoldoffRef.current = setTimeout(() => {
          speakingHoldoffRef.current = null;
          localTrackRef.current?.unmute();
          sendData({ type: 'tts_end' });
        }, 350);
      }
    });
  }, [sendData]);

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

  // ── Fetch LiveKit token + config ──────────────────────────────────────────
  const fetchLiveKitSetup = async (): Promise<{ url: string; room: string; token: string }> => {
    const base = serverUrl.replace(/\/$/, '');
    const [cfgRes, tokRes] = await Promise.all([
      fetch(`${base}/voice/config`),
      fetch(`${base}/voice/token?role=browser`),
    ]);
    if (!cfgRes.ok) throw new Error(`/voice/config → ${cfgRes.status}`);
    if (!tokRes.ok) throw new Error(`/voice/token  → ${tokRes.status}`);
    const [cfg, tok] = await Promise.all([cfgRes.json(), tokRes.json()]);
    if (!cfg.available) throw new Error('LiveKit not configured on the server');
    return { url: cfg.url, room: cfg.room, token: tok.token };
  };

  // ── Connect to LiveKit room ───────────────────────────────────────────────
  const connectLiveKit = useCallback(async () => {
    if (!enabledRef.current) return;

    let setup: { url: string; room: string; token: string };
    try {
      setup = await fetchLiveKitSetup();
    } catch (err) {
      console.warn('[MARK voice] config fetch failed:', err);
      setIsListening(false);
      return;
    }

    const room = new Room({
      audioCaptureDefaults: {
        echoCancellation: true,
        noiseSuppression:  true,
        autoGainControl:   true,
      },
      adaptiveStream: true,
      dynacast:       true,
    });
    roomRef.current = room;

    // ── Data channel: transcripts + interruption ───────────────────────────
    room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === 'speech_start') {
          // Fastest path — direct call, no network round-trip.
          stopMarkSpeech();
        } else if (msg.type === 'partial') {
          setInterimTranscript(msg.text ?? '');
        } else if (msg.type === 'final') {
          setInterimTranscript('');
          if (msg.text) {
            if (isRunningRef.current) {
              // MARK is still processing; queue until run completes.
              pendingMsgRef.current = msg.text;
            } else {
              sendUserMessage(msg.text, workspace);
            }
          }
        }
      } catch { /* ignore malformed packet */ }
    });

    // ── MARK's TTS audio track ─────────────────────────────────────────────
    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        const el = (track as RemoteAudioTrack).attach();
        el.setAttribute('playsinline', '');
        el.setAttribute('autoplay', 'true');
        document.body.appendChild(el);
        void el.play().catch(() => {});
        markAudioEls.current.push(el);
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        (track as RemoteAudioTrack).detach().forEach(el => {
          el.remove();
          markAudioEls.current = markAudioEls.current.filter(e => e !== el);
        });
      }
    });

    room.on(RoomEvent.Reconnected, () =>
      console.log('[MARK voice] reconnected to LiveKit room')
    );

    // ── Connect ────────────────────────────────────────────────────────────
    try {
      await room.connect(setup.url, setup.token);
    } catch (err) {
      console.warn('[MARK voice] room.connect failed:', err);
      setIsListening(false);
      return;
    }

    // ── Publish mic track ──────────────────────────────────────────────────
    let localTrack: LocalAudioTrack;
    try {
      localTrack = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression:  true,
        autoGainControl:   true,
      });
    } catch (err) {
      console.warn('[MARK voice] microphone unavailable:', err);
      setIsListening(false);
      return;
    }
    localTrackRef.current = localTrack;
    await room.localParticipant.publishTrack(localTrack);

    // ── Mic level analyser ─────────────────────────────────────────────────
    // Attach AnalyserNode to the local track's raw MediaStream.
    // Running AudioContext at the native hardware rate (not forced to 16kHz)
    // preserves the browser's AEC pipeline — same constraint as before.
    const stream = new MediaStream([localTrack.mediaStreamTrack]);
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyserRef.current = analyser;
    rafRef.current = requestAnimationFrame(pollLevel);

    setIsListening(true);
    console.log('[MARK voice] connected to LiveKit room:', setup.room);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverUrl, pollLevel, sendUserMessage, stopMarkSpeech, workspace]);

  // ── Disconnect from LiveKit room ──────────────────────────────────────────
  const disconnectLiveKit = useCallback(async () => {
    cancelAnimationFrame(rafRef.current);
    analyserRef.current = null;

    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      void audioCtxRef.current.close();
    }
    audioCtxRef.current = null;

    const room = roomRef.current;
    roomRef.current = null;
    if (room) {
      try { await room.disconnect(); } catch { /* ignore */ }
    }

    localTrackRef.current = null;
    markAudioEls.current.forEach(el => el.remove());
    markAudioEls.current = [];

    setMicLevel(0);
    setIsListening(false);
    setInterimTranscript('');
  }, []);

  // ── Toggle voice on/off ────────────────────────────────────────────────────
  const toggleVoice = useCallback(() => {
    setVoiceEnabled(v => {
      const next = !v;
      enabledRef.current = next;
      if (next) {
        void connectLiveKit();
      } else {
        void disconnectLiveKit();
        stopMarkSpeech();
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      }
      return next;
    });
  }, [connectLiveKit, disconnectLiveKit, stopMarkSpeech]);

  // ── Flush pending message when run completes ────────────────────────────
  useEffect(() => {
    if (!isRunning && pendingMsgRef.current && enabledRef.current) {
      const queued = pendingMsgRef.current;
      pendingMsgRef.current = null;
      sendUserMessage(queued, workspace);
    }
  }, [isRunning, sendUserMessage, workspace]);

  // ── Emergency fallback: browser TTS when Kokoro unavailable ─────────────
  // Only activates on a real SpeechEngineUnavailable event — never the primary path.
  const messages = useMarkStore(s => s.messages);
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
    void disconnectLiveKit();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, [disconnectLiveKit]);

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
