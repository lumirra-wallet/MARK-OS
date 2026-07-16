import React, { useEffect } from 'react';
import { useMarkStore } from '@/store/markStore';
import {
  PanelLeftClose, PanelLeftOpen, Play, Square, Activity,
  FolderGit2, FileText, Cpu, LineChart, Settings, CheckCircle2,
  XCircle, AlertCircle, Clock, Plug, Unplug, Zap,
  Mic, MicOff, AudioWaveform, Volume2,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { TerminalPanel } from './components/TerminalPanel';
import { ApprovalsSidebar } from './components/ApprovalsSidebar';
import { MonacoEditorPanel } from './components/MonacoEditorPanel';
import { ExecutionView } from './components/ExecutionView';
import { SettingsView } from './components/SettingsView';
import { FilesView } from './components/FilesView';
import { LogsView } from './components/LogsView';
import { PerformanceView } from './components/PerformanceView';
import { WorkersView } from './components/WorkersView';
import { VoicePanel } from './components/VoicePanel';
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

// ── Voice state icon mapping ──────────────────────────────────────────────────

const VOICE_STATE_COLORS: Record<string, string> = {
  idle:         'text-muted-foreground',
  listening:    'text-emerald-400',
  transcribing: 'text-accent',
  thinking:     'text-purple-400',
  speaking:     'text-blue-400',
  error:        'text-destructive',
};

function VoiceMicIndicator() {
  const { voice } = useMarkStore();
  if (!voice.running) return null;

  const colorClass = VOICE_STATE_COLORS[voice.state] ?? 'text-muted-foreground';
  const isListening = voice.state === 'listening';

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={`flex items-center gap-1.5 text-sm font-medium ${colorClass} cursor-default select-none`}>
          <div className="relative">
            {isListening && (
              <motion.div
                className="absolute inset-0 rounded-full bg-emerald-400/30"
                animate={{ scale: [1, 1.8, 1], opacity: [0.5, 0, 0.5] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              />
            )}
            {voice.muted
              ? <MicOff className="w-4 h-4" />
              : voice.state === 'speaking'
                ? <Volume2 className={`w-4 h-4 ${voice.state === 'speaking' ? 'animate-pulse' : ''}`} />
                : <Mic className={`w-4 h-4 relative z-10 ${isListening ? 'animate-pulse' : ''}`} />
            }
          </div>
          <span className="text-xs capitalize hidden sm:inline">{voice.state}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        Voice: {voice.state} · Mode: {voice.mode.replace(/_/g, ' ')}
      </TooltipContent>
    </Tooltip>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const {
    connectWebSocket,
    connectionStatus,
    running,
    goal,
    workspace,
    elapsed,
    startRun,
    cancelRun,
    cancelRequested,
    voice,
  } = useMarkStore();

  const [activeTab, setActiveTab] = React.useState('execution');
  const [leftSidebarOpen, setLeftSidebarOpen] = React.useState(true);
  const [runGoal, setRunGoal] = React.useState('');
  const [runWorkspace, setRunWorkspace] = React.useState('');
  const [runModalOpen, setRunModalOpen] = React.useState(false);
  const [liveElapsed, setLiveElapsed] = React.useState(elapsed);

  useEffect(() => { connectWebSocket(); }, [connectWebSocket]);

  useEffect(() => {
    setLiveElapsed(elapsed);
    if (!running) return;
    const interval = setInterval(() => setLiveElapsed(prev => prev + 1), 1000);
    return () => clearInterval(interval);
  }, [running, elapsed]);

  // Auto-populate workspace from transcription (voice auto-submit)
  useEffect(() => {
    if (voice.transcript && !running) {
      setRunGoal(voice.transcript);
    }
  }, [voice.transcript, running]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const handleStart = (e: React.FormEvent) => {
    e.preventDefault();
    if (runGoal && runWorkspace) {
      startRun(runGoal, runWorkspace);
      setRunModalOpen(false);
      setActiveTab('execution');
    }
  };

  return (
    <div className="h-screen w-full flex flex-col bg-background text-foreground overflow-hidden font-sans">

      {/* ── TOP NAV ────────────────────────────────────────────────────────── */}
      <header className="h-14 border-b border-border/50 bg-card/50 backdrop-blur shrink-0 flex items-center justify-between px-4 z-10">
        <div className="flex items-center gap-3">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-accent" />
            <span className="font-bold tracking-tight text-lg">MARK</span>
          </div>

          <div className="h-4 w-px bg-border mx-1" />

          {/* Workspace */}
          {workspace ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground font-mono bg-muted/50 px-2.5 py-1 rounded-md border border-border/50">
              <FolderGit2 className="w-4 h-4 shrink-0" />
              <span className="max-w-[240px] truncate">{workspace}</span>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground italic">No active workspace</div>
          )}

          {/* Goal pill */}
          {goal && (
            <div className="hidden lg:flex items-center max-w-[360px]">
              <span className="text-sm truncate font-medium bg-accent/10 text-accent border border-accent/20 px-3 py-1 rounded-full">
                {goal}
              </span>
            </div>
          )}
        </div>

        {/* Right cluster */}
        <div className="flex items-center gap-3">
          {/* Voice indicator */}
          <VoiceMicIndicator />

          {voice.running && <div className="h-4 w-px bg-border" />}

          {/* Elapsed timer */}
          <div className="flex items-center gap-2 text-sm font-mono bg-muted/50 px-3 py-1 rounded border border-border/50">
            <Clock className={`w-4 h-4 ${running ? 'text-accent animate-pulse' : 'text-muted-foreground'}`} />
            {formatTime(liveElapsed)}
          </div>

          {/* Connection status */}
          <div className="flex items-center gap-2 text-sm font-medium">
            {connectionStatus === 'connected' ? (
              <span className="flex items-center gap-1.5 text-emerald-500">
                <Plug className="w-4 h-4" />
                <span className="hidden sm:inline">Connected</span>
              </span>
            ) : connectionStatus === 'connecting' ? (
              <span className="flex items-center gap-1.5 text-amber-500">
                <Activity className="w-4 h-4 animate-spin" />
                <span className="hidden sm:inline">Reconnecting</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-destructive">
                <Unplug className="w-4 h-4" />
                <span className="hidden sm:inline">Disconnected</span>
              </span>
            )}
          </div>

          <div className="h-4 w-px bg-border" />

          {/* Start / Stop */}
          {running ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={cancelRun}
              disabled={cancelRequested}
              className="font-mono text-xs gap-2 shadow-md shadow-destructive/20"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              {cancelRequested ? 'STOPPING…' : 'STOP RUN'}
            </Button>
          ) : (
            <Dialog open={runModalOpen} onOpenChange={setRunModalOpen}>
              <DialogTrigger asChild>
                <Button size="sm" className="bg-accent hover:bg-accent/90 text-accent-foreground font-mono text-xs gap-2 shadow-md shadow-accent/20">
                  <Play className="w-3.5 h-3.5 fill-current" />
                  START RUN
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-[440px]">
                <DialogHeader>
                  <DialogTitle>New Execution Run</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleStart} className="grid gap-4 py-4">
                  <div className="grid gap-2">
                    <Label htmlFor="workspace">Workspace Path</Label>
                    <Input
                      id="workspace"
                      value={runWorkspace}
                      onChange={e => setRunWorkspace(e.target.value)}
                      placeholder="/home/user/projects/myapp"
                      className="font-mono text-sm"
                      required
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="goal">Goal</Label>
                    <Input
                      id="goal"
                      value={runGoal}
                      onChange={e => setRunGoal(e.target.value)}
                      placeholder='e.g. "Build a REST API in Python"'
                      required
                    />
                    {voice.transcript && runGoal === voice.transcript && (
                      <p className="text-[11px] text-accent flex items-center gap-1">
                        <Mic className="w-3 h-3" /> Pre-filled from voice transcription
                      </p>
                    )}
                  </div>
                  <Button type="submit" className="w-full mt-2">
                    <Zap className="w-4 h-4 mr-2" />
                    Initialize MARK
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </header>

      {/* ── MAIN LAYOUT ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left sidebar (icon rail) */}
        <aside className={`w-14 shrink-0 border-r border-border/50 bg-sidebar flex flex-col items-center py-4 gap-1 transition-all duration-200 ${leftSidebarOpen ? '' : '-ml-14'}`}>
          <NavIcon icon={Activity}      active={activeTab === 'execution'}   onClick={() => setActiveTab('execution')}   tooltip="Execution" />
          <NavIcon icon={FolderGit2}    active={activeTab === 'files'}       onClick={() => setActiveTab('files')}       tooltip="Files" />
          <NavIcon icon={FileText}      active={activeTab === 'logs'}        onClick={() => setActiveTab('logs')}        tooltip="Logs" />
          <NavIcon icon={Cpu}           active={activeTab === 'workers'}     onClick={() => setActiveTab('workers')}     tooltip="Workers" />
          <NavIcon icon={LineChart}     active={activeTab === 'performance'} onClick={() => setActiveTab('performance')} tooltip="Performance" />

          {/* Voice tab — highlight when running */}
          <NavIcon
            icon={voice.running ? AudioWaveform : Mic}
            active={activeTab === 'voice'}
            onClick={() => setActiveTab('voice')}
            tooltip="Voice"
            pulse={voice.running && voice.state === 'listening'}
            accent={voice.running}
          />

          <div className="mt-auto flex flex-col items-center gap-1">
            <NavIcon icon={Settings} active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} tooltip="Settings" />
          </div>
        </aside>

        {/* Workspace area */}
        <PanelGroup direction="horizontal" className="flex-1 bg-background">
          <Panel defaultSize={70} minSize={30} className="flex flex-col relative z-0">
            <div className="flex-1 overflow-hidden relative">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={activeTab}
                  className="absolute inset-0"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.12 }}
                >
                  {activeTab === 'execution'   && <ExecutionView />}
                  {activeTab === 'files'       && <FilesView />}
                  {activeTab === 'logs'        && <LogsView />}
                  {activeTab === 'workers'     && <WorkersView />}
                  {activeTab === 'performance' && <PerformanceView />}
                  {activeTab === 'voice'       && <VoicePanel />}
                  {activeTab === 'settings'    && <SettingsView />}
                </motion.div>
              </AnimatePresence>
            </div>
          </Panel>

          <PanelResizeHandle className="w-1 bg-border/50 hover:bg-accent/50 transition-colors cursor-col-resize flex flex-col justify-center items-center group z-10">
            <div className="h-8 w-1 rounded-full bg-border group-hover:bg-accent transition-colors" />
          </PanelResizeHandle>

          <Panel defaultSize={30} minSize={20} className="flex flex-col border-l border-border/50 bg-card/30">
            <ApprovalsSidebar />
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}

// ── NavIcon helper ────────────────────────────────────────────────────────────

function NavIcon({
  icon: Icon,
  active,
  onClick,
  tooltip,
  pulse = false,
  accent = false,
}: {
  icon: React.ComponentType<any>;
  active: boolean;
  onClick: () => void;
  tooltip: string;
  pulse?: boolean;
  accent?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={`relative w-10 h-10 rounded-xl flex items-center justify-center transition-all
            ${active
              ? 'bg-accent text-accent-foreground shadow-md shadow-accent/20'
              : accent
                ? 'text-emerald-400 hover:bg-emerald-400/10'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
        >
          <Icon className="w-5 h-5" />
          {pulse && (
            <motion.span
              className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-emerald-400"
              animate={{ scale: [1, 1.5, 1], opacity: [1, 0.5, 1] }}
              transition={{ duration: 1.2, repeat: Infinity }}
            />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" className="text-xs">{tooltip}</TooltipContent>
    </Tooltip>
  );
}
