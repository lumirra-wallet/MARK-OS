import { useEffect, useState } from 'react';
import { useMarkStore } from '@/store/markStore';
import { markApi, SelfState } from '@/lib/markApi';
import { MarkAvatar, MarkAvatarState } from './MarkAvatar';

// MARK's actual internal state machine (smartagent/mind/state/state_machine.py)
// has more modes than the avatar's three visual states — map them rather than
// widen the avatar, so the animation stays simple and legible.
const MODE_TO_AVATAR: Record<string, MarkAvatarState> = {
  idle: 'idle', listening: 'idle', waiting: 'idle', sleeping: 'idle', error: 'idle',
  thinking: 'thinking', planning: 'thinking', researching: 'thinking',
  executing: 'thinking', reflecting: 'thinking', learning: 'thinking', recovering: 'thinking',
};

const MODE_LABEL: Record<string, string> = {
  idle: 'Idle', listening: 'Listening', thinking: 'Thinking', planning: 'Planning',
  researching: 'Researching', executing: 'Working', reflecting: 'Reflecting',
  learning: 'Learning', waiting: 'Waiting', sleeping: 'Resting',
  error: 'Recovering', recovering: 'Recovering',
};

/**
 * MARK's real presence in the header — replaces a locally-guessed avatar
 * state with agent.mind's actual mode/activity from GET /self-state, an
 * endpoint that existed but was consumed by nothing in the frontend until
 * now. Falls back to the old local guess (from chat/running flags) if the
 * fetch fails — MARK's presence indicator should never just disappear.
 */
export function MarkPresence() {
  const { serverUrl, messages, running } = useMarkStore();
  const [selfState, setSelfState] = useState<SelfState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await markApi.getSelfState(serverUrl);
        if (!cancelled) setSelfState(s);
      } catch {
        /* keep the last known state rather than clearing it on a hiccup */
      }
    };
    poll();
    const id = setInterval(poll, 4000);
    return () => { cancelled = true; clearInterval(id); };
  }, [serverUrl]);

  const lastMsg = messages[messages.length - 1];
  const isSpeaking = lastMsg?.role === 'mark' && lastMsg.isActive;
  const fallbackState: MarkAvatarState = isSpeaking ? 'speaking' : running ? 'thinking' : 'idle';
  const avatarState: MarkAvatarState = isSpeaking
    ? 'speaking'
    : selfState
      ? (MODE_TO_AVATAR[selfState.mode] ?? fallbackState)
      : fallbackState;

  const modeLabel = selfState
    ? (MODE_LABEL[selfState.mode] ?? selfState.mode)
    : (running ? 'Working' : 'Idle');

  const activity =
    selfState?.current_activity &&
    selfState.current_activity !== 'idle' &&
    selfState.current_activity !== 'not started'
      ? selfState.current_activity
      : null;

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
