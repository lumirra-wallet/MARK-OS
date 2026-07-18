/**
 * DiagnosticsView — full system health dashboard.
 *
 * Shows a green/amber/red status indicator for every major MARK subsystem:
 *   Backend · Database · LLM Provider · Embeddings · Vector DB ·
 *   Git · Workspace · Memory · WebSocket · System (CPU/RAM)
 *
 * Polls /diagnostics every 30 s (probe=false — no real provider network
 * calls, just last-known status). The manual Refresh button does a real
 * connectivity probe (probe=true).
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2, XCircle, AlertTriangle, RefreshCw, Stethoscope,
  Server, Brain, Database, GitBranch, FolderOpen, Layers, MemoryStick,
  Wifi, Activity, Info, Cpu, HardDrive, Zap,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────────

interface DiagCheck {
  name:        string;
  status:      'ok' | 'warn' | 'error';
  message:     string;
  provider?:   string;
  model?:      string;
  latency_ms?: number;
  cpu_pct?:    number;
  ram_pct?:    number;
  ram_used_gb?:  number;
  ram_total_gb?: number;
  count?:      number;
  dir?:        string;
  // llm_provider extras
  endpoint?:       string;
  request_count?:  number;
  last_error?:     string | null;
  last_error_at?:  string | null;
  // system extras — THIS process, distinct from system-wide load
  process_pid?:      number;
  process_cpu_pct?:  number;
  process_rss_mb?:   number;
}

interface DiagResponse {
  status: 'ok' | 'warn' | 'error';
  checks: DiagCheck[];
}

// ── Status helpers ─────────────────────────────────────────────────────────────

const statusColor = {
  ok:    'text-emerald-400',
  warn:  'text-amber-400',
  error: 'text-red-400',
};
const statusBg = {
  ok:    'bg-emerald-400/10 border-emerald-400/20',
  warn:  'bg-amber-400/10  border-amber-400/20',
  error: 'bg-red-400/10   border-red-400/20',
};
const StatusIcon = ({ status }: { status: 'ok' | 'warn' | 'error' }) => {
  if (status === 'ok')   return <CheckCircle2  className="w-4 h-4 text-emerald-400 shrink-0" />;
  if (status === 'warn') return <AlertTriangle className="w-4 h-4 text-amber-400  shrink-0" />;
  return                        <XCircle       className="w-4 h-4 text-red-400    shrink-0" />;
};

// ── Icon + label per subsystem ─────────────────────────────────────────────────

const subsystemIcon: Record<string, React.ElementType> = {
  backend:      Server,
  database:     Database,
  llm_provider: Brain,
  embeddings:   Layers,
  vector_db:    Zap,
  git:          GitBranch,
  workspace:    FolderOpen,
  memory:       MemoryStick,
  websocket:    Wifi,
  system:       Cpu,
};

const subsystemLabel: Record<string, string> = {
  backend:      'Backend',
  database:     'Database',
  llm_provider: 'LLM Provider',
  embeddings:   'Embeddings',
  vector_db:    'Vector DB',
  git:          'Git',
  workspace:    'Workspace',
  memory:       'Memory',
  websocket:    'WebSocket',
  system:       'CPU / RAM',
};

// ── Mini usage bar ─────────────────────────────────────────────────────────────

function UsageBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="w-20 h-1.5 rounded-full bg-muted/40 overflow-hidden shrink-0">
      <div
        className={cn('h-full rounded-full transition-all', color)}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  );
}

// ── Individual check card ──────────────────────────────────────────────────────

function CheckCard({ check, index }: { check: DiagCheck; index: number }) {
  const Icon  = subsystemIcon[check.name] ?? Info;
  const label = subsystemLabel[check.name] ?? check.name;

  const isSystem = check.name === 'system';
  const isLlm    = check.name === 'llm_provider';
  const cpuColor = (check.cpu_pct ?? 0) > 80 ? 'bg-amber-400' : 'bg-emerald-400';
  const ramColor = (check.ram_pct ?? 0) > 85 ? 'bg-red-400'   : (check.ram_pct ?? 0) > 70 ? 'bg-amber-400' : 'bg-emerald-400';

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className={cn(
        'flex flex-col gap-2.5 p-4 rounded-xl border',
        statusBg[check.status],
      )}
    >
      <div className="flex items-start gap-3">
        {/* Subsystem label */}
        <div className="flex items-center gap-2.5 min-w-[148px] shrink-0">
          <Icon className={cn('w-4 h-4 shrink-0', statusColor[check.status])} />
          <span className="text-sm font-medium">{label}</span>
        </div>

        {/* Message + status */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <StatusIcon status={check.status} />
          <p className="text-sm text-muted-foreground truncate">{check.message}</p>
        </div>

        {/* Right-side badges */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          {/* CPU bar */}
          {isSystem && check.cpu_pct != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground/60 font-mono">CPU</span>
              <UsageBar pct={check.cpu_pct} color={cpuColor} />
              <span className="text-[10px] font-mono text-muted-foreground w-8">{check.cpu_pct?.toFixed(0)}%</span>
            </div>
          )}
          {/* RAM bar */}
          {isSystem && check.ram_pct != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground/60 font-mono">RAM</span>
              <UsageBar pct={check.ram_pct} color={ramColor} />
              <span className="text-[10px] font-mono text-muted-foreground w-8">{check.ram_pct?.toFixed(0)}%</span>
            </div>
          )}

          {/* Provider badge */}
          {check.provider && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/40 text-muted-foreground font-mono capitalize">
              {check.provider}
            </span>
          )}
          {/* Model badge */}
          {check.model && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 font-mono truncate max-w-[130px]">
              {check.model}
            </span>
          )}
          {/* Latency */}
          {check.latency_ms != null && (
            <span className="text-[10px] text-muted-foreground/60 font-mono w-14 text-right">
              {check.latency_ms}ms
            </span>
          )}
        </div>
      </div>

      {/* LLM provider detail row — endpoint, request count, last error */}
      {isLlm && (check.endpoint || check.request_count != null) && (
        <div className="flex items-center gap-4 flex-wrap pl-[172px] text-[11px]">
          {check.endpoint && (
            <span className="text-muted-foreground font-mono truncate max-w-[280px]">
              {check.endpoint}
            </span>
          )}
          {check.request_count != null && (
            <span className="text-muted-foreground">
              <span className="font-mono text-foreground/80">{check.request_count}</span> requests this process
            </span>
          )}
          {check.last_error && (
            <span className="text-red-400/80 truncate max-w-[360px]" title={check.last_error}>
              last error: {check.last_error}
              {check.last_error_at && <span className="text-muted-foreground/60"> ({new Date(check.last_error_at).toLocaleTimeString()})</span>}
            </span>
          )}
        </div>
      )}

      {/* System detail row — this process's own PID/CPU/RSS, distinct from system-wide */}
      {isSystem && check.process_pid != null && (
        <div className="flex items-center gap-4 flex-wrap pl-[172px] text-[11px] text-muted-foreground">
          <span>MARK process (pid <span className="font-mono text-foreground/80">{check.process_pid}</span>)</span>
          <span><span className="font-mono text-foreground/80">{check.process_cpu_pct?.toFixed(1)}%</span> CPU</span>
          <span><span className="font-mono text-foreground/80">{check.process_rss_mb}</span> MB RSS</span>
        </div>
      )}
    </motion.div>
  );
}

// ── Summary cards ──────────────────────────────────────────────────────────────

function SummaryCards({ checks }: { checks: DiagCheck[] }) {
  const llm    = checks.find(c => c.name === 'llm_provider');
  const sys    = checks.find(c => c.name === 'system');
  const db     = checks.find(c => c.name === 'database');
  const vdb    = checks.find(c => c.name === 'vector_db');

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {/* Active provider/model */}
      <div className="p-3 rounded-xl border border-border/40 bg-muted/10 space-y-1">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Provider</p>
        <p className="text-sm font-semibold capitalize">{llm?.provider ?? '—'}</p>
        <p className="text-[10px] text-muted-foreground font-mono truncate">{llm?.model ?? '—'}</p>
      </div>

      {/* CPU */}
      <div className="p-3 rounded-xl border border-border/40 bg-muted/10 space-y-1">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">CPU</p>
        <p className="text-sm font-semibold">{sys?.cpu_pct != null ? `${sys.cpu_pct.toFixed(0)}%` : '—'}</p>
        <div className="h-1 rounded-full bg-muted/40 overflow-hidden">
          <div
            className={cn('h-full rounded-full', (sys?.cpu_pct ?? 0) > 80 ? 'bg-amber-400' : 'bg-emerald-400')}
            style={{ width: `${Math.min(sys?.cpu_pct ?? 0, 100)}%` }}
          />
        </div>
      </div>

      {/* RAM */}
      <div className="p-3 rounded-xl border border-border/40 bg-muted/10 space-y-1">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">RAM</p>
        <p className="text-sm font-semibold">
          {sys?.ram_used_gb != null ? `${sys.ram_used_gb} / ${sys.ram_total_gb} GB` : '—'}
        </p>
        <div className="h-1 rounded-full bg-muted/40 overflow-hidden">
          <div
            className={cn('h-full rounded-full', (sys?.ram_pct ?? 0) > 85 ? 'bg-red-400' : (sys?.ram_pct ?? 0) > 70 ? 'bg-amber-400' : 'bg-emerald-400')}
            style={{ width: `${Math.min(sys?.ram_pct ?? 0, 100)}%` }}
          />
        </div>
      </div>

      {/* Storage */}
      <div className="p-3 rounded-xl border border-border/40 bg-muted/10 space-y-1">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Storage</p>
        <p className="text-sm font-semibold capitalize">{db?.provider ?? 'local'}</p>
        <p className="text-[10px] text-muted-foreground">
          {db?.status === 'ok' ? 'Connected' : db?.message?.slice(0, 24) ?? '—'}
        </p>
      </div>
    </div>
  );
}

// ── Overall status banner ──────────────────────────────────────────────────────

function OverallBanner({ status, checkCount }: { status: 'ok' | 'warn' | 'error'; checkCount: number }) {
  const config = {
    ok:    { label: 'All systems operational',       bg: 'bg-emerald-500/10 border-emerald-500/20', text: 'text-emerald-400' },
    warn:  { label: 'Some systems need attention',   bg: 'bg-amber-500/10  border-amber-500/20',  text: 'text-amber-400'  },
    error: { label: 'One or more systems are down',  bg: 'bg-red-500/10    border-red-500/20',    text: 'text-red-400'    },
  }[status];

  return (
    <div className={cn('flex items-center gap-3 p-4 rounded-xl border', config.bg)}>
      <StatusIcon status={status} />
      <div>
        <p className={cn('text-sm font-semibold', config.text)}>{config.label}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{checkCount} subsystems checked</p>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function DiagnosticsView() {
  const { serverUrl } = useMarkStore();
  const [data,      setData]      = useState<DiagResponse | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');
  const [lastCheck, setLastCheck] = useState<Date | null>(null);

  // probe=true makes a REAL network call to the active LLM provider (and to
  // its embedding endpoint, where applicable) to verify reachability — not
  // a free ping. Auto-polling with probe=true would silently burn one real
  // provider request every 30s just from this page being open, which
  // measurably adds to a rate-limited provider's request volume instead of
  // only diagnosing it. The periodic poll below uses probe=false (reports
  // last-known status + telemetry, zero network calls); only an explicit
  // manual refresh click does the real connectivity check.
  const run = useCallback(async (probe: boolean) => {
    setLoading(true);
    setError('');
    try {
      const base = serverUrl.replace(/\/$/, '');
      const res  = await fetch(`${base}/diagnostics?probe=${probe}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: DiagResponse = await res.json();
      setData(json);
      setLastCheck(new Date());
    } catch (err: any) {
      setError(err.message || 'Failed to reach MARK server');
    } finally {
      setLoading(false);
    }
  }, [serverUrl]);

  useEffect(() => {
    run(true); // first load: do the real check once
    const id = setInterval(() => run(false), 30_000);
    return () => clearInterval(id);
  }, [run]);

  const fmt = (d: Date) =>
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Stethoscope className="w-5 h-5 text-accent" />
            <h2 className="text-xl font-bold tracking-tight">Diagnostics</h2>
          </div>
          <div className="flex items-center gap-3">
            {lastCheck && (
              <span className="text-xs text-muted-foreground">
                Last checked {fmt(lastCheck)}
              </span>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => run(true)}
              disabled={loading}
              className="h-8 text-xs"
            >
              {loading
                ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" />
                : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              }
              {loading ? 'Checking…' : 'Refresh'}
            </Button>
          </div>
        </div>

        {/* Error connecting to server */}
        {error && (
          <div className="flex items-start gap-2.5 p-4 bg-red-500/10 border border-red-500/20 rounded-xl">
            <XCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-400">Cannot reach MARK server</p>
              <p className="text-xs text-red-400/70 mt-0.5">{error}</p>
              <p className="text-xs text-muted-foreground mt-1">
                Make sure the Python server is running at <code className="font-mono">{serverUrl}</code>
              </p>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !data && (
          <div className="space-y-3">
            <div className="grid grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-20 rounded-xl bg-muted/30 animate-pulse" />
              ))}
            </div>
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-14 rounded-xl bg-muted/30 animate-pulse" />
            ))}
          </div>
        )}

        {/* Results */}
        <AnimatePresence mode="wait">
          {data && (
            <motion.div
              key="results"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-4"
            >
              {/* Summary row */}
              <SummaryCards checks={data.checks} />

              {/* Overall banner */}
              <OverallBanner status={data.status} checkCount={data.checks.length} />

              {/* Check cards */}
              <div className="space-y-2 pt-1">
                {data.checks.map((check, i) => (
                  <CheckCard key={check.name} check={check} index={i} />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-5 text-xs text-muted-foreground border-t border-border/40 pt-4">
          <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Healthy</span>
          <span className="flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> Warning — degraded</span>
          <span className="flex items-center gap-1.5"><XCircle className="w-3.5 h-3.5 text-red-400" /> Error — action required</span>
          <span className="ml-auto">Auto-refreshes every 30 s</span>
        </div>
      </div>
    </div>
  );
}
