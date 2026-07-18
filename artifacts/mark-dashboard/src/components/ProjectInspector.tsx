/**
 * ProjectInspector.tsx — the Right-zone "what's going on right now" cards.
 * Deliberately reuses existing, already-real data sources instead of
 * introducing new backend endpoints: markApi's git calls, /diagnostics for
 * the active model/provider, and the store's previews/workers state.
 *
 * Split into a shared `useProjectInspectorData()` hook (git status/log +
 * diagnostics, polled every 15s) plus focused card exports so each can be
 * mounted in its own Right-zone slot (Project Inspector / Running Apps /
 * Git Status / Model Status) without duplicating the fetch logic.
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

export function Card({ title, icon: Icon, children, action }: { title: string; icon: React.ComponentType<any>; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card border border-border/50 rounded-xl p-4 flex flex-col gap-2"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          <Icon className="w-3.5 h-3.5" />
          {title}
        </div>
        {action}
      </div>
      {children}
    </motion.div>
  );
}

export function useProjectInspectorData() {
  const { serverUrl, workspace } = useMarkStore();
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [commits, setCommits]     = useState<GitCommit[]>([]);
  const [llmCheck, setLlmCheck]   = useState<DiagCheck | null>(null);
  const [loading, setLoading]     = useState(false);

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

  return { gitStatus, commits, llmCheck, loading, refresh };
}

function RefreshButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors border border-border/40 rounded-md px-2 py-1"
    >
      <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
    </button>
  );
}

// ── Running Apps (Right zone) ───────────────────────────────────────────────

export function RunningAppsCard() {
  const { previews } = useMarkStore();
  const activePreviews = previews.filter(p => p.status === 'active');

  return (
    <Card title="Running Apps" icon={Globe}>
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
  );
}

// ── Git Status (Right zone) ─────────────────────────────────────────────────

export function GitStatusCard() {
  const { gitStatus, commits, loading, refresh } = useProjectInspectorData();

  return (
    <div className="flex flex-col gap-3">
      <Card title="Current Branch" icon={GitBranch} action={<RefreshButton loading={loading} onClick={refresh} />}>
        {gitStatus ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="font-mono">{gitStatus.branch}</span>
            {!gitStatus.clean && <span className="text-[10px] text-warning">dirty</span>}
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
    </div>
  );
}

// ── Model Status (Right zone) ───────────────────────────────────────────────

export function ModelStatusCard() {
  const { llmCheck } = useProjectInspectorData();

  return (
    <Card title="Model Status" icon={Sparkles}>
      {llmCheck ? (
        <div className="text-sm">
          <span className="font-medium text-primary">{llmCheck.provider ?? 'unknown'}</span>
          {llmCheck.model && <span className="text-muted-foreground"> · {llmCheck.model}</span>}
        </div>
      ) : (
        <span className="text-sm text-muted-foreground italic">Unavailable</span>
      )}
    </Card>
  );
}

// ── Project Inspector (Right zone — worker + test summary) ─────────────────

export function ProjectInspector() {
  const { workers, lastTestRun } = useMarkStore();
  const runningWorkers = workers.filter(w => w.status === 'running').length;

  return (
    <div className="h-full p-3 flex flex-col gap-3 bg-background overflow-y-auto">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground shrink-0">
        Project Inspector
      </h2>

      <div className="grid grid-cols-1 gap-3">
        <Card title="Test Results" icon={FlaskConical}>
          <div className="flex items-center gap-2 text-sm">
            <span className={cn(
              'text-[10px] px-2 py-0.5 rounded font-mono uppercase tracking-wider border',
              lastTestRun.status === 'passed' && 'bg-success/20 text-success border-success-border',
              lastTestRun.status === 'failed' && 'bg-destructive/20 text-destructive border-destructive/30',
              lastTestRun.status === 'running' && 'bg-primary/20 text-primary border-primary-border',
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
      </div>
    </div>
  );
}
