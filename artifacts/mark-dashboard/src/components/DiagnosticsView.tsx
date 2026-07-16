/**
 * DiagnosticsView — full system health dashboard.
 *
 * Shows a green/amber/red status indicator for every major MARK subsystem:
 *   Backend · LLM Provider · Embeddings · Git · Workspace ·
 *   Vector DB · Memory · WebSocket
 *
 * Polls /diagnostics every 30 s and supports a manual refresh button.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2, XCircle, AlertTriangle, RefreshCw, Stethoscope,
  Server, Brain, Database, GitBranch, FolderOpen, Layers, MemoryStick,
  Wifi, Activity, Info,
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

// ── Icon per subsystem ─────────────────────────────────────────────────────────

const subsystemIcon: Record<string, React.ElementType> = {
  backend:      Server,
  llm_provider: Brain,
  embeddings:   Layers,
  git:          GitBranch,
  workspace:    FolderOpen,
  vector_db:    Database,
  memory:       MemoryStick,
  websocket:    Wifi,
};

const subsystemLabel: Record<string, string> = {
  backend:      'Backend',
  llm_provider: 'LLM Provider',
  embeddings:   'Embedding Provider',
  git:          'Git',
  workspace:    'Workspace',
  vector_db:    'Vector DB',
  memory:       'Memory',
  websocket:    'WebSocket',
};

// ── Individual check card ──────────────────────────────────────────────────────

function CheckCard({ check, index }: { check: DiagCheck; index: number }) {
  const Icon = subsystemIcon[check.name] ?? Info;
  const label = subsystemLabel[check.name] ?? check.name;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className={cn(
        'flex items-start gap-3 p-4 rounded-xl border',
        statusBg[check.status],
      )}
    >
      <div className="flex items-center gap-2.5 min-w-[160px] shrink-0">
        <Icon className={cn('w-4 h-4 shrink-0', statusColor[check.status])} />
        <span className="text-sm font-medium">{label}</span>
      </div>

      <div className="flex items-center gap-2 flex-1 min-w-0">
        <StatusIcon status={check.status} />
        <p className="text-sm text-muted-foreground truncate">{check.message}</p>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {check.provider && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/40 text-muted-foreground font-mono">
            {check.provider}
          </span>
        )}
        {check.model && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted/40 text-muted-foreground font-mono truncate max-w-[120px]">
            {check.model}
          </span>
        )}
        {check.latency_ms != null && (
          <span className="text-[10px] text-muted-foreground/60 font-mono w-14 text-right">
            {check.latency_ms}ms
          </span>
        )}
      </div>
    </motion.div>
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

  const run = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      // Build the URL from serverUrl (respects VITE_API_URL / same-origin)
      const base = serverUrl.replace(/\/$/, '');
      const res = await fetch(`${base}/diagnostics`);
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

  // Run on mount and every 30 s
  useEffect(() => {
    run();
    const id = setInterval(run, 30_000);
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
              onClick={run}
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
            {Array.from({ length: 8 }).map((_, i) => (
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
              className="space-y-3"
            >
              <OverallBanner status={data.status} checkCount={data.checks.length} />

              <div className="space-y-2 pt-1">
                {data.checks.map((check, i) => (
                  <CheckCard key={check.name} check={check} index={i} />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Legend */}
        <div className="flex items-center gap-5 pt-2 text-xs text-muted-foreground border-t border-border/40 pt-4">
          <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> OK</span>
          <span className="flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> Warning — degraded but functional</span>
          <span className="flex items-center gap-1.5"><XCircle className="w-3.5 h-3.5 text-red-400" /> Error — action required</span>
          <span className="ml-auto">Auto-refreshes every 30 s</span>
        </div>
      </div>
    </div>
  );
}
