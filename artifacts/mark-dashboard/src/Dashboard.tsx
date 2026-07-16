import React, { useEffect, useCallback } from 'react';
import { useMarkStore } from '@/store/markStore';
import {
  MessageSquare, Activity, FolderGit2, FileText, Cpu,
  LineChart, Settings, Clock, Plug, Unplug, Zap,
  Mic, AudioWaveform, Volume2, Square,
  GitBranch, Brain, Box, Workflow,
  Bookmark, Terminal, Briefcase, Wrench, Code2, Award, Stethoscope,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChatView }          from './components/ChatView';
import { ApprovalsSidebar } from './components/ApprovalsSidebar';
import { ExecutionView }     from './components/ExecutionView';
import { SettingsView }      from './components/SettingsView';
import { FilesView }         from './components/FilesView';
import { LogsView }          from './components/LogsView';
import { PerformanceView }   from './components/PerformanceView';
import { WorkersView }       from './components/WorkersView';
import { VoicePanel }        from './components/VoicePanel';
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
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { markApi, SystemMetrics } from '@/lib/markApi';

// ── Voice TopNav indicator ────────────────────────────────────────────────────

function VoiceMicIndicator() {
  const { voice } = useMarkStore();
  if (!voice.running) return null;

  const stateColors: Record<string, string> = {
    idle:         'text-muted-foreground',
    listening:    'text-emerald-400',
    transcribing: 'text-accent',
    speaking:     'text-blue-400',
    error:        'text-destructive',
  };
  const color = stateColors[voice.state] ?? 'text-muted-foreground';

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${color} select-none cursor-default`}>
          {voice.state === 'speaking'
            ? <Volume2       className="w-3.5 h-3.5 animate-pulse" />
            : voice.muted
              ? <Mic         className="w-3.5 h-3.5 opacity-40" />
              : <AudioWaveform className={`w-3.5 h-3.5 ${voice.state === 'listening' ? 'animate-pulse' : ''}`} />
          }
          <span className="hidden sm:inline capitalize">{voice.state}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        Voice · {voice.mode.replace(/_/g, ' ')} · {voice.state}
      </TooltipContent>
    </Tooltip>
  );
}

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

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const {
    connectWebSocket, connectionStatus,
    running, goal, workspace, elapsed,
    cancelRun, cancelRequested, voice,
    serverUrl,
  } = useMarkStore();

  const [activeTab,   setActiveTab]   = React.useState<string>('chat');
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
          <div className="flex items-center gap-1.5 shrink-0">
            <Zap className="w-4 h-4 text-accent" />
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

        {/* Right: metrics + voice + timer + status + stop */}
        <div className="flex items-center gap-2.5 shrink-0">
          <MetricsPill metrics={metrics} />
          <TokenBudgetPill />
          <VoiceMicIndicator />
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

      {/* ── MAIN LAYOUT ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left icon rail */}
        <aside className="w-14 shrink-0 border-r border-border/50 bg-sidebar flex flex-col items-center py-3 gap-1 overflow-y-auto">

          {/* PRIMARY: Chat */}
          <NavIcon icon={MessageSquare} active={activeTab === 'chat'}     onClick={() => setActiveTab('chat')}     tooltip="Chat"           glow={running} />

          <Divider />

          {/* Execution group */}
          <NavIcon icon={Activity}    active={activeTab === 'execution'}   onClick={() => setActiveTab('execution')}   tooltip="Execution" />
          <NavIcon icon={GitBranch}   active={activeTab === 'taskgraph'}   onClick={() => setActiveTab('taskgraph')}   tooltip="Task Graph" />
          <NavIcon icon={Workflow}    active={activeTab === 'pipeline'}    onClick={() => setActiveTab('pipeline')}    tooltip="Pipeline Graph" />
          <NavIcon icon={Cpu}         active={activeTab === 'workers'}     onClick={() => setActiveTab('workers')}     tooltip="Workers" />
          <NavIcon icon={Briefcase}   active={activeTab === 'jobs'}        onClick={() => setActiveTab('jobs')}        tooltip="Long Running Jobs" />

          <Divider />

          {/* Project group */}
          <NavIcon icon={FolderGit2}  active={activeTab === 'files'}      onClick={() => setActiveTab('files')}       tooltip="Files" />
          <NavIcon icon={FolderGit2}  active={activeTab === 'git'}        onClick={() => setActiveTab('git')}         tooltip="Git" />
          <NavIcon icon={FileText}    active={activeTab === 'logs'}        onClick={() => setActiveTab('logs')}        tooltip="Logs" />
          <NavIcon icon={Terminal}    active={activeTab === 'terminal'}    onClick={() => setActiveTab('terminal')}    tooltip="Terminal" />
          <NavIcon icon={Bookmark}    active={activeTab === 'checkpoints'} onClick={() => setActiveTab('checkpoints')} tooltip="Checkpoints" />

          <Divider />

          {/* Intelligence group */}
          <NavIcon icon={Brain}       active={activeTab === 'memory'}      onClick={() => setActiveTab('memory')}      tooltip="Memory" />
          <NavIcon icon={Box}         active={activeTab === 'models'}      onClick={() => setActiveTab('models')}      tooltip="Models" />
          <NavIcon icon={Code2}       active={activeTab === 'codeindex'}   onClick={() => setActiveTab('codeindex')}   tooltip="Codebase Index + RAG" />
          <NavIcon icon={Wrench}      active={activeTab === 'tools'}       onClick={() => setActiveTab('tools')}       tooltip="Tools & Plugins" />

          <Divider />

          {/* Observability group */}
          <NavIcon icon={Clock}        active={activeTab === 'timeline'}     onClick={() => setActiveTab('timeline')}     tooltip="Agent Timeline" />
          <NavIcon icon={Award}        active={activeTab === 'evaluation'}   onClick={() => setActiveTab('evaluation')}   tooltip="Run Evaluations" />
          <NavIcon icon={LineChart}    active={activeTab === 'performance'}  onClick={() => setActiveTab('performance')}  tooltip="Performance" />
          <NavIcon icon={Stethoscope} active={activeTab === 'diagnostics'}  onClick={() => setActiveTab('diagnostics')}  tooltip="Diagnostics" />

          {/* Voice */}
          <NavIcon
            icon={voice.running ? AudioWaveform : Mic}
            active={activeTab === 'voice'}
            onClick={() => setActiveTab('voice')}
            tooltip="Voice Settings"
            pulse={voice.running && voice.state === 'listening'}
            accent={voice.running}
          />

          <div className="mt-auto pt-2">
            <NavIcon icon={Settings} active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} tooltip="Settings" />
          </div>
        </aside>

        {/* Workspace panels */}
        <PanelGroup direction="horizontal" className="flex-1 bg-background">
          <Panel defaultSize={70} minSize={30} className="flex flex-col relative z-0">
            <div className="flex-1 overflow-hidden relative">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={activeTab}
                  className="absolute inset-0"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.1 }}
                >
                  {activeTab === 'chat'        && <ChatView />}
                  {activeTab === 'execution'   && <ExecutionView />}
                  {activeTab === 'taskgraph'   && <TaskGraphView />}
                  {activeTab === 'pipeline'    && <PipelineView />}
                  {activeTab === 'workers'     && <WorkersView />}
                  {activeTab === 'jobs'        && <JobsPanel />}
                  {activeTab === 'files'       && <FilesView />}
                  {activeTab === 'git'         && <GitPanel />}
                  {activeTab === 'logs'        && <LogsView />}
                  {activeTab === 'terminal'    && <LiveTerminal />}
                  {activeTab === 'checkpoints' && <CheckpointsPanel />}
                  {activeTab === 'memory'      && <MemoryPanel />}
                  {activeTab === 'models'      && <ModelsPanel />}
                  {activeTab === 'codeindex'   && <CodeIndexPanel />}
                  {activeTab === 'tools'       && <ToolsPanel />}
                  {activeTab === 'timeline'    && <TimelineView />}
                  {activeTab === 'evaluation'  && <EvaluationPanel />}
                  {activeTab === 'performance'  && <PerformanceView />}
                  {activeTab === 'diagnostics'  && <DiagnosticsView />}
                  {activeTab === 'voice'        && <VoicePanel />}
                  {activeTab === 'settings'     && <SettingsView />}
                </motion.div>
              </AnimatePresence>
            </div>
          </Panel>

          <PanelResizeHandle className="w-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-col-resize z-10">
            <div className="h-full w-full flex flex-col justify-center items-center">
              <div className="h-8 w-1 rounded-full bg-border" />
            </div>
          </PanelResizeHandle>

          <Panel defaultSize={30} minSize={20} className="flex flex-col border-l border-border/50 bg-card/30">
            <ApprovalsSidebar />
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Divider() {
  return <div className="w-6 h-px bg-border/40 my-1 shrink-0" />;
}

function NavIcon({
  icon: Icon, active, onClick, tooltip, pulse = false, accent = false, glow = false,
}: {
  icon: React.ComponentType<any>;
  active: boolean;
  onClick: () => void;
  tooltip: string;
  pulse?: boolean;
  accent?: boolean;
  glow?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={`relative w-10 h-10 rounded-xl flex items-center justify-center transition-all shrink-0
            ${active
              ? 'bg-accent text-accent-foreground shadow-md shadow-accent/20'
              : glow
                ? 'text-accent bg-accent/10 shadow-sm shadow-accent/10'
                : accent
                  ? 'text-emerald-400 hover:bg-emerald-400/10'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
        >
          <Icon style={{ width: 18, height: 18 }} />
          {pulse && (
            <motion.span
              className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-emerald-400"
              animate={{ scale: [1, 1.5, 1], opacity: [1, 0.4, 1] }}
              transition={{ duration: 1.2, repeat: Infinity }}
            />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" className="text-xs">{tooltip}</TooltipContent>
    </Tooltip>
  );
}
