/**
 * WorkerPipeline — the live "MARK delegates to Worker" animation. Extracted
 * from the retired ExecutionView.tsx's pill-row, generalized for the Center
 * zone's Engineering Timeline. Purely a view over existing `workers`/
 * `currentWorker` store state — no new plumbing.
 */
import { motion } from 'framer-motion';
import {
  CheckCircle2, CircleDashed, Loader2, Circle,
  Sparkles, Code2, TestTube2, Eye, GitBranch, Bug, Shield, FileText, Camera,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { cn } from '@/lib/utils';

const WORKER_ICONS: Record<string, React.ComponentType<any>> = {
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

export function WorkerPipeline() {
  const { workers } = useMarkStore();

  return (
    <div className="px-3 py-2 overflow-x-auto">
      <div className="flex items-center gap-1.5 min-w-max">
        {workers.map((worker, index) => {
          const Icon = WORKER_ICONS[worker.name] || CircleDashed;
          const isRunning = worker.status === 'running';
          const isDone    = worker.status === 'success';
          const isFailed  = worker.status === 'failed';

          return (
            <div key={worker.name} className="flex items-center">
              <motion.div
                layout
                className={cn(
                  'relative flex flex-col gap-1 px-3 py-1.5 rounded-xl border min-w-[92px]',
                  isRunning && 'bg-primary/10 border-primary-border text-primary glow-primary',
                  isDone    && 'bg-success/10 border-success-border text-success',
                  isFailed  && 'bg-destructive/10 border-destructive/30 text-destructive',
                  worker.status === 'idle' && 'bg-muted/30 border-transparent text-muted-foreground opacity-50',
                )}
                animate={{ scale: isRunning ? 1.05 : 1 }}
                transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              >
                {isRunning && (
                  <motion.div
                    className="absolute inset-0 rounded-xl border border-primary/50"
                    animate={{ opacity: [0, 1, 0], scale: [1, 1.06, 1.1] }}
                    transition={{ repeat: Infinity, duration: 2 }}
                  />
                )}

                <div className="flex items-center gap-1.5">
                  {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> :
                   isDone    ? <CheckCircle2 className="w-3.5 h-3.5" /> :
                   isFailed  ? <Circle className="w-3.5 h-3.5" /> :
                   <Icon className="w-3.5 h-3.5" />}
                  <span className="text-xs font-semibold tracking-wide">{worker.name}</span>
                </div>

                {(isRunning || isDone) && (
                  <div className="h-1 rounded-full bg-muted overflow-hidden">
                    <motion.div
                      className={cn('h-full rounded-full', isDone ? 'bg-success' : 'bg-primary')}
                      initial={{ width: 0 }}
                      animate={{ width: `${worker.progress ?? (isDone ? 100 : 0)}%` }}
                      transition={{ duration: 0.3 }}
                    />
                  </div>
                )}
              </motion.div>

              {index < workers.length - 1 && (
                <div className="w-4 flex items-center justify-center">
                  <div className={cn('h-px w-full', isDone ? 'bg-success/50' : 'bg-border')} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
