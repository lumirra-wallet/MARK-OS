import { useState } from 'react';
import { ArrowRight, MessageCircle, ChevronDown, ChevronUp, Mic, MicOff, Volume2 } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { useVoice } from '@/hooks/use-voice';
import { PresenceEngine } from './PresenceEngine';
import { ChatView } from './ChatView';
import { ApprovalsSidebar } from './ApprovalsSidebar';
import { CognitiveTimeline } from './CognitiveTimeline';

/**
 * MARK's Home — the brain in view.
 *
 * The presence animation and cognitive timeline are driven entirely by real
 * backend events. The text below MARK's name changes to reflect what he is
 * actually doing right now — never a canned phrase, never a simulated state.
 *
 * Cognitive Timeline is shown by default because it's the core value of
 * Task #6: making MARK's thinking visible and verifiable.
 */

// ── Living presence text ─────────────────────────────────────────────────────
// Maps real system state → quiet, alive text. No status toasts.
function getPresenceText(params: {
  running: boolean;
  isListening: boolean;
  isMarkSpeaking: boolean;
  isVoiceSpeaking: boolean;
  isThinking: boolean;
  emotionalState: string;
  modeLabel: string;
  lastStep?: string;
}): string {
  const { running, isListening, isMarkSpeaking, isVoiceSpeaking, isThinking, emotionalState, modeLabel, lastStep } = params;

  if (isMarkSpeaking || isVoiceSpeaking) return 'Speaking.';
  if (isThinking) return 'Thinking…';
  if (isListening && !isMarkSpeaking) return 'Listening.';
  if (running) {
    if (lastStep === 'reasoning')         return 'Thinking.';
    if (lastStep === 'memory_retrieved')  return 'Reviewing recent memories.';
    if (lastStep === 'knowledge_matched') return 'Matching knowledge.';
    if (lastStep === 'decision_made')     return 'Deciding.';
    return 'Working.';
  }
  if (emotionalState === 'curious')    return 'Something caught my attention.';
  if (emotionalState === 'satisfied')  return 'That went well.';
  if (emotionalState === 'focused')    return 'Focused.';
  if (emotionalState === 'uncertain')  return 'Not sure — ask me to clarify.';
  if (emotionalState === 'frustrated') return 'Having some trouble.';
  return modeLabel || 'Idle.';
}

// Emotion badge colors
const EMOTION_BADGE: Record<string, { bg: string; text: string; dot: string }> = {
  neutral:    { bg: 'bg-transparent',         text: 'text-transparent',          dot: 'bg-transparent' },
  curious:    { bg: 'bg-blue-500/10',         text: 'text-blue-400',             dot: 'bg-blue-400' },
  focused:    { bg: 'bg-emerald-500/10',      text: 'text-emerald-400',          dot: 'bg-emerald-400' },
  satisfied:  { bg: 'bg-green-500/10',        text: 'text-green-400',            dot: 'bg-green-400' },
  uncertain:  { bg: 'bg-amber-500/10',        text: 'text-amber-400',            dot: 'bg-amber-400' },
  frustrated: { bg: 'bg-red-500/10',          text: 'text-red-400',              dot: 'bg-red-400' },
};

export function MarkHome({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  // Individual selectors — Zustand object selectors create a new object every
  // render, which trips the equality check and causes an infinite loop.
  const pendingPermissions = useMarkStore(s => s.pendingPermissions);
  const emotionalState     = useMarkStore(s => s.emotionalState ?? 'neutral');
  const emotionalReason    = useMarkStore(s => s.emotionalReason ?? '');
  const cognitiveEvents    = useMarkStore(s => s.cognitiveEvents ?? []);
  const running            = useMarkStore(s => s.running);
  const isMarkSpeaking     = useMarkStore(s => s.isMarkSpeaking);
  const knowledgeGrowth    = useMarkStore(s => s.knowledgeGrowth ?? 0);
  const memoryActivity     = useMarkStore(s => s.memoryActivity ?? []);
  const { selfState, modeLabel, activity } = useSelfState();
  const voice = useVoice();
  const [chatOpen, setChatOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(true);
  // "Pure voice call" mode — hides the transcript/status line so it feels
  // like talking on the phone rather than typing in a chat box.
  const [transcriptVisible, setTranscriptVisible] = useState(true);

  const latestStep = cognitiveEvents[0]?.step;

  const presenceText = getPresenceText({
    running,
    isListening:     voice.isListening,
    isMarkSpeaking,
    isVoiceSpeaking: voice.isSpeaking,
    isThinking:      voice.isThinking,
    emotionalState:  emotionalState || 'neutral',
    modeLabel:       modeLabel || 'Idle',
    lastStep:        latestStep,
  });

  const badge = EMOTION_BADGE[emotionalState || 'neutral'] || EMOTION_BADGE.neutral;
  const showBadge = emotionalState && emotionalState !== 'neutral';

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-background">
      <PresenceEngine
        className="absolute inset-0"
        micLevel={voice.micLevel}
        isListening={voice.isListening}
        isVoiceSpeaking={voice.isSpeaking}
      />

      {/* Safety-critical — always visible */}
      {pendingPermissions.length > 0 && (
        <div className="absolute top-0 inset-x-0 z-30 border-b border-destructive/30 bg-destructive/10 backdrop-blur-sm">
          <ApprovalsSidebar />
        </div>
      )}

      {/* MARK's name + living presence text */}
      <div className="absolute top-8 inset-x-0 z-10 flex flex-col items-center gap-1.5 pointer-events-none">
        <h1 className="text-lg font-bold tracking-[0.2em] uppercase text-foreground/90">ELENA</h1>

        {/* Living presence text — changes with real state, never static */}
        <p className="text-sm text-muted-foreground transition-all duration-700">
          {presenceText}
        </p>

        {/* Emotional state badge — only shown for non-neutral states */}
        {showBadge && (
          <div className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-mono ${badge.bg} ${badge.text}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
            {emotionalState}
            {emotionalReason && (
              <span className="opacity-60 truncate max-w-[120px]">· {emotionalReason}</span>
            )}
          </div>
        )}

        {activity && !running && (
          <p className="text-xs text-muted-foreground/50 max-w-md text-center px-4 truncate mt-0.5">
            {activity}
          </p>
        )}
      </div>

      {/* Engineering Workspace link */}
      <button
        onClick={onOpenWorkspace}
        className="absolute top-4 right-4 z-10 flex items-center gap-1.5 text-[11px] font-mono bg-card/40 hover:bg-card/70 text-muted-foreground hover:text-foreground px-2.5 py-1.5 rounded border border-border/30 backdrop-blur-sm transition-colors"
        title="Open the Engineering Workspace"
      >
        Engineering Workspace
        <ArrowRight className="w-3 h-3" />
      </button>

      {/* ── Cognitive Timeline ─────────────────────────────────────────────── */}
      {/* Positioned on the right edge — doesn't obscure the brain */}
      <div className="absolute top-16 right-4 z-10 w-56">
        <button
          onClick={() => setTimelineOpen(v => !v)}
          className="w-full flex items-center justify-between px-2 py-1 text-[10px] font-mono text-muted-foreground/50 hover:text-muted-foreground bg-card/30 hover:bg-card/50 rounded-t border border-border/20 backdrop-blur-sm transition-colors"
        >
          <span className="tracking-wider uppercase">Cognitive Timeline</span>
          {timelineOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
        {timelineOpen && (
          <div className="bg-card/30 border border-t-0 border-border/20 backdrop-blur-sm rounded-b overflow-hidden">
            <CognitiveTimeline
              events={cognitiveEvents}
              maxVisible={6}
              className="p-1"
            />
            {/* Brain stats — real counts only, never estimated */}
            <div className="flex items-center justify-between px-2 py-1.5 border-t border-border/10 text-[9px] font-mono text-muted-foreground/40">
              <span>learned {knowledgeGrowth} concepts</span>
              <span>·</span>
              <span>{memoryActivity.length} writes</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Voice ─────────────────────────────────────────────────────────── */}
      {/* MARK is always listening — no enable/disable, just mute/unmute.
          The status line and pulse ring are visible whenever the mic is live. */}
      <div className="absolute bottom-24 inset-x-0 z-10 flex flex-col items-center gap-2 pointer-events-none">

        {/* Thinking pulse — fires the INSTANT VAD detects speech end,
            ~300-800 ms before the LLM call starts.  Amber to distinguish
            from the green "listening" mic ring. */}
        {voice.isThinking && (
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
            </span>
            <p className="text-xs text-amber-400/80 font-mono tracking-wide">Thinking…</p>
          </div>
        )}

        {/* Live transcript / status line — toggleable for "pure voice call" feel */}
        {transcriptVisible && (
          <div className="flex items-center gap-1.5 min-h-[1.25em] max-w-md text-center px-4">
            {voice.isListening && voice.voiceEnabled && !voice.isSpeaking && !voice.isThinking && (
              /* Pulsing dot — amplitude-driven via opacity so it feels live */
              <span
                className="w-1.5 h-1.5 rounded-full bg-accent flex-shrink-0 transition-opacity duration-75"
                style={{ opacity: 0.35 + voice.micLevel * 0.65 }}
              />
            )}
            <p className="text-xs text-muted-foreground truncate">
              {!voice.supported
                ? 'Voice not supported in this browser'
                : voice.isSpeaking
                  ? 'Speaking…'
                  : voice.isThinking
                    ? 'Processing…'
                    : voice.interimTranscript
                      ? voice.interimTranscript
                      : !voice.voiceEnabled
                        ? 'Mic muted — click to unmute'
                        : voice.isListening
                          ? 'Listening…'
                          : 'Connecting…'}
            </p>
          </div>
        )}

        {/* Mic button with amplitude ring */}
        <div className="relative pointer-events-auto">
          {/* Thinking ring — amber pulse while MARK processes your words */}
          {voice.isThinking && (
            <span className="absolute inset-0 rounded-full border border-amber-400/50 animate-ping" />
          )}
          {/* Outer pulse ring — scale with mic level while MARK is listening */}
          {voice.voiceEnabled && voice.isListening && !voice.isSpeaking && !voice.isThinking && (
            <span
              className="absolute inset-0 rounded-full border border-accent/60 transition-transform duration-75"
              style={{
                transform: `scale(${1 + voice.micLevel * 0.35})`,
                opacity:   Math.max(0.15, voice.micLevel * 0.8),
              }}
            />
          )}
          <button
            onClick={voice.toggleVoice}
            disabled={!voice.supported}
            className={`flex items-center justify-center w-14 h-14 rounded-full border transition-all ${
              voice.isThinking
                ? 'bg-amber-500/10 border-amber-400/60 text-amber-400'
                : voice.voiceEnabled
                  ? 'bg-accent/20 border-accent text-accent shadow-lg shadow-accent/20'
                  : 'bg-card/50 border-border/50 text-muted-foreground hover:text-foreground hover:border-border'
            } ${!voice.supported ? 'opacity-40 cursor-not-allowed' : ''}`}
            title={
              !voice.supported
                ? "This browser doesn't support live speech recognition"
                : voice.voiceEnabled
                  ? 'Mute mic'
                  : 'Unmute mic'
            }
          >
            {voice.isSpeaking
              ? <Volume2 className="w-5 h-5" />
              : voice.voiceEnabled
                ? <Mic className="w-5 h-5" />
                : <MicOff className="w-5 h-5" />}
          </button>

          {/* Transcript toggle — small button to hide/show status line */}
          <button
            onClick={() => setTranscriptVisible(v => !v)}
            className="absolute -bottom-7 left-1/2 -translate-x-1/2 text-[9px] font-mono text-muted-foreground/30 hover:text-muted-foreground/70 transition-colors whitespace-nowrap"
            title={transcriptVisible ? 'Hide transcript (pure voice mode)' : 'Show transcript'}
          >
            {transcriptVisible ? 'hide text' : 'show text'}
          </button>
        </div>
      </div>

      {/* MARK vitals — real numbers or nothing */}
      {selfState && (
        <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2.5 text-[10px] font-mono text-muted-foreground/60">
          <span>confidence {Math.round(selfState.confidence * 100)}%</span>
          <span className="text-border">·</span>
          <span>health {Math.round(selfState.health * 100)}%</span>
          <span className="text-border">·</span>
          <span className="truncate max-w-[140px]">{selfState.model}</span>
        </div>
      )}

      {/* ── Chat ──────────────────────────────────────────────────────────── */}
      {chatOpen ? (
        <div
          className="absolute inset-x-0 bottom-0 z-20 bg-background/95 backdrop-blur border-t border-border/50 shadow-2xl"
          style={{ height: '72%' }}
        >
          <button
            onClick={() => setChatOpen(false)}
            className="absolute -top-9 right-4 flex items-center gap-1 text-[11px] text-muted-foreground bg-card/80 hover:bg-card px-2.5 py-1.5 rounded-t border border-b-0 border-border/50 backdrop-blur"
          >
            <ChevronDown className="w-3.5 h-3.5" />
            Hide chat
          </button>
          <div className="h-full min-h-0">
            <ChatView />
          </div>
        </div>
      ) : (
        <button
          onClick={() => setChatOpen(true)}
          className="absolute bottom-4 right-4 z-20 flex items-center gap-1.5 text-[11px] text-muted-foreground/50 hover:text-muted-foreground bg-transparent hover:bg-card/40 px-2 py-1.5 rounded transition-colors"
          title="View chat with Elena"
        >
          <MessageCircle className="w-3.5 h-3.5" />
          <span>Chat</span>
        </button>
      )}
    </div>
  );
}
