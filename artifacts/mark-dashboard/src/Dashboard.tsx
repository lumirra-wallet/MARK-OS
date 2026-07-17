import React, { useEffect, useCallback, useState } from 'react';
import { useMarkStore } from '@/store/markStore';
import {
  Activity, FolderGit2,
  LineChart, Settings, Clock, Plug, Unplug,
  Square, GitBranch, Brain, Box, Workflow,
  Bookmark, Terminal, Briefcase, Wrench, Code2, Award, Stethoscope,
  Folder, FileText, Share2, MoreHorizontal,
} from 'lucide-react';
import { ChatView }          from './components/ChatView';
import { MarkAvatar, MarkAvatarState } from './components/MarkAvatar';
import { ApprovalsSidebar }  from './components/ApprovalsSidebar';
import { ExecutionView }     from './components/ExecutionView';
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
import { ProjectInspector }  from './components/ProjectInspector';
import { RepositorySummary } from './components/RepositorySummary';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { markApi, SystemMetrics } from '@/lib/markApi';

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
// Everything that isn't one of the seven always-visible mission-control
// panels (MARK's conversation, Active Workers, Engineering Timeline, Live
// Preview, Project Inspector, Repository Summary, Current Activity) lives
// here instead — not deleted, just not competing for primary screen space.
// See docs/mark-operating-system.md's "what still doesn't match" section.

const SECONDARY_TOOLS = [
  { id: 'execution',   label: 'Execution',          icon: Activity,     Component: ExecutionView },
  { id: 'taskgraph',   label: 'Task Graph',         icon: Share2,       Component: TaskGraphView },
  { id: 'pipeline',    label: 'Pipeline Graph',     icon: Workflow,     Component: PipelineView },
  { id: 'jobs',        label: 'Long Running Jobs',  icon: Briefcase,    Component: JobsPanel },
  { id: 'files',       label: 'Files',              icon: Folder,      Component: FilesView },
  { id: 'git',         label: 'Git (full detail)',  icon: GitBranch,    Component: GitPanel },
  { id: 'logs',        label: 'Logs',               icon: FileText,     Component: LogsView },
  { id: 'terminal',    label: 'Terminal',           icon: Terminal,     Component: LiveTerminal },
  { id: 'checkpoints', label: 'Checkpoints',        icon: Bookmark,     Component: CheckpointsPanel },
  { id: 'memory',      label: 'Engineering Memory', icon: Brain,        Component: MemoryPanel },
  { id: 'models',      label: 'Models',             icon: Box,          Component: ModelsPanel },
  { id: 'codeindex',   label: 'Codebase Index + RAG', icon: Code2,      Component: CodeIndexPanel },
  { id: 'tools',       label: 'Tools & Plugins',    icon: Wrench,       Component: ToolsPanel },
  { id: 'evaluation',  label: 'Run Evaluations',    icon: Award,        Component: EvaluationPanel },
  { id: 'performance', label: 'Performance',        icon: LineChart,    Component: PerformanceView },
  { id: 'diagnostics', label: 'Diagnostics',        icon: Stethoscope,  Component: DiagnosticsView },
  { id: 'settings',    label: 'Settings',           icon: Settings,     Component: SettingsView },
] as const;

function SecondaryToolsDrawer() {
  const [active, setActive] = useState<string>(SECONDARY_TOOLS[0].id);
  const Active = SECONDARY_TOOLS.find(t => t.id === active)?.Component ?? ExecutionView;

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
    messages,
  } = useMarkStore();

  const lastMsg = messages[messages.length - 1];
  const avatarState: MarkAvatarState =
    lastMsg?.role === 'mark' && lastMsg.isActive ? 'speaking' : running ? 'thinking' : 'idle';

  const [liveElapsed, setLiveElapsed] = React.useState(elapsed);
  const [metrics,     setMetrics]     = React.useState<SystemMetrics | null>(null);

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
      <header className="h-12 border-b border-border/50 bg-card/50 backdrop-blur shrink-0 flex items-center justify-between px-4 z-10 gap-3">

        {/* Left: logo + workspace + goal */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center gap-2 shrink-0">
            <MarkAvatar state={avatarState} size={22} />
            <span className="font-bold tracking-tight">MARK</span>
          </div>
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

      {/* ── MISSION-CONTROL WORKSPACE ─────────────────────────────────────────
           All seven panels are simultaneously mounted — no tab-switching, no
           navigation required to see what's happening. See
           docs/mark-operating-system.md. */}
      <PanelGroup direction="horizontal" className="flex-1 bg-background">

        {/* Column 1 — MARK's live conversation (the only conversational entity) */}
        <Panel defaultSize={40} minSize={26} className="flex flex-col relative z-0">
          {pendingPermissions.length > 0 && (
            <div className="border-b border-destructive/30 bg-destructive/5 shrink-0">
              <ApprovalsSidebar />
            </div>
          )}
          <div className="flex-1 min-h-0">
            <ChatView />
          </div>
        </Panel>

        <PanelResizeHandle className="w-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-col-resize z-10">
          <div className="h-full w-full flex flex-col justify-center items-center">
            <div className="h-8 w-1 rounded-full bg-border" />
          </div>
        </PanelResizeHandle>

        {/* Column 2 — Live Preview + Project Inspector */}
        <Panel defaultSize={30} minSize={20} className="flex flex-col border-l border-border/50 bg-card/20">
          <PanelGroup direction="vertical">
            <Panel defaultSize={60} minSize={25}>
              <PreviewWorkspace />
            </Panel>
            <PanelResizeHandle className="h-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-row-resize" />
            <Panel defaultSize={40} minSize={20}>
              <ProjectInspector />
            </Panel>
          </PanelGroup>
        </Panel>

        <PanelResizeHandle className="w-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-col-resize z-10">
          <div className="h-full w-full flex flex-col justify-center items-center">
            <div className="h-8 w-1 rounded-full bg-border" />
          </div>
        </PanelResizeHandle>

        {/* Column 3 — Active Workers · Engineering Timeline · Repository Summary */}
        <Panel defaultSize={30} minSize={20} className="flex flex-col border-l border-border/50 bg-card/30">
          <PanelGroup direction="vertical">
            <Panel defaultSize={34} minSize={15}>
              <WorkersView />
            </Panel>
            <PanelResizeHandle className="h-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-row-resize" />
            <Panel defaultSize={33} minSize={15}>
              <TimelineView />
            </Panel>
            <PanelResizeHandle className="h-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-row-resize" />
            <Panel defaultSize={33} minSize={15}>
              <RepositorySummary />
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
    </div>
  );
}
