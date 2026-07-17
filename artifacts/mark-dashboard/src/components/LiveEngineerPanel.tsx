/**
 * LiveEngineerPanel — MARK's persistent engineering partner panel.
 *
 * Sections:
 *   Voice bar          — mute, pause/resume, voice selector, speed
 *   Workspace context  — project type, git branch, test status, TODOs
 *   Reasoning stage    — visual phase stepper
 *   Narration          — live scrolling transcript of what MARK is saying
 *   Activity feed      — real-time action log
 *   Memory             — goals, milestones, blockers
 *   Suggestions        — proactive idle improvements
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Volume2, VolumeX, Pause, Play, ChevronDown, ChevronUp,
  FolderGit2, GitBranch, TestTube2, MessageSquare, Cpu,
  CheckCircle2, Circle, Loader2, AlertTriangle,
  Zap, FileText, Terminal, GitCommit, Search, FilePlus,
  Trash2, Pencil, Shield, Lightbulb, Activity, Brain,
  RefreshCw, X, Bug,
} from 'lucide-react';
import { useMarkStore, ActivityEntry, NarrationEntry, ReasoningStage } from '@/store/markStore';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { ApprovalsSidebar } from './ApprovalsSidebar';

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGES: { id: ReasoningStage; label: string; icon: React.ComponentType<any> }[] = [
  { id: 'analyzing',   label: 'Analyze',  icon: Search    },
  { id: 'planning',    label: 'Plan',     icon: Brain     },
  { id: 'writing',     label: 'Write',    icon: FilePlus  },
  { id: 'running',     label: 'Run',      icon: Terminal  },
  { id: 'testing',     label: 'Test',     icon: TestTube2 },
  { id: 'committing',  label: 'Commit',   icon: GitCommit },
  { id: 'done',        label: 'Done',     icon: CheckCircle2 },
];

const STAGE_ORDER = STAGES.map(s => s.id);

// ── Activity type config ──────────────────────────────────────────────────────

const ACTIVITY_CONFIG: Record<string, { icon: React.ComponentType<any>; color: string; label: string }> = {
  write:    { icon: FilePlus,    color: 'text-emerald-400', label: 'Wrote'    },
  read:     { icon: FileText,    color: 'text-blue-400',    label: 'Read'     },
  run:      { icon: Terminal,    color: 'text-amber-400',   label: 'Ran'      },
  test:     { icon: TestTube2,   color: 'text-purple-400',  label: 'Tested'   },
  commit:   { icon: GitCommit,   color: 'text-accent',      label: 'Committed'},
  plan:     { icon: Brain,       color: 'text-pink-400',    label: 'Planned'  },
  analyze:  { icon: Search,      color: 'text-sky-400',     label: 'Analyzed' },
  search:   { icon: Search,      color: 'text-sky-400',     label: 'Searched' },
  git:      { icon: GitBranch,   color: 'text-orange-400',  label: 'Git'      },
  rename:   { icon: Pencil,      color: 'text-violet-400',  label: 'Renamed'  },
  delete:   { icon: Trash2,      color: 'text-destructive', label: 'Deleted'  },
  suggest:  { icon: Lightbulb,   color: 'text-yellow-400',  label: 'Suggest'  },
  error:    { icon: Bug,         color: 'text-destructive', label: 'Error'    },
};

const getActivityConfig = (type: string) =>
  ACTIVITY_CONFIG[type] ?? { icon: Activity, color: 'text-muted-foreground', label: type };

// ── Suggestion category config ────────────────────────────────────────────────

const SUGGESTION_CONFIG: Record<string, { icon: React.ComponentType<any>; color: string }> = {
  'missing-tests': { icon: TestTube2,     color: 'text-purple-400'  },
  'security':      { icon: Shield,        color: 'text-destructive' },
  'performance':   { icon: Zap,           color: 'text-amber-400'   },
  'docs':          { icon: FileText,      color: 'text-blue-400'    },
  'duplicate-code':{ icon: RefreshCw,     color: 'text-orange-400'  },
  'dependency':    { icon: AlertTriangle, color: 'text-yellow-400'  },
};

// ── OpenAI voice options ───────────────────────────────────────────────────────

const OPENAI_VOICES = [
  { value: 'nova',    label: 'Nova — warm, conversational' },
  { value: 'alloy',   label: 'Alloy — neutral, clear' },
  { value: 'echo',    label: 'Echo — deep, confident' },
  { value: 'fable',   label: 'Fable — expressive, British' },
  { value: 'onyx',    label: 'Onyx — authoritative' },
  { value: 'shimmer', label: 'Shimmer — bright, energetic' },
];

// ── Voice controls ────────────────────────────────────────────────────────────

function VoiceBar() {
  const { voice, toggleMute, setTtsProvider, setOpenaiVoice, speak } = useMarkStore();
  const [paused, setPaused] = useState(false);

  const handlePauseResume = () => {
    if (paused) { speechSynthesis.resume(); setPaused(false); }
    else        { speechSynthesis.pause();  setPaused(true);  }
  };

  const stateIcon = voice.state === 'speaking'
    ? <Volume2 className="w-3.5 h-3.5 text-blue-400 animate-pulse" />
    : voice.muted
      ? <VolumeX className="w-3.5 h-3.5 text-muted-foreground" />
      : <Volume2 className="w-3.5 h-3.5 text-emerald-400" />;

  const isOpenAI = voice.ttsProvider === 'openai';

  return (
    <div className="border-b border-border/40 bg-card/50 text-xs">
      {/* Top row: status + provider toggle + controls */}
      <div className="flex items-center gap-2 px-3 py-1.5">
        <div className="flex items-center gap-1.5 text-muted-foreground shrink-0">
          {stateIcon}
          <span className="font-medium text-foreground/70">Narration</span>
        </div>

        {/* Provider toggle */}
        <div className="flex items-center bg-muted/40 border border-border/40 rounded overflow-hidden text-[10px] shrink-0">
          <button
            onClick={() => setTtsProvider('browser')}
            className={cn(
              "px-2 py-0.5 transition-colors",
              !isOpenAI ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground hover:text-foreground",
            )}
          >
            Browser
          </button>
          <button
            onClick={() => setTtsProvider('openai')}
            className={cn(
              "px-2 py-0.5 transition-colors",
              isOpenAI ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground hover:text-foreground",
            )}
          >
            OpenAI
          </button>
        </div>

        <div className="flex-1" />

        {/* Pause/resume (browser only) */}
        {!isOpenAI && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handlePauseResume}
                className="p-1 rounded hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
              >
                {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">{paused ? 'Resume' : 'Pause'}</TooltipContent>
          </Tooltip>
        )}

        {/* Mute */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => toggleMute()}
              className={cn(
                "p-1 rounded hover:bg-muted/60 transition-colors",
                voice.muted ? "text-destructive/70" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {voice.muted ? <VolumeX className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">{voice.muted ? 'Unmute' : 'Mute'}</TooltipContent>
        </Tooltip>
      </div>

      {/* OpenAI voice selector row */}
      {isOpenAI && (
        <div className="flex items-center gap-2 px-3 pb-1.5">
          <select
            value={voice.openaiVoice}
            onChange={e => setOpenaiVoice(e.target.value)}
            className="flex-1 bg-muted/40 border border-border/40 rounded px-1.5 py-0.5 text-[10px] text-foreground/80"
          >
            {OPENAI_VOICES.map(v => (
              <option key={v.value} value={v.value}>{v.label}</option>
            ))}
          </select>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => speak('Hello, I\'m MARK, your AI software engineer.')}
                className="shrink-0 px-2 py-0.5 rounded bg-muted/60 hover:bg-muted text-muted-foreground hover:text-foreground transition-colors text-[10px]"
              >
                Test
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">Play a test phrase</TooltipContent>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

// ── Workspace context card ────────────────────────────────────────────────────

function WorkspaceCard() {
  const { workspaceContext } = useMarkStore();
  const [open, setOpen] = useState(true);

  if (!workspaceContext) return null;

  const { projectType, frameworks, gitBranch, testFramework, todoCount, fileCount, lastCommit } = workspaceContext;

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 bg-card/60 overflow-hidden text-xs">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/20 transition-colors"
      >
        <div className="flex items-center gap-2 font-medium text-foreground/80">
          <FolderGit2 className="w-3.5 h-3.5 text-accent shrink-0" />
          <span className="truncate">{projectType}{frameworks.length > 0 ? ` · ${frameworks.slice(0,2).join(' / ')}` : ''}</span>
        </div>
        {open ? <ChevronUp className="w-3 h-3 text-muted-foreground shrink-0" /> : <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 pt-0 grid grid-cols-2 gap-1.5">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <GitBranch className="w-3 h-3" />
                <span className="font-mono truncate">{gitBranch}</span>
              </div>
              {testFramework && (
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <TestTube2 className="w-3 h-3" />
                  <span>{testFramework}</span>
                </div>
              )}
              {todoCount > 0 && (
                <div className="flex items-center gap-1.5 text-amber-400/80">
                  <AlertTriangle className="w-3 h-3" />
                  <span>{todoCount} TODO{todoCount !== 1 ? 's' : ''}</span>
                </div>
              )}
              {fileCount > 0 && (
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <FileText className="w-3 h-3" />
                  <span>{fileCount} files</span>
                </div>
              )}
              {lastCommit && (
                <div className="col-span-2 flex items-start gap-1.5 text-muted-foreground mt-0.5">
                  <GitCommit className="w-3 h-3 shrink-0 mt-0.5" />
                  <span className="truncate italic">{lastCommit}</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Reasoning stage stepper ───────────────────────────────────────────────────

function ReasoningStepper() {
  const { reasoningStage, running } = useMarkStore();

  if (!running && reasoningStage === 'idle') return null;

  const currentIdx = STAGE_ORDER.indexOf(reasoningStage ?? 'idle');

  return (
    <div className="mx-3 mt-3 px-3 py-2.5 rounded-xl border border-border/50 bg-card/60">
      <div className="flex items-center justify-between">
        {STAGES.map((stage, idx) => {
          const Icon = stage.icon;
          const done    = idx < currentIdx;
          const active  = idx === currentIdx;
          const pending = idx > currentIdx;

          return (
            <React.Fragment key={stage.id}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className={cn(
                    "flex flex-col items-center gap-1",
                    done    && "text-emerald-400",
                    active  && "text-accent",
                    pending && "text-muted-foreground/40",
                  )}>
                    <div className={cn(
                      "w-6 h-6 rounded-full flex items-center justify-center border transition-all",
                      done   && "bg-emerald-400/15 border-emerald-400/50",
                      active && "bg-accent/20 border-accent shadow-sm shadow-accent/30",
                      pending && "bg-transparent border-border/30",
                    )}>
                      {active && running
                        ? <Loader2 className="w-3 h-3 animate-spin" />
                        : <Icon style={{ width: 12, height: 12 }} />
                      }
                    </div>
                    <span className="text-[9px] font-medium leading-none hidden xl:block">
                      {stage.label}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs">{stage.label}</TooltipContent>
              </Tooltip>
              {idx < STAGES.length - 1 && (
                <div className={cn(
                  "flex-1 h-px mx-0.5 transition-colors",
                  idx < currentIdx ? "bg-emerald-400/40" : "bg-border/30",
                )} />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ── Narration transcript ──────────────────────────────────────────────────────

function NarrationTranscript() {
  const { narrationTranscript } = useMarkStore();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (scrollRef.current && !collapsed) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [narrationTranscript, collapsed]);

  if (narrationTranscript.length === 0) return null;

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 overflow-hidden bg-card/40">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/20 transition-colors text-xs"
      >
        <div className="flex items-center gap-2 font-medium text-foreground/70">
          <MessageSquare className="w-3.5 h-3.5 text-blue-400" />
          <span>Narration</span>
          <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4 font-mono">
            {narrationTranscript.length}
          </Badge>
        </div>
        {collapsed ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronUp className="w-3 h-3 text-muted-foreground" />}
      </button>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }}
            transition={{ duration: 0.2 }} className="overflow-hidden"
          >
            <div ref={scrollRef} className="overflow-y-auto max-h-32 px-3 pb-2 space-y-1">
              {narrationTranscript.slice(-8).map(entry => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={cn(
                    "text-[11px] leading-snug",
                    entry.type === 'stage'      && "text-accent font-medium",
                    entry.type === 'summary'    && "text-emerald-400 font-medium",
                    entry.type === 'suggestion' && "text-amber-400",
                    entry.type === 'action'     && "text-foreground/70",
                  )}
                >
                  {entry.type === 'stage' && '▸ '}
                  {entry.type === 'summary' && '✓ '}
                  {entry.text}
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Activity feed ─────────────────────────────────────────────────────────────

function ActivityFeed() {
  const { activityFeed, running } = useMarkStore();
  const [limit, setLimit] = useState(15);

  const visible = activityFeed.slice(0, limit);

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 overflow-hidden bg-card/40 flex-1 min-h-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30 text-xs">
        <div className="flex items-center gap-2 font-medium text-foreground/70">
          <Activity className="w-3.5 h-3.5 text-accent" />
          <span>Activity</span>
          {activityFeed.length > 0 && (
            <Badge variant="secondary" className="text-[9px] px-1.5 py-0 h-4 font-mono">
              {activityFeed.length}
            </Badge>
          )}
        </div>
        {running && (
          <div className="flex items-center gap-1 text-[10px] text-emerald-400">
            <motion.span
              className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.2, repeat: Infinity }}
            />
            LIVE
          </div>
        )}
      </div>

      <ScrollArea className="h-48">
        <div className="p-2 space-y-0.5">
          <AnimatePresence mode="popLayout">
            {visible.length === 0 ? (
              <div className="text-center py-6 text-xs text-muted-foreground/50">
                Activity will appear here during a run
              </div>
            ) : (
              visible.map(entry => {
                const cfg = getActivityConfig(entry.type);
                const Icon = cfg.icon;
                const ts   = new Date(entry.timestamp);
                const timeStr = `${ts.getHours().toString().padStart(2,'0')}:${ts.getMinutes().toString().padStart(2,'0')}:${ts.getSeconds().toString().padStart(2,'0')}`;

                return (
                  <motion.div
                    key={entry.id}
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    layout
                    className="flex items-start gap-2 px-1.5 py-1 rounded-lg hover:bg-muted/20 transition-colors group"
                  >
                    <Icon className={cn("w-3.5 h-3.5 mt-0.5 shrink-0", cfg.color)} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-1.5">
                        <span className="text-[11px] text-foreground/85 leading-snug truncate">
                          {entry.text}
                        </span>
                        {entry.success === false && (
                          <Badge variant="destructive" className="text-[9px] px-1 py-0 h-3.5 shrink-0">err</Badge>
                        )}
                      </div>
                      {entry.detail && (
                        <p className="text-[10px] text-muted-foreground/60 truncate mt-0.5">
                          {entry.detail}
                        </p>
                      )}
                    </div>
                    <span className="text-[9px] font-mono text-muted-foreground/40 shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      {timeStr}
                    </span>
                  </motion.div>
                );
              })
            )}
          </AnimatePresence>
          {activityFeed.length > limit && (
            <button
              onClick={() => setLimit(l => l + 20)}
              className="w-full text-center text-[10px] text-muted-foreground/50 hover:text-muted-foreground py-1.5 transition-colors"
            >
              Show {Math.min(20, activityFeed.length - limit)} more…
            </button>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// ── Engineering memory ────────────────────────────────────────────────────────

function MemorySection() {
  const { engineeringMemory } = useMarkStore();
  const [open, setOpen] = useState(true);

  const { currentGoal, completedMilestones: milestones = [], blockers = [] } = engineeringMemory;
  const hasContent = currentGoal || milestones.length > 0 || blockers.length > 0;
  if (!hasContent) return null;

  const completed = milestones.filter(m => m.completed);
  const pending   = milestones.filter(m => !m.completed);

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 bg-card/40 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/20 transition-colors text-xs"
      >
        <div className="flex items-center gap-2 font-medium text-foreground/70">
          <Brain className="w-3.5 h-3.5 text-pink-400" />
          <span>Memory</span>
        </div>
        {open ? <ChevronUp className="w-3 h-3 text-muted-foreground" /> : <ChevronDown className="w-3 h-3 text-muted-foreground" />}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-1.5 text-xs">
              {currentGoal && (
                <div className="flex items-start gap-1.5 text-accent">
                  <Zap className="w-3 h-3 mt-0.5 shrink-0" />
                  <span className="font-medium">{currentGoal}</span>
                </div>
              )}
              {completed.map((m, i) => (
                <div key={i} className="flex items-start gap-1.5 text-emerald-400/80">
                  <CheckCircle2 className="w-3 h-3 mt-0.5 shrink-0" />
                  <span>{m.text}</span>
                </div>
              ))}
              {pending.map((m, i) => (
                <div key={i} className="flex items-start gap-1.5 text-muted-foreground/60">
                  <Circle className="w-3 h-3 mt-0.5 shrink-0" />
                  <span>{m.text}</span>
                </div>
              ))}
              {blockers.map((b, i) => (
                <div key={i} className="flex items-start gap-1.5 text-destructive/70">
                  <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                  <span>{b.text}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Idle suggestions ──────────────────────────────────────────────────────────

function IdleSuggestions() {
  const { idleSuggestions } = useMarkStore();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const visible = idleSuggestions.filter(s => !dismissed.has(s.id));
  if (visible.length === 0) return null;

  return (
    <div className="mx-3 mt-3 mb-1 rounded-xl border border-amber-400/20 bg-amber-400/5 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-amber-400/15 text-xs">
        <div className="flex items-center gap-2 font-medium text-amber-400/80">
          <Lightbulb className="w-3.5 h-3.5" />
          <span>Suggestions</span>
          <Badge className="text-[9px] px-1.5 py-0 h-4 bg-amber-400/15 text-amber-400 border-amber-400/30">
            {visible.length}
          </Badge>
        </div>
      </div>
      <div className="p-2 space-y-1">
        {visible.slice(0, 5).map(s => {
          const cfg = SUGGESTION_CONFIG[s.category] ?? { icon: Lightbulb, color: 'text-amber-400' };
          const Icon = cfg.icon;
          return (
            <div
              key={s.id}
              className="flex items-start gap-2 px-1.5 py-1 rounded-lg hover:bg-amber-400/5 group"
            >
              <Icon className={cn("w-3.5 h-3.5 mt-0.5 shrink-0", cfg.color)} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className={cn(
                    "text-[10px] font-medium",
                    s.priority === 'high'   && "text-destructive/80",
                    s.priority === 'medium' && "text-amber-400/80",
                    s.priority === 'low'    && "text-foreground/60",
                  )}>
                    {s.title}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground/60 mt-0.5 leading-snug">
                  {s.description}
                </p>
              </div>
              <button
                onClick={() => setDismissed(d => new Set([...d, s.id]))}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 hover:text-foreground text-muted-foreground"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function LiveEngineerPanel() {
  const { pendingPermissions, running } = useMarkStore();

  return (
    <div className="h-full flex flex-col bg-sidebar/30 overflow-hidden">
      {/* Voice bar */}
      <VoiceBar />

      {/* Scrollable content */}
      <ScrollArea className="flex-1">
        <div className="pb-3">
          {/* Workspace context */}
          <WorkspaceCard />

          {/* Reasoning stage */}
          <ReasoningStepper />

          {/* Narration transcript */}
          <NarrationTranscript />

          {/* Activity feed */}
          <ActivityFeed />

          {/* Engineering memory */}
          <MemorySection />

          {/* Idle suggestions */}
          <IdleSuggestions />
        </div>
      </ScrollArea>

      {/* Approvals overlay — shows when permissions are pending */}
      {pendingPermissions.length > 0 && (
        <div className="border-t border-destructive/30 bg-destructive/5">
          <ApprovalsSidebar />
        </div>
      )}
    </div>
  );
}
