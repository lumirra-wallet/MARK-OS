/**
 * Agent Timeline — Feature 16.
 *
 * Shows a replayable event timeline. Every WebSocket event MARK emits is
 * stored server-side and surfaced here in chronological order.
 * Click any event to inspect its full payload.
 */
import React, { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import {
  Clock, ChevronRight, ChevronDown, RefreshCw, Trash2, Filter,
  Play, CheckCircle, XCircle, Zap, GitCommit, FileEdit, Terminal,
  MessageSquare, Cpu, Activity,
} from 'lucide-react';

interface TimelineEvent {
  id:        string;
  run_id:    string;
  name:      string;
  payload:   Record<string, unknown>;
  timestamp: string;
}

const EVENT_ICONS: Record<string, React.ReactElement> = {
  RunStarted:     <Play        className="w-3 h-3 text-accent" />,
  RunCompleted:   <CheckCircle className="w-3 h-3 text-emerald-400" />,
  RunFailed:      <XCircle     className="w-3 h-3 text-red-400" />,
  RunCancelled:   <XCircle     className="w-3 h-3 text-amber-400" />,
  WorkerStarted:  <Cpu         className="w-3 h-3 text-blue-400" />,
  WorkerFinished: <CheckCircle className="w-3 h-3 text-emerald-400" />,
  ToolStarted:    <Zap         className="w-3 h-3 text-purple-400" />,
  ToolFinished:   <Zap         className="w-3 h-3 text-purple-300" />,
  GitCommit:      <GitCommit   className="w-3 h-3 text-amber-400" />,
  FileCreated:    <FileEdit    className="w-3 h-3 text-green-400" />,
  FileModified:   <FileEdit    className="w-3 h-3 text-blue-300" />,
  TestsPassed:    <CheckCircle className="w-3 h-3 text-emerald-400" />,
  TestsFailed:    <XCircle     className="w-3 h-3 text-red-400" />,
  StreamingToken: <Terminal    className="w-3 h-3 text-muted-foreground" />,
  AgentMessage:   <MessageSquare className="w-3 h-3 text-amber-300" />,
  EvaluationComplete: <Activity className="w-3 h-3 text-accent" />,
};

const FILTER_GROUPS = [
  { label: 'All',      values: null },
  { label: 'Run',      values: ['RunStarted','RunCompleted','RunFailed','RunCancelled'] },
  { label: 'Workers',  values: ['WorkerStarted','WorkerFinished','WorkerThinking'] },
  { label: 'Tools',    values: ['ToolStarted','ToolFinished','ToolCalled','ToolResult'] },
  { label: 'Files',    values: ['FileCreated','FileModified','FileDeleted'] },
  { label: 'Tests',    values: ['TestsStarted','TestsPassed','TestsFailed'] },
  { label: 'AI',       values: ['AgentMessage','ReflectionComplete','EvaluationComplete'] },
];

export function TimelineView() {
  const { serverUrl } = useMarkStore();
  const [events,  setEvents]  = useState<TimelineEvent[]>([]);
  const [runs,    setRuns]    = useState<string[]>([]);
  const [runId,   setRunId]   = useState<string>('');
  const [filter,  setFilter]  = useState<string[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const qs = runId ? `?run_id=${runId}&limit=500` : '?limit=500';
      const data = await fetch(`${serverUrl}/timeline${qs}`).then(r => r.json());
      setEvents(data.events || []);
      setRuns(data.run_ids  || []);
    } catch { /* offline */ }
    setLoading(false);
  };

  useEffect(() => { load(); }, [serverUrl, runId]);

  // Auto-refresh every 3 s during runs
  useEffect(() => {
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [serverUrl, runId]);

  const clear = async () => {
    await fetch(`${serverUrl}/timeline${runId ? `?run_id=${runId}` : ''}`, { method: 'DELETE' });
    setEvents([]);
  };

  const visible = filter
    ? events.filter(e => filter.includes(e.name))
    : events.filter(e => e.name !== 'StreamingToken');

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-accent" />
          <span className="font-semibold">Agent Timeline</span>
          <span className="text-xs text-muted-foreground">({visible.length} events)</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load}  className="p-1 hover:bg-muted/40 rounded">
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
          </button>
          <button onClick={clear} className="p-1 hover:bg-muted/40 rounded text-red-400">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Filters row */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40 overflow-x-auto shrink-0">
        <Filter className="w-3 h-3 text-muted-foreground shrink-0" />
        {FILTER_GROUPS.map(g => (
          <button
            key={g.label}
            onClick={() => setFilter(g.values)}
            className={cn(
              'text-xs px-2 py-0.5 rounded shrink-0 transition-colors',
              filter === g.values
                ? 'bg-accent text-accent-foreground'
                : 'bg-muted/30 text-muted-foreground hover:text-foreground',
            )}
          >
            {g.label}
          </button>
        ))}
        <div className="flex-1" />
        {runs.length > 0 && (
          <select
            value={runId}
            onChange={e => setRunId(e.target.value)}
            className="text-xs bg-muted/30 border border-border/50 rounded px-2 py-0.5 text-muted-foreground max-w-[120px]"
          >
            <option value="">All runs</option>
            {runs.map(r => (
              <option key={r} value={r}>{r.slice(0, 8)}</option>
            ))}
          </select>
        )}
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
            <Clock className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs">Run MARK to populate the timeline</p>
          </div>
        ) : (
          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-6 top-0 bottom-0 w-px bg-border/30" />
            <div className="space-y-0">
              {visible.map(ev => {
                const isOpen = expanded === ev.id;
                return (
                  <div key={ev.id} className="pl-12 pr-4 py-1.5 relative group hover:bg-muted/10 transition-colors">
                    {/* Dot */}
                    <div className="absolute left-5 top-3 -translate-y-1/2 w-2 h-2 rounded-full bg-border group-hover:bg-accent/50 transition-colors" />
                    {/* Icon */}
                    <div className="absolute left-3.5 top-2.5 -translate-y-1/2">
                      {EVENT_ICONS[ev.name] ?? <Activity className="w-3 h-3 text-muted-foreground" />}
                    </div>

                    <button
                      onClick={() => setExpanded(isOpen ? null : ev.id)}
                      className="w-full text-left"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-medium text-xs">{ev.name}</span>
                        <span className="text-[10px] text-muted-foreground font-mono shrink-0">
                          {ev.timestamp.slice(11, 23)}
                        </span>
                      </div>
                      {/* Payload preview */}
                      <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                        {Object.entries(ev.payload).slice(0, 3).map(([k, v]) => (
                          <span key={k} className="mr-2">
                            <span className="text-accent/70">{k}:</span>{' '}
                            {typeof v === 'string' ? v.slice(0, 40) : JSON.stringify(v).slice(0, 40)}
                          </span>
                        ))}
                      </div>
                    </button>

                    {isOpen && (
                      <div className="mt-2 bg-muted/20 border border-border/40 rounded p-2">
                        <pre className="text-[10px] font-mono whitespace-pre-wrap break-all text-foreground/80 max-h-48 overflow-y-auto">
                          {JSON.stringify(ev.payload, null, 2)}
                        </pre>
                        <div className="mt-1 text-[10px] text-muted-foreground">
                          run: {ev.run_id || 'n/a'} · id: {ev.id}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
