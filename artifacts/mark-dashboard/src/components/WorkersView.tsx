import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, FileEdit, Clock } from 'lucide-react';
import { useMarkStore, WorkerState } from '@/store/markStore';
import { cn } from '@/lib/utils';

const STATUS_STYLE: Record<WorkerState['status'], string> = {
  running: 'bg-accent/20 text-accent border-accent/30',
  success: 'bg-emerald-500/20 text-emerald-500 border-emerald-500/30',
  failed:  'bg-destructive/20 text-destructive border-destructive/30',
  idle:    'bg-muted text-muted-foreground border-border',
  skipped: 'bg-muted/50 text-muted-foreground border-border/50 border-dashed',
};

function formatRuntime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function WorkerCard({ worker }: { worker: WorkerState }) {
  const [expanded, setExpanded] = useState(worker.status === 'running');
  const [runtime, setRuntime]   = useState(0);

  useEffect(() => {
    if (worker.status !== 'running' || !worker.startedAt) return;
    const started = new Date(worker.startedAt).getTime();
    const tick = () => setRuntime((Date.now() - started) / 1000);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [worker.status, worker.startedAt]);

  useEffect(() => {
    if (worker.status === 'running') setExpanded(true);
  }, [worker.status]);

  const files = worker.filesTouched ?? [];

  return (
    <motion.div
      layout
      className="bg-card border border-border/50 rounded-xl shadow-sm overflow-hidden"
    >
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between gap-3 p-4 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          {worker.status === 'running' && (
            <motion.span
              className="w-1.5 h-1.5 rounded-full bg-accent shrink-0"
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.2, repeat: Infinity }}
            />
          )}
          <h3 className="font-semibold truncate">{worker.name}</h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn('text-[10px] px-2 py-0.5 rounded font-mono uppercase tracking-wider border', STATUS_STYLE[worker.status])}>
            {worker.status}
          </span>
          <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.15 }}>
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          </motion.span>
        </div>
      </button>

      {/* Progress bar — always visible for running/success workers */}
      {(worker.status === 'running' || worker.status === 'success') && (
        <div className="px-4 pb-2">
          <div className="h-1 rounded-full bg-muted overflow-hidden">
            <motion.div
              className={cn('h-full rounded-full', worker.status === 'success' ? 'bg-emerald-500' : 'bg-accent')}
              initial={{ width: 0 }}
              animate={{ width: `${worker.progress ?? (worker.status === 'success' ? 100 : 0)}%` }}
              transition={{ duration: 0.3 }}
            />
          </div>
        </div>
      )}

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 flex flex-col gap-3 border-t border-border/30 pt-3">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Current Task</div>
                <div className="text-sm min-h-[1.25rem]">
                  {worker.task || <span className="text-muted-foreground italic">None</span>}
                </div>
              </div>

              {worker.thought && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">Last Thought</div>
                  <div className="text-sm italic text-foreground/80 break-words">{worker.thought}</div>
                </div>
              )}

              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                {worker.startedAt && (
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {worker.status === 'running' ? formatRuntime(runtime) : 'done'}
                  </span>
                )}
                <span className="flex items-center gap-1">
                  <FileEdit className="w-3 h-3" />
                  {files.length} file{files.length !== 1 ? 's' : ''} touched
                </span>
              </div>

              {files.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {files.map(f => (
                    <span key={f} className="text-[10px] font-mono bg-muted/50 border border-border/40 rounded px-1.5 py-0.5 truncate max-w-[180px]">
                      {f}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export function WorkersView() {
  const { workers } = useMarkStore();

  return (
    <div className="h-full p-3 flex flex-col gap-3 bg-background overflow-y-auto">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground shrink-0">
        Active Workers
      </h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {workers.map(worker => (
          <WorkerCard key={worker.name} worker={worker} />
        ))}
      </div>
    </div>
  );
}
