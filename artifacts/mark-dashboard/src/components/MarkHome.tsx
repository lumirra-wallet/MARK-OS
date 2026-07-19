import { useState } from 'react';
import { ArrowRight, MessageCircle, ChevronDown, Mic, MicOff, Volume2 } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { useVoice } from '@/hooks/use-voice';
import { PresenceEngine } from './PresenceEngine';
import { ChatView } from './ChatView';
import { ApprovalsSidebar } from './ApprovalsSidebar';

/**
 * MARK's Home — the default view. Not "the dashboard, improved": Mission
 * Control (the Engineering Workspace) is now something opened from inside
 * MARK, the way Task Manager opens inside Windows, not the boot screen
 * itself. The owner should feel like they're watching MARK think, listen,
 * and speak — not looking at software update. See PresenceEngine.tsx for
 * how that's driven entirely by real runtime state, not decoration, and
 * use-voice.ts for the real microphone/speech pipeline behind it.
 *
 * Chat is deliberately not the dominant element here: it's a tap-to-reveal
 * panel, present but nearly invisible until asked for. Voice is the
 * intended primary interface — the mic button below is the prominent
 * control, not tucked away — but it's opt-in, never auto-started: browsers
 * require an explicit user gesture before granting microphone access, and
 * starting to listen without being asked would be a real consent problem
 * even if it weren't also technically blocked.
 */
export function MarkHome({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  const { pendingPermissions } = useMarkStore();
  const { selfState, modeLabel, activity } = useSelfState();
  const voice = useVoice();
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-background">
      <PresenceEngine
        className="absolute inset-0"
        micLevel={voice.micLevel}
        isListening={voice.isListening}
        isVoiceSpeaking={voice.isSpeaking}
      />

      {/* Safety-critical — never part of the "almost invisible" treatment */}
      {pendingPermissions.length > 0 && (
        <div className="absolute top-0 inset-x-0 z-30 border-b border-destructive/30 bg-destructive/10 backdrop-blur-sm">
          <ApprovalsSidebar />
        </div>
      )}

      {/* MARK's own label, over the core — not a header pill, a presence */}
      <div className="absolute top-8 inset-x-0 z-10 flex flex-col items-center gap-1 pointer-events-none">
        <h1 className="text-lg font-bold tracking-[0.2em] uppercase text-foreground/90">MARK</h1>
        <p className="text-sm text-muted-foreground">{modeLabel}</p>
        {activity && (
          <p className="text-xs text-muted-foreground/70 max-w-md text-center px-4 truncate">
            {activity}
          </p>
        )}
      </div>

      {/* Engineering Workspace — one explicit step away, not the default */}
      <button
        onClick={onOpenWorkspace}
        className="absolute top-4 right-4 z-10 flex items-center gap-1.5 text-[11px] font-mono bg-card/40 hover:bg-card/70 text-muted-foreground hover:text-foreground px-2.5 py-1.5 rounded border border-border/30 backdrop-blur-sm transition-colors"
        title="Open the Engineering Workspace — workers, timeline, git, terminal"
      >
        Engineering Workspace
        <ArrowRight className="w-3 h-3" />
      </button>

      {/* ── Voice — the primary interface, front and center ────────────────── */}
      <div className="absolute bottom-24 inset-x-0 z-10 flex flex-col items-center gap-2 pointer-events-none">
        {voice.voiceEnabled && (
          <p className="text-xs text-muted-foreground min-h-[1em] max-w-md text-center px-4 truncate">
            {voice.isSpeaking ? 'Speaking…' : voice.interimTranscript || (voice.isListening ? 'Listening…' : '')}
          </p>
        )}
        <button
          onClick={voice.toggleVoice}
          disabled={!voice.supported}
          className={`pointer-events-auto flex items-center justify-center w-14 h-14 rounded-full border transition-all ${
            voice.voiceEnabled
              ? 'bg-accent/20 border-accent text-accent shadow-lg shadow-accent/20'
              : 'bg-card/50 border-border/40 text-muted-foreground hover:text-foreground hover:border-border'
          } ${!voice.supported ? 'opacity-40 cursor-not-allowed' : ''}`}
          title={
            !voice.supported
              ? "This browser doesn't support live speech recognition"
              : voice.voiceEnabled
                ? 'Turn off voice — stop listening and speaking'
                : 'Talk to MARK — no need to open chat first'
          }
        >
          {voice.voiceEnabled
            ? (voice.isSpeaking ? <Volume2 className="w-5 h-5" /> : <Mic className="w-5 h-5" />)
            : <MicOff className="w-5 h-5" />}
        </button>
      </div>

      {/* MARK's vitals — quiet, bottom-left, real numbers or nothing */}
      {selfState && (
        <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2.5 text-[10px] font-mono text-muted-foreground/60">
          <span>confidence {Math.round(selfState.confidence * 100)}%</span>
          <span className="text-border">·</span>
          <span>health {Math.round(selfState.health * 100)}%</span>
          <span className="text-border">·</span>
          <span className="truncate max-w-[140px]">{selfState.model}</span>
        </div>
      )}

      {/* ── Chat — present, almost invisible, one tap away ────────────────── */}
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
          title="View chat with MARK"
        >
          <MessageCircle className="w-3.5 h-3.5" />
          <span>Chat</span>
        </button>
      )}
    </div>
  );
}
