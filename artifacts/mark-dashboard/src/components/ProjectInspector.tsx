/**
 * ProjectInspector — the composite "what's going on right now" panel.
 *
 * Deliberately reuses existing, already-real data sources instead of
 * introducing new backend endpoints: GitPanel's own markApi calls for
 * branch/commits/files, DiagnosticsView's /diagnostics fetch for the active
 * model/provider, and the store's previews/workers state. The two real gaps
 * (persistent test results, real performance telemetry) are filled by
 * markStore's `lastTestRun` and `tokenTimestamps` fields.
 */
import { useEffect, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  GitBranch, GitCommit as GitCommitIcon, FileEdit, FlaskConical,
  Cpu, Sparkles, Globe, RefreshCw,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi, GitStatus, GitCommit } from '@/lib/markApi';
import { cn } from '@/lib/utils';

interface DiagCheck {
  name: string;
  status: 'ok' | 'warn' | 'error';
  provider?: string;
  model?: string;
}

function Card({ title, icon: Icon, children }: { title: string; icon: React.ComponentType<any>; children: React.ReactNode }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card border border-border/50 rounded-xl p-4 flex flex-col gap-2"
    >
      <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        <Icon className="w-3.5 h-3.5" />
        {title}
      </div>
      {children}
    </motion.div>
  );
}

export function ProjectInspector() {
  const { serverUrl, workspace, previews, workers, lastTestRun, tokenTimestamps } = useMarkStore();
  const [gitStatus, setGitStatus]   = useState<GitStatus | null>(null);
  const [commits, setCommits]       = useState<GitCommit[]>([]);
  const [llmCheck, setLlmCheck]     = useState<DiagCheck | null>(null);
  const [loading, setLoading]       = useState(false);

  const ws = workspace || undefined;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [status, log] = await Promise.all([
        markApi.getGitStatus(serverUrl, ws),
        markApi.getGitLog(serverUrl, ws, 8),
      ]);
      setGitStatus(status);
      setCommits(log.commits);
    } catch { /* workspace may not be a git repo */ }
    try {
      const res = await fetch(`${serverUrl}/diagnostics`);
      if (res.ok) {
        const data = await res.json();
        const check = (data.checks as DiagCheck[]).find(c => c.name === 'llm_provider');
        setLlmCheck(check ?? null);
      }
    } catch { /* diagnostics endpoint unavailable */ }
    setLoading(false);
  }, [serverUrl, ws]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, [refresh]);

  // Real tokens/sec: bucket actual StreamingToken arrival timestamps into 1s windows.
  const tokensPerSec = (() => {
    if (tokenTimestamps.length < 2) return 0;
    const now = Date.now();
    const lastSecond = tokenTimestamps.filter(t => now - t <= 1000).length;
    return lastSecond;
  })();

  const runningWorkers  = workers.filter(w => w.status === 'running').length;
  const activePreviews  = previews.filter(p => p.status === 'ready');

  return (
    <div className="h-full p-6 flex flex-col gap-4 bg-background overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight mb-1">Project Inspector</h2>
          <p className="text-muted-foreground text-sm">Live status across git, tests, workers, previews, and the model.</p>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors border border-border/40 rounded-md px-2.5 py-1.5"
        >
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <Card title="Running Applications" icon={Globe}>
          {activePreviews.length === 0 ? (
            <span className="text-sm text-muted-foreground italic">None detected</span>
          ) : (
            <div className="flex flex-col gap-1.5">
              {activePreviews.map(p => (
                <div key={p.id} className="flex items-center justify-between text-sm">
                  <span className="truncate">{p.title}</span>
                  <span className="text-[10px] font-mono text-muted-foreground">{p.framework}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Current Branch" icon={GitBranch}>
          {gitStatus ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="font-mono">{gitStatus.branch}</span>
              {!gitStatus.clean && <span className="text-[10px] text-amber-500">dirty</span>}
              {gitStatus.ahead > 0 && <span className="text-[10px] text-muted-foreground">↑{gitStatus.ahead}</span>}
              {gitStatus.behind > 0 && <span className="text-[10px] text-muted-foreground">↓{gitStatus.behind}</span>}
            </div>
          ) : (
            <span className="text-sm text-muted-foreground italic">Not a git workspace</span>
          )}
        </Card>

        <Card title="Recent Commits" icon={GitCommitIcon}>
          {commits.length === 0 ? (
            <span className="text-sm text-muted-foreground italic">None</span>
          ) : (
            <div className="flex flex-col gap-1">
              {commits.slice(0, 5).map(c => (
                <div key={c.hash} className="text-xs truncate">
                  <span className="font-mono text-muted-foreground mr-1.5">{c.short}</span>
                  {c.message}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Files Changed" icon={FileEdit}>
          {!gitStatus || gitStatus.changes.length === 0 ? (
            <span className="text-sm text-muted-foreground italic">Clean</span>
          ) : (
            <div className="flex flex-col gap-1">
              {gitStatus.changes.slice(0, 6).map(c => (
                <div key={c.path} className="text-xs font-mono truncate">
                  <span className="text-muted-foreground mr-1.5">{c.status}</span>{c.path}
                </div>
              ))}
              {gitStatus.changes.length > 6 && (
                <span className="text-[10px] text-muted-foreground">+{gitStatus.changes.length - 6} more</span>
              )}
            </div>
          )}
        </Card>

        <Card title="Test Results" icon={FlaskConical}>
          <div className="flex items-center gap-2 text-sm">
            <span className={cn(
              'text-[10px] px-2 py-0.5 rounded font-mono uppercase tracking-wider border',
              lastTestRun.status === 'passed' && 'bg-emerald-500/20 text-emerald-500 border-emerald-500/30',
              lastTestRun.status === 'failed' && 'bg-destructive/20 text-destructive border-destructive/30',
              lastTestRun.status === 'running' && 'bg-accent/20 text-accent border-accent/30',
              lastTestRun.status === 'idle' && 'bg-muted text-muted-foreground border-border',
            )}>
              {lastTestRun.status}
            </span>
            {lastTestRun.timestamp && (
              <span className="text-[10px] text-muted-foreground">
                {new Date(lastTestRun.timestamp).toLocaleTimeString()}
              </span>
            )}
          </div>
          {lastTestRun.output && (
            <div className="text-xs font-mono text-muted-foreground truncate mt-1">
              {lastTestRun.output.split('\n')[0]}
            </div>
          )}
        </Card>

        <Card title="Worker Status" icon={Cpu}>
          <div className="flex items-center gap-2 text-sm">
            <span>{runningWorkers} running</span>
            <span className="text-muted-foreground">·</span>
            <span>{workers.length} total</span>
          </div>
        </Card>

        <Card title="Performance" icon={Sparkles}>
          <div className="text-sm">{tokensPerSec} tokens/sec (last 1s)</div>
        </Card>

        <Card title="Active Model & Provider" icon={Sparkles}>
          {llmCheck ? (
            <div className="text-sm">
              <span className="font-medium">{llmCheck.provider ?? 'unknown'}</span>
              {llmCheck.model && <span className="text-muted-foreground"> · {llmCheck.model}</span>}
            </div>
          ) : (
            <span className="text-sm text-muted-foreground italic">Unavailable</span>
          )}
        </Card>
      </div>
    </div>
  );
}
