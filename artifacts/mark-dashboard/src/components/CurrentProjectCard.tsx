/**
 * CurrentProjectCard — the Left-zone "Current Project" widget. Compact by
 * design: workspace name, project type, and MARK's current status/goal.
 * Deeper detail lives in the Repository Summary widget right below it.
 */
import { FolderGit2, Circle } from 'lucide-react';
import { useMarkStore } from '@/store/markStore';

export function CurrentProjectCard() {
  const { workspace, workspaceContext, running, goal } = useMarkStore();

  const name = workspace?.split('/').filter(Boolean).pop() || workspace || 'No workspace';

  return (
    <div className="mx-3 mt-3 rounded-xl border border-border/50 bg-card/60 px-3 py-2.5">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <FolderGit2 className="w-4 h-4 text-primary shrink-0" />
        <span className="truncate">{name}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
        {running ? (
          <>
            <span className="relative flex h-2 w-2 shrink-0">
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary glow-sm" />
            </span>
            <span className="truncate text-foreground/80">{goal || 'Working…'}</span>
          </>
        ) : (
          <>
            <Circle className="w-2 h-2 text-faint-foreground shrink-0" />
            <span>{workspaceContext?.projectType ?? 'Idle'}</span>
          </>
        )}
      </div>
    </div>
  );
}
