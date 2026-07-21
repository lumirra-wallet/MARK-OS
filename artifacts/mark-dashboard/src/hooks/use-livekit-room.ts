/**
 * use-livekit-room.ts
 *
 * LiveKit-native persistent voice hook.
 *
 * MARK is always in the LiveKit room before the browser connects.
 * This hook joins the existing room, publishes the mic as a continuous
 * LocalAudioTrack, and subscribes to MARK's RemoteAudioTrack for playback.
 * Conversation events (speech_start, partial transcript) arrive via the room
 * data channel; the LLM text reply flows over the existing main /ws.
 *
 * Toggle = mute / unmute the local mic track.
 * The room session stays warm; mic audio stops when muted.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Room,
  RoomEvent,
  Track,
  LocalAudioTrack,
  createLocalAudioTrack,
  RoomConnectOptions,
} from 'livekit-client';
import { useMarkStore } from '@/store/markStore';

// ── Types ─────────────────────────────────────────────────────────────────────

interface VoiceConfig {
  url: string;
  room: string;
  mode: string;
  available: boolean;
}

export interface UseLiveKitRoomResult {
  supported: boolean;
  voiceEnabled: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  micLevel: number;
  interimTranscript: string;
  toggleVoice: () => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useLiveKitRoom(): UseLiveKitRoomResult {
  const serverUrl     = useMarkStore(s => s.serverUrl);
  const isMarkSpeaking = useMarkStore(s => s.isMarkSpeaking);
  const stopMarkSpeech = useMarkStore(s => s.stopMarkSpeech);

  const [supported] = useState(() =>
    typeof window !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioContext !== 'undefined',
  );
  const [voiceEnabled,      setVoiceEnabled]     = useState(true);
  const [isListening,       setIsListening]       = useState(false);
  const [micLevel,          setMicLevel]          = useState(0);
  const [interimTranscript, setInterimTranscript] = useState('');

  const roomRef           = useRef<Room | null>(null);
  const localTrackRef     = useRef<LocalAudioTrack | null>(null);
  const audioElRef        = useRef<HTMLAudioElement | null>(null);
  const enabledRef        = useRef(true);
  const connectedRef      = useRef(false);
  const micPollRef        = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch voice config + token ─────────────────────────────────────────────

  const fetchCreds = useCallback(async (): Promise<{
    url: string; token: string;
  } | null> => {
    const base = serverUrl.replace(/\/$/, '');
    try {
      const [cfgRes, tokRes] = await Promise.all([
        fetch(`${base}/voice/config`),
        fetch(`${base}/voice/token`),
      ]);
      if (!cfgRes.ok || !tokRes.ok) return null;
      const cfg: VoiceConfig = await cfgRes.json();
      const tok: { token: string } = await tokRes.json();
      if (!cfg.available || !tok.token) return null;
      return { url: cfg.url, token: tok.token };
    } catch {
      return null;
    }
  }, [serverUrl]);

  // ── Mic level polling ──────────────────────────────────────────────────────

  const startMicPoll = useCallback(() => {
    if (micPollRef.current) return;
    micPollRef.current = setInterval(() => {
      const room = roomRef.current;
      setMicLevel(room ? (room.localParticipant.audioLevel ?? 0) : 0);
    }, 50);
  }, []);

  const stopMicPoll = useCallback(() => {
    if (micPollRef.current) { clearInterval(micPollRef.current); micPollRef.current = null; }
    setMicLevel(0);
  }, []);

  // ── Connect ────────────────────────────────────────────────────────────────

  const connect = useCallback(async () => {
    if (!enabledRef.current || !supported || connectedRef.current) return;

    const creds = await fetchCreds();
    if (!creds) {
      console.warn('[MARK voice] LiveKit not configured on server — voice disabled');
      return;
    }

    let localTrack: LocalAudioTrack;
    try {
      localTrack = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl:  true,
      });
    } catch (err) {
      console.warn('[MARK voice] mic access denied:', err);
      return;
    }
    localTrackRef.current = localTrack;

    const room = new Room({
      adaptiveStream: true,
      dynacast:       true,
    });
    roomRef.current = room;

    // ── Event handlers ───────────────────────────────────────────────────────

    room.on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
      if (track.kind !== Track.Kind.Audio) return;
      const id = participant?.identity ?? '';
      if (!id.startsWith('mark-')) return;
      // Detach previous element, attach new one
      audioElRef.current?.remove();
      const el = track.attach() as HTMLAudioElement;
      el.style.display = 'none';
      document.body.appendChild(el);
      audioElRef.current = el;
      console.log('[MARK voice] subscribed to MARK TTS audio track');
    });

    room.on(RoomEvent.TrackUnsubscribed, (_track, _pub, participant) => {
      if ((participant?.identity ?? '').startsWith('mark-')) {
        audioElRef.current?.remove();
        audioElRef.current = null;
      }
    });

    room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload)) as {
          type: string; text?: string;
        };
        if (msg.type === 'speech_start') {
          stopMarkSpeech();
          setInterimTranscript('');
        } else if (msg.type === 'partial') {
          setInterimTranscript(msg.text ?? '');
        } else if (msg.type === 'final') {
          setInterimTranscript('');
        }
      } catch { /* ignore */ }
    });

    room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (!room.canPlaybackAudio) room.startAudio().catch(() => {});
    });

    room.on(RoomEvent.Disconnected, () => {
      connectedRef.current = false;
      setIsListening(false);
      stopMicPoll();
      if (enabledRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          if (enabledRef.current) void connect();
        }, 3000);
      }
    });

    // ── Connect + publish ────────────────────────────────────────────────────

    try {
      await room.connect(creds.url, creds.token, {
        autoSubscribe: true,
      } as RoomConnectOptions);
      connectedRef.current = true;

      await room.localParticipant.publishTrack(localTrack);

      setIsListening(true);
      startMicPoll();
      console.log('[MARK voice] connected — mic live');
    } catch (err) {
      console.warn('[MARK voice] connect failed:', err);
      localTrack.stop();
      localTrackRef.current = null;
      roomRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchCreds, startMicPoll, stopMarkSpeech, stopMicPoll, supported]);

  // ── Disconnect ─────────────────────────────────────────────────────────────

  const disconnect = useCallback(async () => {
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    stopMicPoll();
    localTrackRef.current?.stop();
    localTrackRef.current = null;
    audioElRef.current?.remove();
    audioElRef.current = null;
    if (roomRef.current) { await roomRef.current.disconnect(); roomRef.current = null; }
    connectedRef.current = false;
    setIsListening(false);
    setInterimTranscript('');
  }, [stopMicPoll]);

  // ── Toggle mic mute / unmute ───────────────────────────────────────────────

  const toggleVoice = useCallback(() => {
    setVoiceEnabled(prev => {
      const next = !prev;
      enabledRef.current = next;
      const track = localTrackRef.current;
      if (track) {
        if (next) {
          track.unmute().catch(() => {});
          setIsListening(true);
        } else {
          track.mute().catch(() => {});
          setIsListening(false);
          setInterimTranscript('');
        }
      } else if (next) {
        void connect();
      }
      return next;
    });
  }, [connect]);

  // ── Auto-connect on mount ──────────────────────────────────────────────────

  useEffect(() => {
    if (!supported) return;
    void connect();
    return () => {
      enabledRef.current = false;
      void disconnect();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported]);

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
