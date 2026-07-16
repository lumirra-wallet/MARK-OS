/**
 * Evaluation Panel — Feature 17.
 *
 * Scores every run and shows trends over time. Metrics: planning quality,
 * tool efficiency, test pass rate, code quality, time score, overall grade.
 */
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { Activity, TrendingUp, Award, RefreshCw, CheckCircle, XCircle } from 'lucide-react';

interface Evaluation {
  run_id:            string;
  goal:              string;
  success:           boolean;
  timestamp:         string;
  elapsed_s:         number;
  overall:           number;
  grade:             string;
  scores: {
    planning_score:  number;
    tool_efficiency: number;
    test_pass_rate:  number;
    code_quality:    number;
    time_score:      number;
    context_ratio:   number;
  };
}

interface Trends {
  trends:     { timestamp: string; overall: number; success: boolean }[];
  averages:   Record<string, number>;
  total_runs: number;
}

const GRADE_COLOR: Record<string, string> = {
  A: 'text-emerald-400', B: 'text-blue-400',
  C: 'text-amber-400',   D: 'text-orange-400', F: 'text-red-400',
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn(pct >= 80 ? 'text-emerald-400' : pct >= 60 ? 'text-amber-400' : 'text-red-400')}>
          {pct}%
        </span>
      </div>
      <div className="h-1.5 bg-muted/30 rounded-full overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all', pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-500' : 'bg-red-500')}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function EvaluationPanel() {
  const { serverUrl } = useMarkStore();
  const [evals,    setEvals]   = useState<Evaluation[]>([]);
  const [trends,   setTrends]  = useState<Trends | null>(null);
  const [selected, setSelected] = useState<Evaluation | null>(null);
  const [loading,  setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [e, t] = await Promise.all([
        fetch(`${serverUrl}/evaluations?limit=50`).then(r => r.json()),
        fetch(`${serverUrl}/evaluations/trends`).then(r => r.json()),
      ]);
      setEvals(e.evaluations || []);
      setTrends(t);
      if (!selected && e.evaluations?.length) setSelected(e.evaluations[0]);
    } catch { /* offline */ }
    setLoading(false);
  };

  useEffect(() => { load(); }, [serverUrl]);

  const trendData = (trends?.trends || []).map((t, i) => ({
    i,
    overall: Math.round(t.overall * 100),
    success: t.success ? 100 : 0,
    time:    t.timestamp.slice(11, 16),
  }));

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-accent" />
          <span className="font-semibold">Run Evaluations</span>
          {trends && (
            <span className="text-xs text-muted-foreground">
              ({trends.total_runs} runs)
            </span>
          )}
        </div>
        <button onClick={load} className="p-1 hover:bg-muted/40 rounded">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Trend chart */}
      {trendData.length > 0 && (
        <div className="px-4 py-3 border-b border-border/50 shrink-0">
          <p className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
            <TrendingUp className="w-3 h-3" /> Overall Score Trend
          </p>
          <ResponsiveContainer width="100%" height={60}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="evalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--accent)" stopOpacity={0}   />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="overall" stroke="var(--accent)" fill="url(#evalGrad)" strokeWidth={2} dot={false} />
              <Tooltip
                formatter={(v: number) => [`${v}%`, 'Score']}
                contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 4, fontSize: 11 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Averages */}
      {trends?.averages && Object.keys(trends.averages).length > 0 && (
        <div className="px-4 py-2 border-b border-border/50 shrink-0">
          <p className="text-xs text-muted-foreground mb-2">Averages across all runs</p>
          <div className="grid grid-cols-3 gap-x-4 gap-y-1.5">
            {Object.entries(trends.averages).map(([k, v]) => (
              <ScoreBar key={k} label={k.replace(/_/g, ' ')} value={v} />
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Run list */}
        <div className="w-48 border-r border-border/50 overflow-y-auto shrink-0">
          {evals.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
              <Activity className="w-6 h-6 mb-1 opacity-30" />
              <p className="text-xs text-center">No evaluations yet.<br/>Complete a run to score it.</p>
            </div>
          ) : evals.map(ev => (
            <button
              key={ev.run_id}
              onClick={() => setSelected(ev)}
              className={cn(
                'w-full text-left px-3 py-2.5 border-b border-border/20 hover:bg-muted/30 transition-colors',
                selected?.run_id === ev.run_id && 'bg-muted/50',
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn('text-lg font-bold', GRADE_COLOR[ev.grade] || 'text-foreground')}>
                  {ev.grade}
                </span>
                {ev.success
                  ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                  : <XCircle     className="w-3.5 h-3.5 text-red-400" />
                }
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 truncate">{ev.goal.slice(0, 40)}</p>
              <p className="text-[10px] text-muted-foreground/60">{ev.timestamp.slice(0, 16)}</p>
            </button>
          ))}
        </div>

        {/* Selected detail */}
        <div className="flex-1 overflow-y-auto p-4">
          {selected ? (
            <div className="space-y-4">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <span className={cn('text-3xl font-bold', GRADE_COLOR[selected.grade])}>
                    {selected.grade}
                  </span>
                  <div>
                    <p className="text-sm font-semibold">{Math.round(selected.overall * 100)}% overall</p>
                    <p className="text-xs text-muted-foreground">{selected.elapsed_s}s · {selected.timestamp.slice(0, 16)}</p>
                  </div>
                  <Award className={cn('w-5 h-5 ml-auto', GRADE_COLOR[selected.grade])} />
                </div>
                <p className="text-xs text-muted-foreground truncate">{selected.goal}</p>
              </div>

              <div className="space-y-2">
                <ScoreBar label="Planning Quality"  value={selected.scores.planning_score}  />
                <ScoreBar label="Tool Efficiency"   value={selected.scores.tool_efficiency}  />
                <ScoreBar label="Test Pass Rate"    value={selected.scores.test_pass_rate}   />
                <ScoreBar label="Code Quality"      value={selected.scores.code_quality}     />
                <ScoreBar label="Time Efficiency"   value={selected.scores.time_score}       />
                <ScoreBar label="Context Efficiency" value={selected.scores.context_ratio}   />
              </div>

              <div className="bg-muted/20 border border-border/40 rounded p-2 text-xs">
                <p className="text-muted-foreground mb-1 font-medium">Run ID</p>
                <code className="font-mono text-[10px] break-all">{selected.run_id}</code>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
              <Award className="w-8 h-8 mb-2 opacity-30" />
              <p className="text-xs">Select a run to see detailed scores</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
