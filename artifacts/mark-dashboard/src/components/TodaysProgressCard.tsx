/**
 * TodaysProgressCard — the Left-zone "Today's Progress" widget. Derived
 * entirely from existing engineeringMemory/activityFeed state — no new
 * backend plumbing.
 */
import { CheckCircle2, ListChecks } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';

function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function TodaysProgressCard() {
  const { engineeringMemory, activityFeed } = useMarkStore();
  const milestones = engineeringMemory.completedMilestones ?? [];
  const completed  = milestones.filter(m => m.completed).length;
  const total      = milestones.length;
  const pct        = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 bg-card/60 px-3 py-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          <ListChecks className="w-3.5 h-3.5" />
          Today's Progress
        </div>
        {total > 0 && (
          <span className="text-[10px] font-mono text-primary">{completed}/{total}</span>
        )}
      </div>

      {total > 0 ? (
        <div className="mt-2 h-1.5 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-primary glow-sm transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : (
        <p className="mt-1.5 text-xs text-muted-foreground italic">No milestones yet this session</p>
      )}

      <div className="flex items-center gap-3 mt-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3 text-success" />
          {activityFeed.length} action{activityFeed.length !== 1 ? 's' : ''}
        </span>
        {engineeringMemory.sessionElapsed > 0 && (
          <span>{formatElapsed(engineeringMemory.sessionElapsed)} this session</span>
        )}
      </div>
    </div>
  );
}
