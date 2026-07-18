/**
 * CodingActivityCard — Center-zone "Coding Activity" widget. Sourced from
 * filesInRun, already tracked in the store for every active/last run —
 * no new plumbing.
 */
import { FilePlus, FileEdit, FileMinus } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { cn } from '@/lib/utils';

const OP_CONFIG = {
  created:  { icon: FilePlus, color: 'text-success' },
  modified: { icon: FileEdit, color: 'text-primary' },
  deleted:  { icon: FileMinus, color: 'text-destructive' },
} as const;

export function CodingActivityCard() {
  const { filesInRun } = useMarkStore();

  if (filesInRun.length === 0) {
    return (
      <div className="mx-3 mt-3 mb-3 rounded-xl border border-border/50 bg-card/40 px-3 py-4 text-center">
        <span className="text-xs text-muted-foreground italic">No files touched yet</span>
      </div>
    );
  }

  const counts = filesInRun.reduce(
    (acc, f) => ({ ...acc, [f.operation]: (acc[f.operation] ?? 0) + 1 }),
    {} as Record<string, number>,
  );

  return (
    <div className="mx-3 mt-3 mb-3 rounded-xl border border-border/50 bg-card/40 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Coding Activity</span>
        <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
          {(['created', 'modified', 'deleted'] as const).map(op =>
            counts[op] ? (
              <span key={op} className={cn('flex items-center gap-0.5', OP_CONFIG[op].color)}>
                {counts[op]}{op[0]}
              </span>
            ) : null,
          )}
        </div>
      </div>
      <div className="max-h-32 overflow-y-auto p-1.5 space-y-0.5">
        {filesInRun.slice(-10).reverse().map(f => {
          const cfg = OP_CONFIG[f.operation];
          const Icon = cfg.icon;
          return (
            <div key={f.path} className="flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[11px] font-mono truncate">
              <Icon className={cn('w-3 h-3 shrink-0', cfg.color)} />
              <span className="truncate text-foreground/80">{f.path}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
