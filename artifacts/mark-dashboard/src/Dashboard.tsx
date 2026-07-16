import React, { useEffect } from 'react';
import { useMarkStore } from '@/store/markStore';
import { PanelLeftClose, PanelLeftOpen, Play, Square, Activity, FolderGit2, FileText, Cpu, LineChart, Settings, CheckCircle2, XCircle, AlertCircle, Clock, Plug, Unplug, Zap } from 'lucide-react';
import { format } from 'date-fns';
import { TerminalPanel } from './components/TerminalPanel';
import { ApprovalsSidebar } from './components/ApprovalsSidebar';
import { MonacoEditorPanel } from './components/MonacoEditorPanel';
import { ExecutionView } from './components/ExecutionView';
import { SettingsView } from './components/SettingsView';
import { FilesView } from './components/FilesView';
import { LogsView } from './components/LogsView';
import { PerformanceView } from './components/PerformanceView';
import { WorkersView } from './components/WorkersView';
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

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
    cancelRequested 
  } = useMarkStore();

  const [activeTab, setActiveTab] = React.useState('execution');
  const [leftSidebarOpen, setLeftSidebarOpen] = React.useState(true);
  const [runGoal, setRunGoal] = React.useState('');
  const [runWorkspace, setRunWorkspace] = React.useState('');
  const [runModalOpen, setRunModalOpen] = React.useState(false);
  const [liveElapsed, setLiveElapsed] = React.useState(elapsed);

  useEffect(() => {
    connectWebSocket();
  }, [connectWebSocket]);

  useEffect(() => {
    setLiveElapsed(elapsed);
    if (!running) return;
    
    const interval = setInterval(() => {
      setLiveElapsed(prev => prev + 1);
    }, 1000);
    
    return () => clearInterval(interval);
  }, [running, elapsed]);

  // Format elapsed time (seconds -> MM:SS)
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
      {/* TOP NAV BAR */}
      <header className="h-14 border-b border-border/50 bg-card/50 backdrop-blur shrink-0 flex items-center justify-between px-4 z-10">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-accent" />
            <span className="font-bold tracking-tight text-lg">MARK</span>
          </div>
          
          <div className="h-4 w-px bg-border mx-2"></div>
          
          {workspace ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground font-mono bg-muted/50 px-2.5 py-1 rounded-md border border-border/50">
              <FolderGit2 className="w-4 h-4" />
              {workspace}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground italic">No active workspace</div>
          )}
          
          {goal && (
            <div className="hidden lg:flex items-center max-w-[400px]">
              <span className="text-sm truncate font-medium bg-accent/10 text-accent border border-accent/20 px-3 py-1 rounded-full">
                {goal}
              </span>
            </div>
          )}
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm font-mono bg-muted/50 px-3 py-1 rounded border border-border/50">
            <Clock className={`w-4 h-4 ${running ? 'text-accent animate-pulse' : 'text-muted-foreground'}`} />
            {formatTime(liveElapsed)}
          </div>
          
          <div className="flex items-center gap-2 text-sm font-medium">
            {connectionStatus === 'connected' ? (
              <span className="flex items-center gap-1.5 text-emerald-500">
                <Plug className="w-4 h-4" /> Connected
              </span>
            ) : connectionStatus === 'connecting' ? (
              <span className="flex items-center gap-1.5 text-amber-500">
                <Activity className="w-4 h-4 animate-spin" /> Reconnecting
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-destructive">
                <Unplug className="w-4 h-4" /> Disconnected
              </span>
            )}
          </div>
          
          <div className="h-4 w-px bg-border mx-2"></div>
          
          {running ? (
            <Button 
              variant="destructive" 
              size="sm" 
              onClick={cancelRun} 
              disabled={cancelRequested}
              className="font-mono text-xs gap-2 shadow-md shadow-destructive/20"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              {cancelRequested ? 'STOPPING...' : 'STOP RUN'}
            </Button>
          ) : (
            <Dialog open={runModalOpen} onOpenChange={setRunModalOpen}>
              <DialogTrigger asChild>
                <Button size="sm" className="bg-accent hover:bg-accent/90 text-accent-foreground font-mono text-xs gap-2 shadow-md shadow-accent/20">
                  <Play className="w-3.5 h-3.5 fill-current" />
                  START RUN
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                  <DialogTitle>New Execution Run</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleStart} className="grid gap-4 py-4">
                  <div className="grid gap-2">
                    <Label htmlFor="workspace">Workspace Path</Label>
                    <Input 
                      id="workspace" 
                      value={runWorkspace} 
                      onChange={(e) => setRunWorkspace(e.target.value)} 
                      placeholder="/home/runner/workspace" 
                      className="font-mono text-sm"
                      required
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="goal">Goal</Label>
                    <Input 
                      id="goal" 
                      value={runGoal} 
                      onChange={(e) => setRunGoal(e.target.value)} 
                      placeholder="e.g. Build a snake game in python" 
                      required
                    />
                  </div>
                  <Button type="submit" className="w-full mt-2">Initialize MARK</Button>
                </form>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </header>

      {/* MAIN LAYOUT */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* LEFT SIDEBAR (ICONS) */}
        <aside className={`w-14 shrink-0 border-r border-border/50 bg-sidebar flex flex-col items-center py-4 gap-4 transition-all ${leftSidebarOpen ? 'ml-0' : '-ml-14'}`}>
          <NavIcon icon={Activity} active={activeTab === 'execution'} onClick={() => setActiveTab('execution')} tooltip="Execution" />
          <NavIcon icon={FolderGit2} active={activeTab === 'files'} onClick={() => setActiveTab('files')} tooltip="Files" />
          <NavIcon icon={FileText} active={activeTab === 'logs'} onClick={() => setActiveTab('logs')} tooltip="Logs" />
          <NavIcon icon={Cpu} active={activeTab === 'workers'} onClick={() => setActiveTab('workers')} tooltip="Workers" />
          <NavIcon icon={LineChart} active={activeTab === 'performance'} onClick={() => setActiveTab('performance')} tooltip="Performance" />
          
          <div className="mt-auto mb-2 flex flex-col items-center gap-4">
            <NavIcon icon={Settings} active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} tooltip="Settings" />
          </div>
        </aside>

        {/* WORKSPACE AREA (Resizable Panels) */}
        <PanelGroup direction="horizontal" className="flex-1 w-full bg-background">
          <Panel defaultSize={70} minSize={30} className="flex flex-col relative z-0">
            {/* TABS CONTENT */}
            <div className="flex-1 overflow-hidden relative">
              {activeTab === 'execution' && <ExecutionView />}
              {activeTab === 'files' && <FilesView />}
              {activeTab === 'logs' && <LogsView />}
              {activeTab === 'workers' && <WorkersView />}
              {activeTab === 'performance' && <PerformanceView />}
              {activeTab === 'settings' && <SettingsView />}
            </div>
          </Panel>

          <PanelResizeHandle className="w-1 bg-border/50 hover:bg-accent/50 transition-colors z-10 cursor-col-resize flex flex-col justify-center items-center group">
            <div className="h-8 w-1 rounded-full bg-border group-hover:bg-accent transition-colors" />
          </PanelResizeHandle>

          <Panel defaultSize={30} minSize={20} className="flex flex-col border-l border-border/50 bg-card/30">
            <ApprovalsSidebar />
          </Panel>
        </PanelGroup>
      </div>

      {/* BOTTOM TERMINAL PANEL (Fixed / Resizable via absolute positioning if needed, but lets just make it fixed height or resizable from bottom of ExecutionView) */}
      {/* Wait, the requirement says "Resizable panel height with a drag handle". We can wrap the main layout and terminal in a Vertical PanelGroup */}
      
    </div>
  );
}

function NavIcon({ icon: Icon, active, onClick, tooltip }: { icon: any, active: boolean, onClick: () => void, tooltip: string }) {
  return (
    <button 
      onClick={onClick}
      title={tooltip}
      className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${active ? 'bg-accent text-accent-foreground shadow-md shadow-accent/20' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
    >
      <Icon className="w-5 h-5" />
    </button>
  );
}