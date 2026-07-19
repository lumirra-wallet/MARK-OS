import { useSelfState } from '@/hooks/use-self-state';
import { MarkAvatar } from './MarkAvatar';

/**
 * MARK's real presence, compact form — used in chrome that's visible
 * regardless of which view (Home or the Engineering Workspace) is active.
 * See use-self-state.ts for the shared polling/derivation logic; see
 * MarkHome.tsx for the large form used as MARK's actual home screen.
 */
export function MarkPresence() {
  const { avatarState, modeLabel, activity } = useSelfState();

  return (
    <div className="flex items-center gap-2 min-w-0">
      <MarkAvatar state={avatarState} size={26} />
      <div className="min-w-0 leading-tight">
        <div className="flex items-center gap-1.5">
          <span className="font-bold tracking-tight text-sm">MARK</span>
          <span className="text-[10px] font-mono text-muted-foreground">· {modeLabel}</span>
        </div>
        {activity && (
          <div
            className="text-[10px] text-muted-foreground truncate max-w-[220px]"
            title={activity}
          >
            {activity}
          </div>
        )}
      </div>
    </div>
  );
}
