/**
 * RepositorySummary — "Repository Summary" + "Current Engineering Activity",
 * two of the always-visible mission-control panels (see docs/mark-operating-
 * system.md and Dashboard.tsx). Extracted from the retired LiveEngineerPanel.tsx
 * (Narration transcript dropped — see that doc's narration removal).
 *
 * Sections:
 *   Workspace context  — project type, git branch, test status, TODOs
 *   Reasoning stage    — visual phase stepper (current engineering activity)
 *   Activity feed      — real-time action log
 *   Memory             — goals, milestones, blockers
 *   Suggestions        — proactive idle improvements
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, ChevronUp,
  FolderGit2, GitBranch, TestTube2, Cpu,
  CheckCircle2, Circle, Loader2, AlertTriangle,
  Zap, FileText, Terminal, GitCommit, Search, FilePlus,
  Trash2, Pencil, Shield, Lightbulb, Activity, Brain,
  RefreshCw, X, Bug, Eye, Rocket,
} from 'lucide-react';
import { useMarkStore, ReasoningStage } from '@/store/markStore';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGES: { id: ReasoningStage; label: string; icon: React.ComponentType<any> }[] = [
  { id: 'analyzing',   label: 'Analyze',  icon: Search       },
  { id: 'planning',    label: 'Plan',     icon: Brain        },
  { id: 'writing',     label: 'Write',    icon: FilePlus     },
  { id: 'running',     label: 'Run',      icon: Terminal     },
  { id: 'testing',     label: 'Test',     icon: TestTube2    },
  { id: 'reviewing',   label: 'Review',   icon: Eye          },
  { id: 'committing',  label: 'Commit',   icon: GitCommit    },
  { id: 'deploying',   label: 'Deploy',   icon: Rocket       },
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

// ── Workspace context card (Repository Summary) ───────────────────────────────

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

// ── Reasoning stage stepper (current engineering activity, at a glance) ──────

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

export function RepositorySummary() {
  return (
    <ScrollArea className="h-full">
      <div className="pb-3">
        <WorkspaceCard />
        <ReasoningStepper />
        <ActivityFeed />
        <MemorySection />
        <IdleSuggestions />
      </div>
    </ScrollArea>
  );
}
