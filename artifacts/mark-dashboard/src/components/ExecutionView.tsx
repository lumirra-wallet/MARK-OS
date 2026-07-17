import { useMarkStore } from '@/store/markStore';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, CircleDashed, Loader2, Play, Circle, Sparkles, Code2, TestTube2, Eye, GitBranch, Bug, Shield, FileText, Camera } from 'lucide-react';
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { TerminalPanel } from './TerminalPanel';
import { ScrollArea } from '@/components/ui/scroll-area';
import { format } from 'date-fns';

const WORKER_ICONS = {
  Engineer: Code2,
  QA: TestTube2,
  Debugger: Bug,
  Reviewer: Eye,
  Git: GitBranch,
  Research: Sparkles,
  Security: Shield,
  Docs: FileText,
  Preview: Camera,
};

export function ExecutionView() {
  const { workers, currentWorker, streamingTokens, timeline, running, cancelRequested } = useMarkStore();

  return (
    <PanelGroup direction="vertical" className="h-full">
      <Panel defaultSize={60} minSize={30} className="flex flex-col bg-background">
        
        {/* TOP STATUS ROW */}
        <div className="h-24 border-b border-border/50 p-6 flex flex-col justify-center relative overflow-hidden bg-card/30">
          <div className="absolute right-0 top-0 w-64 h-full bg-gradient-to-l from-accent/5 to-transparent pointer-events-none" />
          
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold tracking-tight">Execution Plan</h2>
              <div className="text-sm text-muted-foreground flex items-center gap-2 mt-1">
                {running ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin text-accent" />
                    <span>MARK is active</span>
                  </>
                ) : cancelRequested ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin text-destructive" />
                    <span className="text-destructive">Cancelling run...</span>
                  </>
                ) : (
                  <>
                    <Circle className="w-4 h-4 text-muted-foreground" />
                    <span>Idle. Waiting for instructions.</span>
                  </>
                )}
              </div>
            </div>
            
            {running && (
              <div className="text-right">
                <div className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">Generated</div>
                <div className="text-2xl font-mono text-accent">
                  {(streamingTokens.length).toLocaleString()} <span className="text-sm text-muted-foreground">chars</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* WORKER GRAPH PIPELINE */}
        <div className="p-6 border-b border-border/50 bg-card/10 overflow-x-auto">
          <div className="flex items-center gap-2 min-w-max">
            {workers.map((worker, index) => {
              const Icon = (WORKER_ICONS as any)[worker.name] || CircleDashed;
              const isRunning = worker.status === 'running';
              const isDone = worker.status === 'success';
              const isFailed = worker.status === 'failed';
              
              return (
                <div key={worker.name} className="flex items-center">
                  <motion.div 
                    layout
                    className={`
                      relative flex items-center gap-3 px-4 py-2.5 rounded-full border
                      ${isRunning ? 'bg-accent/10 border-accent/30 text-accent shadow-[0_0_15px_rgba(var(--accent),0.2)]' : ''}
                      ${isDone ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400' : ''}
                      ${isFailed ? 'bg-destructive/10 border-destructive/30 text-destructive' : ''}
                      ${worker.status === 'idle' ? 'bg-muted/30 border-transparent text-muted-foreground opacity-50' : ''}
                    `}
                    animate={{
                      scale: isRunning ? 1.05 : 1,
                    }}
                    transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                  >
                    {isRunning && (
                      <motion.div 
                        className="absolute inset-0 rounded-full border border-accent/50"
                        animate={{ opacity: [0, 1, 0], scale: [1, 1.1, 1.2] }}
                        transition={{ repeat: Infinity, duration: 2 }}
                      />
                    )}
                    
                    {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : 
                     isDone ? <CheckCircle2 className="w-4 h-4" /> : 
                     <Icon className="w-4 h-4" />}
                    
                    <span className="text-sm font-semibold tracking-wide">{worker.name}</span>
                  </motion.div>
                  
                  {index < workers.length - 1 && (
                    <div className="w-8 flex items-center justify-center">
                      <div className={`h-px w-full ${isDone ? 'bg-emerald-500/50' : 'bg-border'}`} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* CURRENT WORKER DETAIL & TIMELINE SPLIT */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* CURRENT WORKER DETAIL */}
          <div className="w-1/2 border-r border-border/50 p-6 flex flex-col overflow-hidden">
            <h3 className="text-xs uppercase tracking-widest text-muted-foreground font-semibold mb-4">Current Focus</h3>
            
            {currentWorker ? (
              <div className="flex flex-col gap-4">
                {workers.find(w => w.name === currentWorker)?.task && (
                  <div className="bg-muted/30 rounded-xl p-4 border border-border/50">
                    <div className="text-xs text-muted-foreground mb-1 font-mono uppercase">Executing Task</div>
                    <div className="text-sm">{workers.find(w => w.name === currentWorker)?.task}</div>
                  </div>
                )}
                
                {workers.find(w => w.name === currentWorker)?.thought && (
                  <div className="bg-accent/5 rounded-xl p-4 border border-accent/10">
                    <div className="text-xs text-accent mb-1 font-mono uppercase flex items-center gap-2">
                      <Sparkles className="w-3 h-3" /> MARK is thinking
                    </div>
                    <div className="text-sm italic text-foreground/80 leading-relaxed">
                      "{workers.find(w => w.name === currentWorker)?.thought}"
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm italic opacity-50">
                No active worker
              </div>
            )}
          </div>

          {/* TIMELINE */}
          <div className="w-1/2 flex flex-col overflow-hidden bg-card/20">
            <div className="px-6 pt-6 pb-2 shrink-0">
              <h3 className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">Event Timeline</h3>
            </div>
            <ScrollArea className="flex-1 px-6">
              <div className="py-2 flex flex-col gap-4">
                <AnimatePresence initial={false}>
                  {timeline.map((event, i) => (
                    <motion.div
                      key={event.id}
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="flex gap-4 relative"
                    >
                      {/* Timeline line */}
                      {i !== timeline.length - 1 && (
                        <div className="absolute left-[3.5px] top-4 bottom-[-16px] w-px bg-border/50 z-0" />
                      )}
                      
                      <div className="mt-1 w-2 h-2 rounded-full bg-border shrink-0 z-10 ring-4 ring-background" />
                      
                      <div className="flex flex-col flex-1 pb-1">
                        <div className="text-xs text-muted-foreground font-mono">
                          {format(new Date(event.timestamp || Date.now()), 'HH:mm:ss.SSS')}
                        </div>
                        <div className="text-sm mt-0.5 leading-snug">
                          {event.message}
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
                {timeline.length === 0 && (
                  <div className="text-sm text-muted-foreground italic text-center mt-10 opacity-50">
                    Waiting for events...
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        </div>

      </Panel>

      <PanelResizeHandle className="h-1 bg-border/50 hover:bg-accent/50 transition-colors z-10 cursor-row-resize flex justify-center items-center group">
        <div className="w-8 h-1 rounded-full bg-border group-hover:bg-accent transition-colors" />
      </PanelResizeHandle>

      <Panel defaultSize={40} minSize={20} className="border-t border-border">
        <TerminalPanel />
      </Panel>
    </PanelGroup>
  );
}