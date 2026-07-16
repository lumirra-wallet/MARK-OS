/**
 * GitPanel — Git history, status, and diff viewer.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  GitBranch, GitCommit, RefreshCw, ChevronRight,
  Plus, Minus, Edit3, Trash2, Circle, AlertCircle,
  ArrowUp, ArrowDown,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface GitStatusData {
  workspace: string;
  branch:    string;
  ahead:     number;
  behind:    number;
  clean:     boolean;
  changes:   { status: string; path: string }[];
  error?:    string;
}

interface GitCommit {
  hash:    string;
  short:   string;
  message: string;
  author:  string;
  date:    string;
  refs:    string;
}

// ── Diff renderer (line-by-line coloring) ─────────────────────────────────────

function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n');
  return (
    <ScrollArea className="h-full">
      <pre className="text-[11px] font-mono leading-5 p-4 whitespace-pre-wrap break-all">
        {lines.map((line, i) => {
          const cls = line.startsWith('+') && !line.startsWith('+++')
            ? 'bg-emerald-500/10 text-emerald-400'
            : line.startsWith('-') && !line.startsWith('---')
              ? 'bg-red-500/10 text-red-400'
              : line.startsWith('@@')
                ? 'text-blue-400/80 bg-blue-500/5'
                : line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')
                  ? 'text-muted-foreground'
                  : 'text-foreground';
          return (
            <span key={i} className={cn('block px-1 rounded-sm', cls)}>
              {line || '\u00a0'}
            </span>
          );
        })}
      </pre>
    </ScrollArea>
  );
}

// ── Status icons ──────────────────────────────────────────────────────────────

function StatusBadge({ code }: { code: string }) {
  const map: Record<string, { icon: React.ComponentType<any>; color: string; label: string }> = {
    'M':  { icon: Edit3,  color: 'text-blue-400',   label: 'Modified' },
    'A':  { icon: Plus,   color: 'text-emerald-400', label: 'Added' },
    'D':  { icon: Trash2, color: 'text-red-400',     label: 'Deleted' },
    'R':  { icon: Edit3,  color: 'text-amber-400',   label: 'Renamed' },
    '?':  { icon: Circle, color: 'text-muted-foreground', label: 'Untracked' },
    '??': { icon: Circle, color: 'text-muted-foreground', label: 'Untracked' },
  };
  const m = map[code] ?? map['M'];
  const Icon = m.icon;
  return (
    <Badge variant="outline" className={cn('text-[10px] h-4 px-1 border-current/30', m.color)}>
      <Icon className="w-2.5 h-2.5 mr-0.5" />
      {m.label}
    </Badge>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function GitPanel() {
  const { serverUrl, workspace } = useMarkStore();
  const [status,  setStatus]  = useState<GitStatusData | null>(null);
  const [commits, setCommits] = useState<GitCommit[]>([]);
  const [diff,    setDiff]    = useState<string | null>(null);
  const [selRef,  setSelRef]  = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab,     setTab]     = useState<'log' | 'status'>('log');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        markApi.getGitStatus(serverUrl, workspace || undefined),
        markApi.getGitLog(serverUrl, workspace || undefined, 50),
      ]);
      setStatus(s as unknown as GitStatusData);
      setCommits(l.commits);
    } catch (err) {
      console.error('git refresh', err);
    } finally {
      setLoading(false);
    }
  }, [serverUrl, workspace]);

  useEffect(() => { refresh(); }, [refresh]);

  const selectCommit = async (commit: GitCommit) => {
    if (selRef === commit.hash) { setSelRef(null); setDiff(null); return; }
    setSelRef(commit.hash);
    setDiff('Loading diff…');
    try {
      const d = await markApi.getGitDiff(serverUrl, commit.hash, workspace || undefined);
      setDiff(d.diff);
    } catch {
      setDiff('Failed to load diff.');
    }
  };

  const relDate = (iso: string) => {
    try {
      const d = new Date(iso);
      const ms = Date.now() - d.getTime();
      if (ms < 60_000)  return 'just now';
      if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
      if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
      return `${Math.floor(ms / 86_400_000)}d ago`;
    } catch { return iso.slice(0, 10); }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-card/40 shrink-0">
        <div className="flex items-center gap-2">
          {status?.branch && (
            <div className="flex items-center gap-1.5 text-sm font-mono font-medium">
              <GitBranch className="w-4 h-4 text-accent" />
              {status.branch}
              {status.ahead > 0 && (
                <span className="flex items-center gap-0.5 text-[10px] text-emerald-400">
                  <ArrowUp className="w-3 h-3" />{status.ahead}
                </span>
              )}
              {status.behind > 0 && (
                <span className="flex items-center gap-0.5 text-[10px] text-amber-400">
                  <ArrowDown className="w-3 h-3" />{status.behind}
                </span>
              )}
            </div>
          )}
          {status?.clean === false && (
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-400/30">
              {status.changes.length} changed
            </Badge>
          )}
          {status?.clean && (
            <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-400/30">
              Clean
            </Badge>
          )}
          {status?.error && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {status.error}
            </span>
          )}
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/50 shrink-0">
        {(['log', 'status'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              'flex-1 py-2 text-xs font-medium capitalize transition-colors',
              tab === t ? 'border-b-2 border-accent text-accent' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t === 'log' ? `Log (${commits.length})` : `Status (${status?.changes.length ?? 0})`}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left — list */}
        <div className="w-1/2 border-r border-border/50 overflow-hidden flex flex-col">
          <ScrollArea className="flex-1">
            {tab === 'log' ? (
              <div className="py-2">
                {commits.length === 0 && !loading && (
                  <p className="text-xs text-muted-foreground text-center py-8 italic">No commits found</p>
                )}
                {commits.map(c => (
                  <motion.button
                    key={c.hash}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    onClick={() => selectCommit(c)}
                    className={cn(
                      'w-full text-left px-4 py-2.5 hover:bg-muted/40 transition-colors border-b border-border/20',
                      selRef === c.hash && 'bg-accent/10 border-l-2 border-l-accent',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <GitCommit className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate">{c.message}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <code className="text-[10px] font-mono text-accent">{c.short}</code>
                          <span className="text-[10px] text-muted-foreground truncate">{c.author}</span>
                          <span className="text-[10px] text-muted-foreground ml-auto shrink-0">{relDate(c.date)}</span>
                        </div>
                        {c.refs && (
                          <div className="flex gap-1 mt-0.5 flex-wrap">
                            {c.refs.split(',').filter(Boolean).map(r => (
                              <span key={r.trim()} className="text-[9px] bg-accent/15 text-accent rounded px-1">{r.trim()}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                    </div>
                  </motion.button>
                ))}
              </div>
            ) : (
              <div className="py-2">
                {(!status?.changes || status.changes.length === 0) && (
                  <p className="text-xs text-muted-foreground text-center py-8 italic">Working tree clean</p>
                )}
                {status?.changes.map((ch, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-2 hover:bg-muted/30 transition-colors border-b border-border/20">
                    <StatusBadge code={ch.status} />
                    <span className="text-xs font-mono text-foreground truncate">{ch.path}</span>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>

        {/* Right — diff */}
        <div className="w-1/2 overflow-hidden flex flex-col bg-card/20">
          {diff ? (
            <DiffViewer diff={diff} />
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground italic">
              {tab === 'log' ? 'Click a commit to see its diff' : 'Select a file to diff'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
