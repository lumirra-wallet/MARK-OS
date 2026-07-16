/**
 * VoicePanel — full voice-mode control surface for MARK.
 *
 * Provides:
 * - Mode selector: Push-to-Talk / Continuous / Wake Word
 * - PTT button with WebAudio recording → Whisper transcription
 * - Live state indicator (idle / listening / transcribing / speaking / error)
 * - Mute toggle
 * - Transcript display
 * - Settings: Whisper model, TTS voice, speed, language, wake phrase, auto-submit
 * - Browser SpeechSynthesis fallback indicator
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Mic, MicOff, Volume2, VolumeX, Radio, Activity,
  AudioWaveform, ChevronDown, CheckCircle, AlertCircle,
  Loader2, Square, Play, Settings2, Zap,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { VoiceMode } from '@/lib/markApi';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Slider } from '@/components/ui/slider';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';

// ─── Constants ────────────────────────────────────────────────────────────────

const WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'] as const;
const TTS_VOICES = [
  'en_US-lessac-medium',
  'en_US-ryan-high',
  'en_US-amy-medium',
  'en_GB-alan-medium',
  'en_GB-cori-high',
] as const;

const STATE_META: Record<string, { label: string; color: string; icon: React.ComponentType<any> }> = {
  idle:         { label: 'Idle',          color: 'text-muted-foreground', icon: Radio },
  listening:    { label: 'Listening',     color: 'text-emerald-400',      icon: AudioWaveform },
  transcribing: { label: 'Transcribing',  color: 'text-accent',           icon: Loader2 },
  thinking:     { label: 'Thinking',      color: 'text-purple-400',       icon: Loader2 },
  speaking:     { label: 'Speaking',      color: 'text-blue-400',         icon: Volume2 },
  error:        { label: 'Error',         color: 'text-destructive',       icon: AlertCircle },
};

// ─── PulsingRing component ────────────────────────────────────────────────────

function PulsingRing({ active, color }: { active: boolean; color: string }) {
  return (
    <div className="relative">
      <AnimatePresence>
        {active && (
          <>
            <motion.div
              className={`absolute inset-0 rounded-full ${color} opacity-30`}
              initial={{ scale: 1 }}
              animate={{ scale: 1.6, opacity: 0 }}
              transition={{ duration: 1.2, repeat: Infinity, ease: 'easeOut' }}
            />
            <motion.div
              className={`absolute inset-0 rounded-full ${color} opacity-20`}
              initial={{ scale: 1 }}
              animate={{ scale: 1.3, opacity: 0 }}
              transition={{ duration: 1.2, delay: 0.4, repeat: Infinity, ease: 'easeOut' }}
            />
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── SoundBars component ──────────────────────────────────────────────────────

function SoundBars({ active }: { active: boolean }) {
  return (
    <div className="flex items-end gap-0.5 h-4">
      {[0.4, 0.8, 0.6, 1, 0.5, 0.7, 0.3].map((h, i) => (
        <motion.div
          key={i}
          className="w-0.5 rounded-full bg-current"
          animate={active ? { height: ['30%', `${h * 100}%`, '30%'] } : { height: '20%' }}
          transition={{
            duration: 0.8,
            delay: i * 0.07,
            repeat: active ? Infinity : 0,
            ease: 'easeInOut',
          }}
          style={{ minHeight: 2 }}
        />
      ))}
    </div>
  );
}

// ─── PTT Button ──────────────────────────────────────────────────────────────

function PushToTalkButton() {
  const { voice, transcribeAudio, startRun, serverUrl } = useMarkStore();
  const [isRecording, setIsRecording] = useState(false);
  const [recordingMs, setRecordingMs] = useState(0);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks        = useRef<Blob[]>([]);
  const timerRef      = useRef<ReturnType<typeof setInterval> | null>(null);

  const startRecording = useCallback(async () => {
    if (isRecording || voice.muted) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      chunks.current = [];
      mr.ondataavailable = e => { if (e.data.size > 0) chunks.current.push(e.data); };
      mr.start(100);
      mediaRecorder.current = mr;
      setIsRecording(true);
      setRecordingMs(0);
      timerRef.current = setInterval(() => setRecordingMs(p => p + 100), 100);
    } catch (err) {
      console.error('Mic access denied', err);
    }
  }, [isRecording, voice.muted]);

  const stopRecording = useCallback(async () => {
    if (!isRecording || !mediaRecorder.current) return;
    const mr = mediaRecorder.current;
    if (timerRef.current) clearInterval(timerRef.current);
    setIsRecording(false);

    await new Promise<void>(resolve => {
      mr.onstop = () => resolve();
      mr.stop();
      mr.stream.getTracks().forEach(t => t.stop());
    });

    if (chunks.current.length === 0) return;
    const blob = new Blob(chunks.current, { type: 'audio/webm' });
    const text = await transcribeAudio(blob);
    // If auto-submit and we got text, trigger a run
    if (text && voice.autoSubmit) {
      // Find workspace from current store state — fall back to CWD
      const ws = useMarkStore.getState().workspace || '.';
      await useMarkStore.getState().startRun(text, ws);
    }
  }, [isRecording, transcribeAudio, voice.autoSubmit]);

  const formatMs = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative flex items-center justify-center">
        <PulsingRing active={isRecording} color="bg-red-500" />
        <motion.button
          className={`relative z-10 w-20 h-20 rounded-full flex items-center justify-center
            border-2 transition-colors shadow-lg
            ${isRecording
              ? 'bg-red-500 border-red-400 text-white shadow-red-500/30'
              : voice.muted
                ? 'bg-muted border-border text-muted-foreground cursor-not-allowed'
                : 'bg-card border-accent text-accent hover:bg-accent hover:text-accent-foreground shadow-accent/20'
            }`}
          onMouseDown={startRecording}
          onMouseUp={stopRecording}
          onTouchStart={startRecording}
          onTouchEnd={stopRecording}
          whileTap={{ scale: 0.95 }}
          disabled={voice.muted}
        >
          <Mic className="w-8 h-8" />
        </motion.button>
      </div>

      <div className="text-xs text-muted-foreground text-center">
        {isRecording ? (
          <span className="text-red-400 font-mono animate-pulse">● {formatMs(recordingMs)}</span>
        ) : voice.muted ? (
          <span>Microphone muted</span>
        ) : (
          <span>Hold to record</span>
        )}
      </div>
    </div>
  );
}

// ─── Main VoicePanel ──────────────────────────────────────────────────────────

export function VoicePanel() {
  const {
    voice, startVoice, stopVoice, toggleMute, updateVoiceSettings,
  } = useMarkStore();
  const [showSettings, setShowSettings] = useState(false);
  const [localSpeed, setLocalSpeed] = useState([voice.ttsSpeed]);

  const meta = STATE_META[voice.state] ?? STATE_META.idle;
  const StateIcon = meta.icon;

  const handleModeChange = async (mode: VoiceMode) => {
    if (voice.running) {
      await stopVoice();
    }
    await updateVoiceSettings({ mode });
  };

  const handleToggleVoice = async () => {
    if (voice.running) {
      await stopVoice();
    } else {
      await startVoice(voice.mode);
    }
  };

  // Debounced speed update
  const speedTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSpeedChange = (v: number[]) => {
    setLocalSpeed(v);
    if (speedTimeout.current) clearTimeout(speedTimeout.current);
    speedTimeout.current = setTimeout(() => {
      updateVoiceSettings({ tts_speed: v[0] });
    }, 500);
  };

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${voice.running ? 'bg-emerald-400 animate-pulse' : 'bg-muted-foreground'}`} />
            <span className="text-sm font-semibold">Voice Mode</span>
            {voice.isBrowserTTSFallback && (
              <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-400/30">
                Browser TTS
              </Badge>
            )}
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={() => setShowSettings(s => !s)}
          >
            <Settings2 className="w-3.5 h-3.5" />
          </Button>
        </div>

        {/* ── State badge ─────────────────────────────────────────────── */}
        <motion.div
          className={`flex items-center gap-2 text-sm font-medium ${meta.color}`}
          key={voice.state}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <StateIcon
            className={`w-4 h-4 ${voice.state === 'transcribing' || voice.state === 'thinking' ? 'animate-spin' : ''}`}
          />
          {meta.label}
          {voice.state === 'listening' && (
            <SoundBars active />
          )}
        </motion.div>

        {/* ── Mode selector ───────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Mode</Label>
          <div className="grid grid-cols-3 gap-1.5">
            {(['push_to_talk', 'continuous', 'wake_word'] as VoiceMode[]).map(m => (
              <button
                key={m}
                onClick={() => handleModeChange(m)}
                className={`text-[11px] py-1.5 px-2 rounded-md border transition-colors font-medium
                  ${voice.mode === m
                    ? 'bg-accent/20 border-accent/50 text-accent'
                    : 'bg-muted/50 border-border/50 text-muted-foreground hover:border-border hover:text-foreground'
                  }`}
              >
                {m === 'push_to_talk' ? 'Push-to-Talk' : m === 'continuous' ? 'Continuous' : 'Wake Word'}
              </button>
            ))}
          </div>
        </div>

        {/* ── Push-to-talk UI ─────────────────────────────────────────── */}
        {voice.mode === 'push_to_talk' && (
          <div className="flex flex-col items-center gap-2 py-2">
            <PushToTalkButton />
          </div>
        )}

        {/* ── Continuous / Wake-word controls ─────────────────────────── */}
        {(voice.mode === 'continuous' || voice.mode === 'wake_word') && (
          <div className="flex flex-col items-center gap-3 py-2">
            <div className="relative flex items-center justify-center">
              <PulsingRing
                active={voice.running && voice.state === 'listening'}
                color={voice.running ? 'bg-emerald-500' : 'bg-muted'}
              />
              <motion.button
                className={`relative z-10 w-20 h-20 rounded-full flex items-center justify-center
                  border-2 shadow-lg transition-colors
                  ${voice.running
                    ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400'
                    : 'bg-card border-border text-muted-foreground hover:border-accent hover:text-accent'
                  }`}
                onClick={handleToggleVoice}
                whileTap={{ scale: 0.95 }}
              >
                {voice.running ? <Square className="w-7 h-7" /> : <Play className="w-7 h-7" />}
              </motion.button>
            </div>
            <span className="text-xs text-muted-foreground">
              {voice.running
                ? voice.mode === 'wake_word'
                  ? `Say "${voice.mode}" to activate`
                  : 'Listening — speak now'
                : 'Click to start listening'}
            </span>
          </div>
        )}

        {/* ── Mute / controls ─────────────────────────────────────────── */}
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className={`flex-1 gap-1.5 text-xs ${voice.muted ? 'border-destructive/50 text-destructive' : ''}`}
            onClick={toggleMute}
          >
            {voice.muted ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            {voice.muted ? 'Unmute' : 'Mute'}
          </Button>
        </div>

        {/* ── Latest transcript ─────────────────────────────────────────── */}
        <AnimatePresence mode="popLayout">
          {voice.transcript && (
            <motion.div
              key={voice.transcript}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="rounded-lg border border-accent/20 bg-accent/5 p-3 space-y-1">
                <div className="flex items-center gap-1.5 text-[10px] text-accent/70 font-medium uppercase tracking-wide">
                  <CheckCircle className="w-3 h-3" />
                  Transcribed
                </div>
                <p className="text-sm text-foreground leading-relaxed">
                  "{voice.transcript}"
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Settings (collapsible) ──────────────────────────────────── */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="border border-border/50 rounded-lg p-3 space-y-4 bg-muted/20">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest">
                  Voice Settings
                </p>

                {/* Whisper model */}
                <div className="space-y-1.5">
                  <Label className="text-xs">Whisper Model</Label>
                  <Select
                    value={voice.whisperModel}
                    onValueChange={v => updateVoiceSettings({ whisper_model: v })}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {WHISPER_MODELS.map(m => (
                        <SelectItem key={m} value={m} className="text-xs">
                          {m}{m === 'base' ? ' (recommended)' : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-[10px] text-muted-foreground">
                    Larger = more accurate, slower. First use downloads the model.
                  </p>
                </div>

                {/* TTS voice */}
                <div className="space-y-1.5">
                  <Label className="text-xs">TTS Voice (Piper)</Label>
                  <Select
                    value={voice.ttsVoice}
                    onValueChange={v => updateVoiceSettings({ tts_voice: v })}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TTS_VOICES.map(v => (
                        <SelectItem key={v} value={v} className="text-xs">{v}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {voice.isBrowserTTSFallback && (
                    <p className="text-[10px] text-amber-400">
                      Piper not found — using browser SpeechSynthesis
                    </p>
                  )}
                </div>

                {/* TTS speed */}
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <Label className="text-xs">Speech Speed</Label>
                    <span className="text-xs font-mono text-muted-foreground">{localSpeed[0].toFixed(1)}×</span>
                  </div>
                  <Slider
                    min={0.5} max={2.0} step={0.1}
                    value={localSpeed}
                    onValueChange={handleSpeedChange}
                    className="h-1"
                  />
                </div>

                {/* Language */}
                <div className="space-y-1.5">
                  <Label className="text-xs">Language</Label>
                  <Input
                    className="h-8 text-xs font-mono"
                    defaultValue={voice.mode}
                    placeholder="en"
                    onBlur={e => updateVoiceSettings({ language: e.target.value })}
                  />
                </div>

                {/* Auto-submit */}
                <div className="flex items-center justify-between">
                  <div>
                    <Label className="text-xs">Auto-Submit</Label>
                    <p className="text-[10px] text-muted-foreground">Send transcription to MARK automatically</p>
                  </div>
                  <Switch
                    checked={voice.autoSubmit}
                    onCheckedChange={v => updateVoiceSettings({ auto_submit: v })}
                  />
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Info footer ────────────────────────────────────────────── */}
        <div className="text-[10px] text-muted-foreground/60 leading-relaxed space-y-1 border-t border-border/30 pt-3">
          <div className="flex items-center gap-1">
            <Zap className="w-3 h-3" />
            <span>100% local — Whisper STT + Piper TTS + OpenWakeWord</span>
          </div>
          <p>No audio leaves your machine.</p>
        </div>

      </div>
    </ScrollArea>
  );
}
