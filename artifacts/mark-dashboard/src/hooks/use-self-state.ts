import { useMarkStore } from '@/store/markStore';
import { MarkAvatarState } from '@/components/MarkAvatar';

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
 * MARK's real presence, shared by every surface that shows it (the compact
 * header pill and the Presence Engine on MARK's Home). No polling: reads
 * straight from the store's `selfState`, which is populated by one fetch on
 * WebSocket connect and updated thereafter purely by SelfStateChanged
 * pushes from the backend (see api.py's _broadcast_self_state, called at the
 * two real transition points — a task starting, a task finishing).
 */
export function useSelfState() {
  const { selfState, messages, running } = useMarkStore();

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

  return { selfState, avatarState, modeLabel, activity, isSpeaking };
}
