import { useCallback, useEffect, useRef, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

/**
 * Real voice I/O for MARK — browser-native Web Speech API (SpeechRecognition
 * for listening, speechSynthesis for speaking). No cloud STT/TTS provider:
 * that requires an account and an API key only the owner can provision
 * (smartagent/voice/speech_to_text.py and text_to_speech.py are still
 * genuinely unbuilt server-side — confirmed in the Brain Ownership audit).
 * This is real microphone capture and real synthesized speech today, not a
 * placeholder — just running client-side instead of through a paid backend.
 *
 * Pipeline: mic → SpeechRecognition transcript → the SAME sendUserMessage()
 * the typed chat box already uses (no parallel path) → MARK's real reply
 * streams back over the existing WebSocket → speechSynthesis speaks it.
 * Listening pauses while MARK is speaking, to avoid the mic picking up his
 * own voice as if it were the owner talking.
 *
 * Opt-in by design, not auto-started: browsers require a user gesture
 * before granting microphone access, and starting to listen without one
 * being asked for would be a real consent violation even if it weren't
 * also technically blocked.
 */

// Web Speech API isn't in TypeScript's standard DOM lib — minimal shims for
// exactly what's used here.
interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: Event) => void) | null;
}

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function useVoice() {
  const { workspace, sendUserMessage, messages } = useMarkStore();

  const [supported] = useState(() => getSpeechRecognitionCtor() !== null && 'speechSynthesis' in window);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [micLevel, setMicLevel] = useState(0); // 0-1, real amplitude — not decorative
  const [interimTranscript, setInterimTranscript] = useState('');

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);
  const enabledRef = useRef(false);
  const speakingRef = useRef(false);
  const lastSpokenMsgId = useRef<string | null>(null);

  // ── Real mic amplitude, sampled every animation frame from the actual
  // audio buffer — not a fake pulse, a live FFT read of the microphone. ──
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

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
    cancelAnimationFrame(rafRef.current);
    micStreamRef.current?.getTracks().forEach(t => t.stop());
    micStreamRef.current = null;
    analyserRef.current = null;
    setMicLevel(0);
  }, []);

  const startListening = useCallback(async () => {
    if (!enabledRef.current || speakingRef.current) return;
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      micStreamRef.current = stream;
      const ctx = audioCtxRef.current ?? new AudioContext();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
      rafRef.current = requestAnimationFrame(pollLevel);
    } catch {
      // Mic permission denied or unavailable — recognition below still
      // works without amplitude visualization; MARK just won't get the
      // live "listening" pulse.
    }

    const recognition = new Ctor();
    recognition.continuous = false; // one utterance at a time — restarted below
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          const transcript = r[0].transcript.trim();
          if (transcript) {
            sendUserMessage(transcript, workspace);
          }
          setInterimTranscript('');
        } else {
          interim += r[0].transcript;
        }
      }
      if (interim) setInterimTranscript(interim);
    };

    recognition.onerror = () => { /* transient — onend still fires and restarts */ };

    recognition.onend = () => {
      setIsListening(false);
      // Continuous experience: pick listening back up automatically, as
      // long as voice mode is still on and MARK isn't talking right now.
      if (enabledRef.current && !speakingRef.current) {
        window.setTimeout(() => startListening(), 250);
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [pollLevel, sendUserMessage, workspace]);

  const speak = useCallback((text: string) => {
    if (!('speechSynthesis' in window) || !text.trim()) return;
    // Never listen to ourselves — pause recognition while MARK talks.
    speakingRef.current = true;
    stopListening();
    setIsSpeaking(true);

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = utterance.onerror = () => {
      speakingRef.current = false;
      setIsSpeaking(false);
      if (enabledRef.current) startListening();
    };
    window.speechSynthesis.cancel(); // don't queue over a previous reply
    window.speechSynthesis.speak(utterance);
  }, [startListening, stopListening]);

  const toggleVoice = useCallback(() => {
    setVoiceEnabled(v => {
      const next = !v;
      enabledRef.current = next;
      if (next) {
        startListening();
      } else {
        stopListening();
        window.speechSynthesis.cancel();
        speakingRef.current = false;
        setIsSpeaking(false);
      }
      return next;
    });
  }, [startListening, stopListening]);

  // Speak MARK's real replies aloud once they finish streaming — the same
  // finalized message the chat transcript shows, nothing separately
  // generated for voice.
  useEffect(() => {
    if (!voiceEnabled) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'mark' || last.isActive) return;
    if (last.id === lastSpokenMsgId.current) return;
    const text = last.blocks
      .filter(b => b.type === 'text' || b.type === 'summary')
      .map(b => (b as any).text as string)
      .join(' ')
      .trim();
    if (!text) return;
    lastSpokenMsgId.current = last.id;
    speak(text);
  }, [messages, voiceEnabled, speak]);

  useEffect(() => () => {
    stopListening();
    window.speechSynthesis.cancel();
  }, [stopListening]);

  return { supported, voiceEnabled, isListening, isSpeaking, micLevel, interimTranscript, toggleVoice };
}
