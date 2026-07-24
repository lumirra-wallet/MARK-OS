import React, { useEffect, useCallback, useState } from 'react';
import { useMarkStore } from '@/store/markStore';
import {
  Activity, FolderGit2,
  LineChart, Settings, Clock, Plug, Unplug,
  Square, GitBranch, Brain, Box, Workflow,
  Bookmark, Terminal, Briefcase, Wrench, Code2, Award, Stethoscope,
  Folder, FileText, Share2, MoreHorizontal, FlaskConical, Rocket,
  ArrowLeft,
} from 'lucide-react';
import { ChatView }          from './components/ChatView';
import { MarkPresence }      from './components/MarkPresence';
import { MarkHome }          from './components/MarkHome';
import { ApprovalsSidebar }  from './components/ApprovalsSidebar';
import { SettingsView }      from './components/SettingsView';
import { FilesView }         from './components/FilesView';
import { LogsView }          from './components/LogsView';
import { PerformanceView }   from './components/PerformanceView';
import { WorkersView }       from './components/WorkersView';
import { PipelineView }      from './components/PipelineView';
import { GitPanel }          from './components/GitPanel';
import { MemoryPanel }       from './components/MemoryPanel';
import { ModelsPanel }       from './components/ModelsPanel';
import { ToolsPanel }        from './components/ToolsPanel';
import { TimelineView }      from './components/TimelineView';
import { CheckpointsPanel }  from './components/CheckpointsPanel';
import { EvaluationPanel }   from './components/EvaluationPanel';
import { DiagnosticsView }   from './components/DiagnosticsView';
import { LiveTerminal }      from './components/LiveTerminal';
import { JobsPanel }         from './components/JobsPanel';
import { TaskGraphView }     from './components/TaskGraphView';
import { CodeIndexPanel }    from './components/CodeIndexPanel';
import { PreviewWorkspace }  from './components/PreviewWorkspace';
import {
  ProjectInspector, RunningAppsCard, GitStatusCard, ModelStatusCard,
} from './components/ProjectInspector';
import {
  RepositorySummary, ReasoningStepper, ActivityFeed, MemorySection,
} from './components/RepositorySummary';
import { CurrentProjectCard }  from './components/CurrentProjectCard';
import { TodaysProgressCard }  from './components/TodaysProgressCard';
import { CodingActivityCard }  from './components/CodingActivityCard';
import { WorkerPipeline }      from './components/WorkerPipeline';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { markApi, SystemMetrics } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';

// ── Token Budget pill (Feature 13) ───────────────────────────────────────────

function TokenBudgetPill() {
  const { tokenBudget } = useMarkStore();
  if (!tokenBudget.used) return null;
  const pct = Math.min(100, Math.round((tokenBudget.used / tokenBudget.window) * 100));
  const hot = pct > 80;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="hidden lg:flex items-center gap-1.5 text-[10px] font-mono bg-muted/40 px-2 py-1 rounded border border-border/40 select-none cursor-default">
          <span className={hot ? 'text-amber-400' : 'text-muted-foreground'}>
            Tokens {pct}%
          </span>
          <div className="w-12 h-1 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${hot ? 'bg-amber-400' : 'bg-accent'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        Token budget: {tokenBudget.used.toLocaleString()} / {tokenBudget.window.toLocaleString()} (~{pct}%)
      </TooltipContent>
    </Tooltip>
  );
}

// ── Metrics pill ──────────────────────────────────────────────────────────────

function MetricsPill({ metrics }: { metrics: SystemMetrics | null }) {
  if (!metrics || metrics.error) return null;
  const cpuHot = metrics.cpu_pct > 70;
  const memHot = metrics.mem_pct > 80;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="hidden lg:flex items-center gap-2 text-[10px] font-mono bg-muted/40 px-2 py-1 rounded border border-border/40 select-none cursor-default">
          <span className={cpuHot ? 'text-amber-400' : 'text-muted-foreground'}>CPU {metrics.cpu_pct}%</span>
          <span className="text-border">·</span>
          <span className={memHot ? 'text-amber-400' : 'text-muted-foreground'}>RAM {metrics.mem_pct}%</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        <div className="space-y-0.5">
          <div>CPU: {metrics.cpu_pct}%</div>
          <div>RAM: {metrics.mem_used_mb} MB / {metrics.mem_total_mb} MB ({metrics.mem_pct}%)</div>
          <div>Disk free: {metrics.disk_free_gb} GB</div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

// ── Secondary tools drawer ────────────────────────────────────────────────────
//
// Deeper/occasional tools that don't compete for primary Mission Control
// screen space. Everything the redesign brief named explicitly (MARK
// Conversation, Engineering Timeline, Mission Feed, Coding Activity, Current
// Project, Active Workers, Repository Summary, Today's Progress, Engineering
// Memory, Project Inspector, Running Apps, Live Preview, Git Status,
// Performance, Model Status, Terminal, Logs, Testing, Deployment) now lives
// in one of the four always-visible zones in Dashboard's body — see
// docs/mark-operating-system.md. What remains here are the disk-based
// memory-file browser, the full interactive git tool (stage/commit/branch/
// stash — Git Status in the Right zone is a read-only summary), the full
// model-switching UI (Model Status in the Right zone is read-only), and
// tools with no named zone in the brief.

const SECONDARY_TOOLS = [
  { id: 'taskgraph',   label: 'Task Graph',           icon: Share2,       Component: TaskGraphView },
  { id: 'pipeline',    label: 'Pipeline Graph',       icon: Workflow,     Component: PipelineView },
  { id: 'jobs',        label: 'Long Running Jobs',    icon: Briefcase,    Component: JobsPanel },
  { id: 'files',       label: 'Files',                icon: Folder,       Component: FilesView },
  { id: 'git',         label: 'Git (full detail)',    icon: GitBranch,    Component: GitPanel },
  { id: 'memory',      label: 'Memory Files',         icon: Brain,        Component: MemoryPanel },
  { id: 'models',      label: 'Models & Providers',   icon: Box,          Component: ModelsPanel },
  { id: 'codeindex',   label: 'Codebase Index + RAG', icon: Code2,        Component: CodeIndexPanel },
  { id: 'tools',       label: 'Tools & Plugins',      icon: Wrench,       Component: ToolsPanel },
  { id: 'evaluation',  label: 'Run Evaluations',      icon: Award,        Component: EvaluationPanel },
  { id: 'diagnostics', label: 'Diagnostics',          icon: Stethoscope,  Component: DiagnosticsView },
  { id: 'settings',    label: 'Settings',             icon: Settings,     Component: SettingsView },
] as const;

function SecondaryToolsDrawer() {
  const [active, setActive] = useState<string>(SECONDARY_TOOLS[0].id);
  const Active = SECONDARY_TOOLS.find(t => t.id === active)?.Component ?? SECONDARY_TOOLS[0].Component;

  return (
    <Sheet>
      <SheetTrigger asChild>
        <button
          className="flex items-center gap-1.5 text-xs font-mono bg-muted/40 hover:bg-muted/60 px-2.5 py-1.5 rounded border border-border/40 transition-colors"
          title="More tools — Files, Logs, Terminal, Models, and other deep-dive views"
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">More</span>
        </button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[85vw] sm:w-[720px] sm:max-w-none p-0 flex">
        {/* Mini icon rail — secondary tools only, not the primary workspace */}
        <div className="w-14 shrink-0 border-r border-border/50 bg-sidebar flex flex-col items-center py-3 gap-1 overflow-y-auto">
          {SECONDARY_TOOLS.map(tool => (
            <Tooltip key={tool.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setActive(tool.id)}
                  className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all shrink-0 ${
                    active === tool.id
                      ? 'bg-accent text-accent-foreground shadow-md shadow-accent/20'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`}
                >
                  <tool.icon style={{ width: 18, height: 18 }} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right" className="text-xs">{tool.label}</TooltipContent>
            </Tooltip>
          ))}
        </div>
        <div className="flex-1 min-w-0 flex flex-col">
          <SheetHeader className="px-4 py-3 border-b border-border/50">
            <SheetTitle className="text-sm">
              {SECONDARY_TOOLS.find(t => t.id === active)?.label}
            </SheetTitle>
          </SheetHeader>
          <div className="flex-1 min-h-0">
            <Active />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const {
    connectWebSocket, connectionStatus,
    running, goal, workspace, elapsed,
    cancelRun, cancelRequested,
    serverUrl, pendingPermissions,
  } = useMarkStore();

  const [liveElapsed, setLiveElapsed] = React.useState(elapsed);
  const [metrics,     setMetrics]     = React.useState<SystemMetrics | null>(null);

  // MARK's Home is the default view. The Engineering Workspace (everything
  // below the "MISSION-CONTROL WORKSPACE" block) is an application opened
  // from inside MARK, not the boot screen — see docs/mark-operating-system.md
  // and the Brain Ownership Architecture. Local, not persisted: every fresh
  // load starts at MARK, the way opening Windows doesn't resume Task Manager.
  const [view, setView] = useState<'home' | 'workspace'>('home');

  useEffect(() => { connectWebSocket(); }, [connectWebSocket]);

  // Elapsed timer
  useEffect(() => {
    setLiveElapsed(elapsed);
    if (!running) return;
    const t = setInterval(() => setLiveElapsed(p => p + 1), 1000);
    return () => clearInterval(t);
  }, [running, elapsed]);

  // Metrics polling (every 5 s)
  const fetchMetrics = useCallback(async () => {
    try {
      const m = await markApi.getMetrics(serverUrl);
      setMetrics(m);
    } catch { /* server may not be up yet */ }
  }, [serverUrl]);

  useEffect(() => {
    fetchMetrics();
    const id = setInterval(fetchMetrics, 5000);
    return () => clearInterval(id);
  }, [fetchMetrics]);

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

  return (
    <div className="h-screen w-full flex flex-col bg-background text-foreground overflow-hidden font-sans">

      {/* ── TOP NAV ────────────────────────────────────────────────────────── */}
      <header className="h-14 border-b border-border/50 bg-card/50 backdrop-blur shrink-0 flex items-center justify-between px-4 z-10 gap-3">

        {/* Left: MARK's real presence + workspace + goal */}
        <div className="flex items-center gap-3 min-w-0">
          <MarkPresence />
          {view === 'workspace' && (
            <button
              onClick={() => setView('home')}
              className="flex items-center gap-1.5 shrink-0 text-xs font-mono bg-muted/40 hover:bg-muted/60 px-2.5 py-1.5 rounded border border-border/40 transition-colors"
              title="Back to Elena"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Elena</span>
            </button>
          )}
          <div className="h-3.5 w-px bg-border shrink-0" />
          {workspace && (
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground font-mono bg-muted/40 px-2 py-0.5 rounded border border-border/40 max-w-[220px]">
              <FolderGit2 className="w-3 h-3 shrink-0" />
              <span className="truncate">{workspace}</span>
            </div>
          )}
          {running && goal && (
            <div className="hidden lg:block max-w-[280px]">
              <span className="text-xs truncate font-medium bg-accent/10 text-accent border border-accent/20 px-2.5 py-0.5 rounded-full">
                {goal}
              </span>
            </div>
          )}
        </div>

        {/* Right: metrics + timer + status + more-tools + stop */}
        <div className="flex items-center gap-2.5 shrink-0">
          <MetricsPill metrics={metrics} />
          <TokenBudgetPill />
          <div className="flex items-center gap-1.5 text-xs font-mono bg-muted/40 px-2.5 py-1 rounded border border-border/40">
            <Clock className={`w-3.5 h-3.5 ${running ? 'text-accent animate-pulse' : 'text-muted-foreground'}`} />
            {formatTime(liveElapsed)}
          </div>
          <div className="flex items-center gap-1.5 text-xs font-medium">
            {connectionStatus === 'connected' ? (
              <span className="flex items-center gap-1 text-emerald-500"><Plug className="w-3.5 h-3.5" /><span className="hidden sm:inline">Connected</span></span>
            ) : connectionStatus === 'connecting' ? (
              <span className="flex items-center gap-1 text-amber-500"><Activity className="w-3.5 h-3.5 animate-spin" /><span className="hidden sm:inline">Connecting</span></span>
            ) : (
              <span className="flex items-center gap-1 text-muted-foreground"><Unplug className="w-3.5 h-3.5" /><span className="hidden sm:inline">Disconnected</span></span>
            )}
          </div>
          <SecondaryToolsDrawer />
          {running && (
            <button
              onClick={cancelRun}
              disabled={cancelRequested}
              className="flex items-center gap-1.5 text-xs font-mono bg-destructive/20 hover:bg-destructive/30 text-destructive border border-destructive/30 px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50"
            >
              <Square className="w-3 h-3 fill-current" />
              {cancelRequested ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </header>

      {view === 'home' ? (
        <div className="flex-1 min-h-0 bg-background">
          <MarkHome onOpenWorkspace={() => setView('workspace')} />
        </div>
      ) : (
      /* ── ENGINEERING WORKSPACE — opened from inside MARK, not the boot ────
           screen. Four always-visible zones (Left / Center / Right / Bottom)
           — no tab-switching within it, no navigation required to see what's
           happening once you're here. See docs/mark-operating-system.md and
           the Brain Ownership Architecture. */
      <PanelGroup direction="vertical" className="flex-1 bg-background">
        <Panel defaultSize={76} minSize={45}>
          <PanelGroup direction="horizontal" className="h-full">

            {/* Left — Current Project · Active Workers · Repository Summary ·
                Today's Progress · Engineering Memory */}
            <Panel defaultSize={22} minSize={16} className="flex flex-col bg-card/20">
              <PanelGroup direction="vertical">
                <Panel defaultSize={42} minSize={20}>
                  <ScrollArea className="h-full">
                    <CurrentProjectCard />
                    <RepositorySummary />
                    <TodaysProgressCard />
                    <MemorySection />
                  </ScrollArea>
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={58} minSize={25}>
                  <WorkersView />
                </Panel>
              </PanelGroup>
            </Panel>

            <ColResizeHandle />

            {/* Center — MARK Conversation · Engineering Timeline · Mission
                Feed · Coding Activity */}
            <Panel defaultSize={46} minSize={30} className="flex flex-col relative z-0 border-l border-border/50">
              <PanelGroup direction="vertical">
                <Panel defaultSize={48} minSize={25} className="flex flex-col">
                  {pendingPermissions.length > 0 && (
                    <div className="border-b border-destructive/30 bg-destructive/5 shrink-0">
                      <ApprovalsSidebar />
                    </div>
                  )}
                  <div className="flex-1 min-h-0">
                    <ChatView />
                  </div>
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={28} minSize={15} className="flex flex-col border-t border-border/50">
                  <div className="px-3 pt-2 pb-1 shrink-0">
                    <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Engineering Timeline</h2>
                  </div>
                  <WorkerPipeline />
                  <ReasoningStepper />
                  <div className="flex-1 min-h-0 mt-2">
                    <TimelineView />
                  </div>
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={24} minSize={15} className="border-t border-border/50">
                  <ScrollArea className="h-full">
                    <div className="px-3 pt-2">
                      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Mission Feed</h2>
                    </div>
                    <ActivityFeed />
                    <CodingActivityCard />
                  </ScrollArea>
                </Panel>
              </PanelGroup>
            </Panel>

            <ColResizeHandle />

            {/* Right — Project Inspector · Running Apps · Live Preview ·
                Git Status · Performance · Model Status */}
            <Panel defaultSize={32} minSize={22} className="flex flex-col border-l border-border/50 bg-card/20">
              <PanelGroup direction="vertical">
                <Panel defaultSize={34} minSize={18}>
                  <PreviewWorkspace />
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={22} minSize={15}>
                  <ScrollArea className="h-full">
                    <div className="p-3 flex flex-col gap-3">
                      <RunningAppsCard />
                      <ModelStatusCard />
                    </div>
                  </ScrollArea>
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={24} minSize={15}>
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      <GitStatusCard />
                    </div>
                  </ScrollArea>
                </Panel>
                <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize" />
                <Panel defaultSize={20} minSize={15}>
                  <ProjectInspector />
                </Panel>
              </PanelGroup>
            </Panel>
          </PanelGroup>
        </Panel>

        <PanelResizeHandle className="h-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-row-resize z-10">
          <div className="w-full h-full flex items-center justify-center">
            <div className="w-8 h-1 rounded-full bg-border" />
          </div>
        </PanelResizeHandle>

        {/* Bottom — Terminal · Logs · Testing · Deployment */}
        <Panel defaultSize={24} minSize={12} className="border-t border-border/50 bg-card/30">
          <PanelGroup direction="horizontal" className="h-full">
            <Panel defaultSize={30} minSize={15} className="flex flex-col">
              <BottomZoneLabel icon={Terminal} label="Terminal" />
              <div className="flex-1 min-h-0 p-2">
                <LiveTerminal />
              </div>
            </Panel>
            <ColResizeHandle />
            <Panel defaultSize={25} minSize={15} className="flex flex-col">
              <LogsView />
            </Panel>
            <ColResizeHandle />
            <Panel defaultSize={20} minSize={12} className="flex flex-col">
              <BottomZoneLabel icon={FlaskConical} label="Testing" />
              <TestingZone />
            </Panel>
            <ColResizeHandle />
            <Panel defaultSize={25} minSize={15} className="flex flex-col">
              <BottomZoneLabel icon={Rocket} label="Deployment & Checkpoints" />
              <div className="flex-1 min-h-0">
                <CheckpointsPanel />
              </div>
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
      )}
    </div>
  );
}

// ── Shared layout bits ───────────────────────────────────────────────────────

function ColResizeHandle() {
  return (
    <PanelResizeHandle className="w-1 bg-border/50 hover:bg-primary/50 transition-colors cursor-col-resize z-10">
      <div className="h-full w-full flex flex-col justify-center items-center">
        <div className="h-8 w-1 rounded-full bg-border" />
      </div>
    </PanelResizeHandle>
  );
}

function BottomZoneLabel({ icon: Icon, label }: { icon: React.ComponentType<any>; label: string }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border/40 shrink-0">
      <Icon className="w-3.5 h-3.5 text-primary" />
      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
    </div>
  );
}

function TestingZone() {
  const { lastTestRun } = useMarkStore();
  const statusStyle: Record<string, string> = {
    passed:  'bg-success/20 text-success border-success-border',
    failed:  'bg-destructive/20 text-destructive border-destructive/30',
    running: 'bg-primary/20 text-primary border-primary-border',
    idle:    'bg-muted text-muted-foreground border-border',
  };
  return (
    <div className="flex-1 min-h-0 flex flex-col p-2.5 gap-2 overflow-hidden">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`text-[10px] px-2 py-0.5 rounded font-mono uppercase tracking-wider border ${statusStyle[lastTestRun.status]}`}>
          {lastTestRun.status}
        </span>
        {lastTestRun.timestamp && (
          <span className="text-[10px] text-muted-foreground">
            {new Date(lastTestRun.timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>
      <ScrollArea className="flex-1 min-h-0">
        {lastTestRun.output ? (
          <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-all">{lastTestRun.output}</pre>
        ) : (
          <span className="text-xs text-muted-foreground italic">No test output yet</span>
        )}
      </ScrollArea>
    </div>
  );
}
