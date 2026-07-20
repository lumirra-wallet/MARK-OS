/**
 * CognitiveTimeline — MARK's real observable pipeline, event by event.
 *
 * Every entry here originated from a real brain event on the backend.
 * The UI never fabricates entries; it only receives and displays.
 *
 * Steps: listening → memory_retrieved → knowledge_matched →
 *        reasoning → decision_made → speaking → reflection_complete
 */

import { useMarkStore } from '@/store/markStore';

export interface CognitiveEvent {
  id: string;
  timestamp: string;
  step: string;
  detail?: string;
}

const STEP_CONFIG: Record<string, { icon: string; label: string; color: string }> = {
  listening:           { icon: '◉', label: 'Listening',          color: 'text-blue-400' },
  memory_retrieved:    { icon: '◈', label: 'Memory retrieved',   color: 'text-violet-400' },
  knowledge_matched:   { icon: '✦', label: 'Knowledge matched',  color: 'text-emerald-400' },
  reasoning:           { icon: '⚡', label: 'Reasoning',          color: 'text-yellow-400' },
  decision_made:       { icon: '✓', label: 'Decision made',      color: 'text-green-400' },
  speaking:            { icon: '◎', label: 'Speaking',           color: 'text-cyan-400' },
  reflection_complete: { icon: '↻', label: 'Reflected',          color: 'text-indigo-400' },
  voice_interrupted:   { icon: '⊘', label: 'Interrupted',        color: 'text-orange-400' },
};

function formatAge(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    if (diff < 5000)  return 'just now';
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    return `${Math.floor(diff / 3600000)}h ago`;
  } catch {
    return '';
  }
}

interface Props {
  events: CognitiveEvent[];
  maxVisible?: number;
  className?: string;
}

export function CognitiveTimeline({ events, maxVisible = 8, className = '' }: Props) {
  const visible = events.slice(0, maxVisible);

  if (visible.length === 0) {
    return (
      <div className={`flex items-center justify-center h-16 text-[11px] font-mono text-muted-foreground/40 ${className}`}>
        No activity yet
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      {visible.map((ev, idx) => {
        const cfg = STEP_CONFIG[ev.step] ?? {
          icon: '·', label: ev.step.replace(/_/g, ' '), color: 'text-muted-foreground',
        };
        const isLatest = idx === 0;
        return (
          <div
            key={ev.id}
            className={`flex items-start gap-2 px-2 py-1 rounded text-[11px] font-mono transition-all ${
              isLatest ? 'bg-card/60' : ''
            }`}
            style={{ opacity: Math.max(0.3, 1 - idx * 0.12) }}
          >
            {/* Timeline spine */}
            <div className="flex flex-col items-center mt-0.5 shrink-0 w-3">
              <span className={`text-[10px] leading-none ${cfg.color}`}>{cfg.icon}</span>
              {idx < visible.length - 1 && (
                <div className="w-px flex-1 mt-0.5 bg-border/30 min-h-[8px]" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className={`font-medium ${isLatest ? cfg.color : 'text-muted-foreground'}`}>
                  {cfg.label}
                </span>
                <span className="text-muted-foreground/40 shrink-0">{formatAge(ev.timestamp)}</span>
              </div>
              {ev.detail && (
                <p className="text-muted-foreground/60 truncate mt-px">{ev.detail}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Note: use useMarkStore(s => s.cognitiveEvents) directly in consumers
// rather than a separate hook — mixing hook + component exports in one file
// breaks Vite's Fast Refresh.
