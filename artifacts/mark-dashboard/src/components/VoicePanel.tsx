/**
 * VoicePanel — the Narration panel.
 *
 * Deliberately minimal: this used to be a full voice-mode control surface
 * (Push-to-Talk / Continuous / Wake Word, mic recording, transcripts,
 * Whisper settings). Per the MARK v2 narration redesign, MARK only speaks —
 * it doesn't listen for spoken commands here — so this panel now shows
 * exactly five things: Voice Provider, Voice Selection, Speaking Status,
 * Volume, Mute.
 *
 * The backend `/voice/*` endpoints (Piper/OpenAI/transcription) are
 * untouched for backward compatibility — this panel just no longer
 * surfaces the STT/recording controls that used to sit in front of them.
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Volume2, VolumeX, Mic, MicOff, Radio, Loader2, Play } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

const PROVIDERS = [
  { value: 'kokoro',  label: 'Kokoro (default)' },
  { value: 'piper',   label: 'Piper' },
  { value: 'openai',  label: 'OpenAI' },
  { value: 'browser', label: 'Browser (fallback)' },
] as const;

const SPEAKING_META: Record<string, { label: string; color: string; icon: React.ComponentType<any> }> = {
  idle:     { label: 'Idle',     color: 'text-muted-foreground', icon: Radio },
  speaking: { label: 'Speaking', color: 'text-blue-400',         icon: Volume2 },
  error:    { label: 'Error',    color: 'text-destructive',      icon: Radio },
};

export function VoicePanel() {
  const { voice, serverUrl, toggleMute, setTtsProvider, setTtsVoice, setOpenaiVoice, setTtsVolume, speak } = useMarkStore();
  const [voices, setVoices]       = useState<string[]>([]);
  const [available, setAvailable] = useState<Record<string, boolean>>({});

  const meta = SPEAKING_META[voice.state] ?? SPEAKING_META.idle;
  const StateIcon = meta.icon;
  const isOpenAI = voice.ttsProvider === 'openai';
  const selectedVoice = isOpenAI ? voice.openaiVoice : voice.ttsVoice;
  const setSelectedVoice = isOpenAI ? setOpenaiVoice : setTtsVoice;

  useEffect(() => {
    fetch(`${serverUrl}/tts/status`)
      .then(r => r.json())
      .then(data => setAvailable(data.providers ?? {}))
      .catch(() => {});
  }, [serverUrl]);

  useEffect(() => {
    if (voice.ttsProvider === 'browser') { setVoices([]); return; }
    fetch(`${serverUrl}/tts/voices?provider=${voice.ttsProvider}`)
      .then(r => r.json())
      .then(data => setVoices(data.voices ?? []))
      .catch(() => setVoices([]));
  }, [serverUrl, voice.ttsProvider]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">

        {/* ── Speaking status ─────────────────────────────────────────── */}
        <motion.div
          className={cn('flex items-center gap-2 text-sm font-medium', meta.color)}
          key={voice.state}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <StateIcon className={cn('w-4 h-4', voice.state === 'speaking' && 'animate-pulse')} />
          {meta.label}
        </motion.div>

        {/* ── Voice Provider ───────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Voice Provider</Label>
          <Select value={voice.ttsProvider} onValueChange={v => setTtsProvider(v as typeof voice.ttsProvider)}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map(p => (
                <SelectItem key={p.value} value={p.value} className="text-xs">
                  {p.label}{p.value !== 'browser' && available[p.value] === false ? ' — unavailable' : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* ── Voice Selection ──────────────────────────────────────────── */}
        {voice.ttsProvider !== 'browser' && voices.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Voice</Label>
            <Select value={selectedVoice} onValueChange={setSelectedVoice}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {voices.map(v => (
                  <SelectItem key={v} value={v} className="text-xs">{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* ── Volume ───────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <Label className="text-xs text-muted-foreground">Volume</Label>
            <span className="text-xs font-mono text-muted-foreground">{Math.round(voice.ttsVolume * 100)}%</span>
          </div>
          <Slider
            min={0} max={1} step={0.05}
            value={[voice.ttsVolume]}
            onValueChange={v => setTtsVolume(v[0])}
            className="h-1"
          />
        </div>

        {/* ── Mute + test ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className={cn('flex-1 gap-1.5 text-xs', voice.muted && 'border-destructive/50 text-destructive')}
            onClick={toggleMute}
          >
            {voice.muted ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            {voice.muted ? 'Unmute' : 'Mute'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="gap-1.5 text-xs"
            onClick={() => speak("I'm MARK, your AI software engineer.")}
          >
            <Play className="w-3.5 h-3.5" />
            Test
          </Button>
        </div>

      </div>
    </ScrollArea>
  );
}
