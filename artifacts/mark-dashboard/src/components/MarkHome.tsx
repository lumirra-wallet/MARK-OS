import { useState, useMemo } from 'react';
import { ArrowRight, Mic, MicOff, MessageCircle, X, ChevronDown, ChevronUp, Globe } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { useVoice } from '@/hooks/use-voice';
import { PresenceEngine } from './PresenceEngine';
import { ChatView } from './ChatView';
import { ApprovalsSidebar } from './ApprovalsSidebar';

/**
 * Elena's Home — Live call interface inspired by ChatGPT-5's real-time mode.
 *
 * Full-screen dark canvas with Elena's membrane orb at center, dual live
 * transcripts at the bottom (user left, Elena right), and a clean minimal
 * control bar. Everything driven by real backend state — no simulated values.
 */

// ── Transcript helpers ────────────────────────────────────────────────────────

function truncate(text: string, max: number) {
  if (!text) return '';
  if (text.length <= max) return text;
  return '…' + text.slice(-(max - 1));
}

// ── Emotion → accent color ────────────────────────────────────────────────────
const EMOTION_COLOR: Record<string, string> = {
  neutral:    'text-emerald-400',
  curious:    'text-blue-400',
  focused:    'text-emerald-300',
  satisfied:  'text-green-400',
  uncertain:  'text-amber-400',
  frustrated: 'text-red-400',
};

// ── Live state label ──────────────────────────────────────────────────────────
function getStateLabel(params: {
  isListening: boolean;
  isMarkSpeaking: boolean;
  isThinking: boolean;
  running: boolean;
  emotionalState: string;
}): { label: string; pulse: boolean } {
  const { isListening, isMarkSpeaking, isThinking, running, emotionalState } = params;
  if (isThinking) return { label: 'thinking', pulse: true };
  if (isMarkSpeaking) return { label: 'speaking', pulse: true };
  if (isListening) return { label: 'listening', pulse: true };
  if (running) return { label: 'working', pulse: true };
  if (emotionalState === 'curious') return { label: 'curious', pulse: false };
  if (emotionalState === 'focused') return { label: 'focused', pulse: false };
  if (emotionalState === 'satisfied') return { label: 'satisfied', pulse: false };
  return { label: 'idle', pulse: false };
}

export function MarkHome({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  const pendingPermissions = useMarkStore(s => s.pendingPermissions);
  const emotionalState     = useMarkStore(s => s.emotionalState ?? 'neutral');
  const running            = useMarkStore(s => s.running);
  const isMarkSpeaking     = useMarkStore(s => s.isMarkSpeaking);
  const messages           = useMarkStore(s => s.messages);
  const streamingTokens    = useMarkStore(s => s.streamingTokens);
  const speakerName        = useMarkStore(s => s.speakerName);
  const speakerConfidence  = useMarkStore(s => s.speakerConfidence);

  const { selfState } = useSelfState();
  const voice = useVoice();

  const [chatOpen, setChatOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);

  // ── Derive transcript content from real state ─────────────────────────────
  const lastUserMsg = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user' && messages[i].text) return messages[i].text!;
    }
    return '';
  }, [messages]);

  const lastElenaMsg = useMemo(() => {
    // When Elena is actively streaming, show that; otherwise show last message
    if (running && streamingTokens) return streamingTokens;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'mark') {
        const block = messages[i].blocks.find(b => b.type === 'text' || b.type === 'streaming');
        if (block && (block.type === 'text' || block.type === 'streaming')) return block.text;
      }
    }
    return '';
  }, [messages, running, streamingTokens]);

  // Current user's live transcript (interim speech recognition)
  const currentUserSpeech = voice.interimTranscript;

  const stateLabel = getStateLabel({
    isListening: voice.isListening,
    isMarkSpeaking,
    isThinking: voice.isThinking,
    running,
    emotionalState: emotionalState || 'neutral',
  });

  const emotionColor = EMOTION_COLOR[emotionalState || 'neutral'] ?? EMOTION_COLOR.neutral;
  const showUserTranscript = currentUserSpeech || lastUserMsg;
  const showElenaTranscript = lastElenaMsg;

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-black select-none">

      {/* ── Presence Engine — fills the whole canvas ────────────────────────── */}
      <PresenceEngine
        className="absolute inset-0"
        micLevel={voice.micLevel}
        isListening={voice.isListening}
        isVoiceSpeaking={voice.isSpeaking}
      />

      {/* ── Permission banner (safety-critical, always on top) ─────────────── */}
      {pendingPermissions.length > 0 && (
        <div className="absolute top-0 inset-x-0 z-40 border-b border-destructive/30 bg-destructive/10 backdrop-blur-sm">
          <ApprovalsSidebar />
        </div>
      )}

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <div className="absolute top-0 inset-x-0 z-20 flex items-center justify-between px-5 pt-4 pb-2 pointer-events-none">

        {/* Elena name + live state */}
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold tracking-[0.25em] uppercase text-white/90">
              Elena
            </span>
            <div className="flex items-center gap-1.5 mt-0.5">
              {stateLabel.pulse && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    voice.isThinking ? 'bg-amber-400' :
                    isMarkSpeaking ? 'bg-emerald-400' :
                    'bg-emerald-500'
                  }`} />
                  <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${
                    voice.isThinking ? 'bg-amber-400' :
                    isMarkSpeaking ? 'bg-emerald-400' :
                    'bg-emerald-500'
                  }`} />
                </span>
              )}
              <span className={`text-[10px] font-mono tracking-wider transition-all duration-500 ${
                stateLabel.pulse
                  ? voice.isThinking
                    ? 'text-amber-400'
                    : isMarkSpeaking
                      ? 'text-emerald-400'
                      : 'text-emerald-500'
                  : emotionColor
              }`}>
                {stateLabel.label}
              </span>
            </div>
          </div>
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-2 pointer-events-auto">
          {/* Web search indicator */}
          <div
            className="flex items-center gap-1 px-2 py-1 rounded bg-black/20 border border-white/5 text-[9px] font-mono text-white/30"
            title="Elena can search the web"
          >
            <Globe className="w-2.5 h-2.5" />
            <span>web</span>
          </div>

          {/* Memory toggle */}
          <button
            onClick={() => setMemoryOpen(v => !v)}
            className="flex items-center gap-1 px-2 py-1 rounded bg-black/20 hover:bg-white/5 border border-white/5 text-[9px] font-mono text-white/30 hover:text-white/60 transition-colors"
            title="View Elena's memory"
          >
            <span>memory</span>
          </button>

          {/* Engineering workspace */}
          <button
            onClick={onOpenWorkspace}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-black/30 hover:bg-white/5 border border-white/10 text-[11px] font-mono text-white/40 hover:text-white/70 transition-colors"
          >
            <span>Workspace</span>
            <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* ── Confidence + health (minimal vitals) ───────────────────────────── */}
      {selfState && (
        <div className="absolute top-16 left-5 z-10 flex items-center gap-2 text-[9px] font-mono text-white/20 pointer-events-none">
          <span>{Math.round(selfState.confidence * 100)}% confident</span>
          <span>·</span>
          <span>{Math.round(selfState.health * 100)}% health</span>
        </div>
      )}

      {/* ── Speaker identity badge ───────────────────────────────────────────── */}
      {speakerName && speakerName !== 'Unknown' && (
        <div className="absolute top-[5.5rem] left-5 z-10 flex items-center gap-1.5 pointer-events-none">
          <span
            className="w-1.5 h-1.5 rounded-full bg-violet-400"
            style={{ opacity: 0.4 + speakerConfidence * 0.6 }}
          />
          <span className="text-[9px] font-mono text-violet-300/50">
            {speakerName}
            {speakerConfidence > 0 && (
              <span className="ml-1 text-violet-300/30">
                {Math.round(speakerConfidence * 100)}%
              </span>
            )}
          </span>
        </div>
      )}

      {/* ── Memory panel (slides in from top-right) ─────────────────────────── */}
      {memoryOpen && (
        <div className="absolute top-14 right-4 z-30 w-64 bg-black/80 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl">
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
            <span className="text-[10px] font-mono text-white/50 uppercase tracking-wider">Elena's Memory</span>
            <button onClick={() => setMemoryOpen(false)} className="text-white/30 hover:text-white/60">
              <X className="w-3 h-3" />
            </button>
          </div>
          <MemoryPanel />
        </div>
      )}

      {/* ── Live transcript area (positioned at lower 35%) ──────────────────── */}
      <div className="absolute inset-x-0 bottom-28 z-10 px-6 space-y-2 pointer-events-none">

        {/* Thinking indicator */}
        {voice.isThinking && (
          <div className="flex justify-center mb-1">
            <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-amber-400/10 border border-amber-400/20">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-amber-400" />
              </span>
              <span className="text-[10px] font-mono text-amber-400">Processing…</span>
            </div>
          </div>
        )}

        {/* Dual transcript — user left, Elena right */}
        <div className="flex items-end gap-4 min-h-[3rem]">

          {/* User transcript */}
          <div className="flex-1 text-right">
            {showUserTranscript && (
              <div className="inline-block max-w-full">
                <p className="text-[11px] font-mono text-white/25 mb-0.5 text-right tracking-wider">You</p>
                <div className="bg-white/5 backdrop-blur-sm border border-white/8 rounded-xl rounded-br-sm px-3 py-2 inline-block max-w-full">
                  <p className="text-sm text-white/80 leading-relaxed text-right break-words">
                    {currentUserSpeech
                      ? <span className="italic text-white/60">{truncate(currentUserSpeech, 120)}</span>
                      : truncate(lastUserMsg, 120)
                    }
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Elena transcript */}
          <div className="flex-1">
            {showElenaTranscript && (
              <div className="inline-block max-w-full">
                <p className="text-[11px] font-mono text-emerald-400/50 mb-0.5 tracking-wider">Elena</p>
                <div className="bg-emerald-500/5 backdrop-blur-sm border border-emerald-500/10 rounded-xl rounded-bl-sm px-3 py-2 inline-block max-w-full">
                  <p className="text-sm text-white/85 leading-relaxed break-words">
                    {truncate(lastElenaMsg, 180)}
                    {running && streamingTokens && (
                      <span className="inline-block w-0.5 h-3.5 bg-emerald-400 ml-0.5 animate-pulse align-middle" />
                    )}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Control bar ─────────────────────────────────────────────────────── */}
      <div className="absolute bottom-0 inset-x-0 z-20 flex items-center justify-center gap-6 pb-8 pt-3">

        {/* Chat toggle */}
        <button
          onClick={() => setChatOpen(v => !v)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white/5 hover:bg-white/10 border border-white/10 text-white/40 hover:text-white/70 transition-all text-xs font-mono"
        >
          <MessageCircle className="w-3.5 h-3.5" />
          <span>text</span>
        </button>

        {/* Primary mic button — center, larger */}
        <div className="relative">
          {/* Outer pulse ring — amplitude-driven */}
          {voice.voiceEnabled && voice.isListening && !voice.isSpeaking && !voice.isThinking && (
            <span
              className="absolute inset-0 rounded-full border border-emerald-400/40 transition-transform duration-75 pointer-events-none"
              style={{
                transform: `scale(${1 + voice.micLevel * 0.5})`,
                opacity:   Math.max(0.1, voice.micLevel * 0.9),
              }}
            />
          )}
          {/* Thinking ring */}
          {voice.isThinking && (
            <span className="absolute inset-0 rounded-full border border-amber-400/40 animate-ping pointer-events-none" />
          )}
          {/* Speaking ring */}
          {isMarkSpeaking && !voice.isThinking && (
            <span className="absolute inset-0 rounded-full border border-emerald-400/50 animate-pulse pointer-events-none" />
          )}

          <button
            onClick={voice.toggleVoice}
            disabled={!voice.supported}
            title={
              !voice.supported
                ? "Voice not supported in this browser"
                : voice.voiceEnabled
                  ? 'Mute microphone'
                  : 'Unmute microphone'
            }
            className={`relative flex items-center justify-center w-16 h-16 rounded-full border-2 transition-all duration-200 shadow-lg ${
              voice.isThinking
                ? 'bg-amber-500/15 border-amber-400/50 text-amber-400 shadow-amber-400/10'
                : isMarkSpeaking
                  ? 'bg-emerald-500/15 border-emerald-400/60 text-emerald-400 shadow-emerald-400/20'
                  : voice.voiceEnabled
                    ? 'bg-emerald-500/10 border-emerald-400/40 text-emerald-400 shadow-emerald-400/10 hover:bg-emerald-500/20'
                    : 'bg-white/5 border-white/15 text-white/40 hover:text-white/70 hover:border-white/30'
            } ${!voice.supported ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            {voice.voiceEnabled
              ? <Mic className="w-6 h-6" />
              : <MicOff className="w-6 h-6" />
            }
          </button>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-white/5 border border-white/10">
          <ConnectionDot />
        </div>
      </div>

      {/* ── Chat drawer (slides up from bottom) ─────────────────────────────── */}
      {chatOpen && (
        <div
          className="absolute inset-x-0 bottom-0 z-30 bg-black/95 backdrop-blur-xl border-t border-white/10 rounded-t-2xl shadow-2xl"
          style={{ height: '70%' }}
        >
          <div className="flex items-center justify-between px-4 pt-3 pb-2 border-b border-white/5">
            <span className="text-[11px] font-mono text-white/40 tracking-wider uppercase">Chat with Elena</span>
            <button
              onClick={() => setChatOpen(false)}
              className="flex items-center gap-1 text-[11px] text-white/30 hover:text-white/60 transition-colors"
            >
              <ChevronDown className="w-3.5 h-3.5" />
              <span>close</span>
            </button>
          </div>
          <div className="h-[calc(100%-2.5rem)] min-h-0">
            <ChatView />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tiny connection status dot ────────────────────────────────────────────────
function ConnectionDot() {
  const status = useMarkStore(s => s.connectionStatus);
  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${
        status === 'connected'    ? 'bg-emerald-400' :
        status === 'connecting'   ? 'bg-amber-400 animate-pulse' :
        'bg-red-400/60'
      }`} />
      <span className={`text-[9px] font-mono ${
        status === 'connected'  ? 'text-white/30' :
        status === 'connecting' ? 'text-amber-400/60' :
        'text-red-400/60'
      }`}>
        {status}
      </span>
    </div>
  );
}

// ── Memory panel (Elena's persisted knowledge) ────────────────────────────────
function MemoryPanel() {
  const [data, setData] = useState<null | {
    episodic_today: number;
    semantic_total: number;
    owner_attributes: number;
    recent_facts: string[];
    web_searches: number;
  }>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const serverUrl = useMarkStore(s => s.serverUrl);

  const load = async () => {
    if (loading || data) return;
    setLoading(true);
    try {
      const res = await fetch(`${serverUrl}/memory/summary`);
      if (res.ok) setData(await res.json());
    } catch {
      // silently ignore
    } finally {
      setLoading(false);
    }
  };

  // Load on mount
  if (!data && !loading) load();

  return (
    <div className="p-3 space-y-2">
      {loading && (
        <p className="text-[10px] font-mono text-white/30 text-center py-2">Loading…</p>
      )}
      {data && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="today" value={data.episodic_today} color="text-blue-400" />
            <Stat label="facts" value={data.semantic_total} color="text-emerald-400" />
            <Stat label="owner" value={data.owner_attributes} color="text-violet-400" />
          </div>

          {data.recent_facts.length > 0 && (
            <div className="space-y-1 pt-1 border-t border-white/5">
              <button
                onClick={() => setOpen(v => !v)}
                className="flex items-center gap-1 text-[9px] font-mono text-white/30 hover:text-white/50 transition-colors"
              >
                {open ? <ChevronUp className="w-2.5 h-2.5" /> : <ChevronDown className="w-2.5 h-2.5" />}
                recent facts
              </button>
              {open && (
                <ul className="space-y-1">
                  {data.recent_facts.slice(0, 4).map((f, i) => (
                    <li key={i} className="text-[9px] text-white/40 truncate">• {f}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {data.web_searches > 0 && (
            <div className="flex items-center gap-1.5 pt-1 border-t border-white/5">
              <Globe className="w-2.5 h-2.5 text-emerald-400/50" />
              <span className="text-[9px] font-mono text-white/30">{data.web_searches} web facts learned</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 bg-white/3 rounded-lg py-1.5">
      <span className={`text-base font-bold ${color}`}>{value}</span>
      <span className="text-[8px] font-mono text-white/30">{label}</span>
    </div>
  );
}
