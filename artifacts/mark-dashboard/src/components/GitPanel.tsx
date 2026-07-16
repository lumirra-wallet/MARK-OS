/**
 * GitPanel — Git history, status, interactive staging, commit, branch management.
 * Feature 12: Better Git Integration.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  GitBranch, GitCommit, RefreshCw, ChevronRight,
  Plus, Minus, Edit3, Trash2, Circle, AlertCircle,
  ArrowUp, ArrowDown, CheckCircle, Send, GitMerge,
  Archive, ArchiveRestore, FileText,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi } from '@/lib/markApi';
import type { GitBranchInfo } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface GitStatusData {
  workspace: string; branch: string; ahead: number; behind: number;
  clean: boolean; changes: { status: string; path: string }[]; error?: string;
}

interface GitCommitInfo {
  hash: string; short: string; message: string;
  author: string; date: string; refs: string;
}

interface StashInfo { ref: string; message: string; when: string; }

// ── Diff renderer ─────────────────────────────────────────────────────────────

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
    'M':  { icon: Edit3,  color: 'text-blue-400',        label: 'Modified' },
    'A':  { icon: Plus,   color: 'text-emerald-400',     label: 'Added' },
    'D':  { icon: Trash2, color: 'text-red-400',         label: 'Deleted' },
    'R':  { icon: Edit3,  color: 'text-amber-400',       label: 'Renamed' },
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

type Tab = 'log' | 'status' | 'stage' | 'branches' | 'stash';

export function GitPanel() {
  const { serverUrl, workspace } = useMarkStore();
  const [status,   setStatus]   = useState<GitStatusData | null>(null);
  const [commits,  setCommits]  = useState<GitCommitInfo[]>([]);
  const [branches, setBranches] = useState<GitBranchInfo[]>([]);
  const [stashes,  setStashes]  = useState<StashInfo[]>([]);
  const [staged,   setStaged]   = useState<{ diff: string; stat: string; files: string[] } | null>(null);
  const [diff,     setDiff]     = useState<string | null>(null);
  const [selRef,   setSelRef]   = useState<string | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [tab,      setTab]      = useState<Tab>('log');

  // Commit form
  const [commitMsg,   setCommitMsg]   = useState('');
  const [committing,  setCommitting]  = useState(false);
  const [commitNotice, setCommitNotice] = useState('');

  // Branch form
  const [newBranch,    setNewBranch]    = useState('');
  const [branchNotice, setBranchNotice] = useState('');

  // Stash form
  const [stashMsg,    setStashMsg]    = useState('');
  const [stashNotice, setStashNotice] = useState('');

  const ws = workspace || undefined;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        markApi.getGitStatus(serverUrl, ws),
        markApi.getGitLog(serverUrl, ws, 50),
      ]);
      setStatus(s as unknown as GitStatusData);
      setCommits(l.commits as unknown as GitCommitInfo[]);
    } catch { /* offline */ } finally { setLoading(false); }
  }, [serverUrl, workspace]);

  const refreshBranches = useCallback(async () => {
    try { const b = await markApi.getGitBranches(serverUrl, ws); setBranches(b.branches); }
    catch { /* offline */ }
  }, [serverUrl, workspace]);

  const refreshStages = useCallback(async () => {
    try { const s = await markApi.getGitStaged(serverUrl, ws); setStaged(s); }
    catch { /* offline */ }
  }, [serverUrl, workspace]);

  const refreshStashes = useCallback(async () => {
    try { const s = await markApi.getGitStashes(serverUrl, ws); setStashes(s.stashes); }
    catch { /* offline */ }
  }, [serverUrl, workspace]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (tab === 'branches') refreshBranches();
    if (tab === 'stage')    refreshStages();
    if (tab === 'stash')    refreshStashes();
  }, [tab]);

  const selectCommit = async (c: GitCommitInfo) => {
    if (selRef === c.hash) { setSelRef(null); setDiff(null); return; }
    setSelRef(c.hash); setDiff('Loading diff…');
    try { const d = await markApi.getGitDiff(serverUrl, c.hash, ws); setDiff(d.diff); }
    catch { setDiff('Failed to load diff.'); }
  };

  const stageAll = async () => {
    await markApi.stageFiles(serverUrl, ['.'], ws);
    refreshStages(); refresh();
  };

  const unstageAll = async () => {
    await markApi.unstageFiles(serverUrl, ['.'], ws);
    refreshStages(); refresh();
  };

  const doCommit = async () => {
    if (!commitMsg.trim()) return;
    setCommitting(true);
    try {
      const r = await markApi.gitCommit(serverUrl, commitMsg, ws);
      setCommitNotice(`✓ Committed ${r.hash}`);
      setCommitMsg('');
      refresh();
      setTimeout(() => setCommitNotice(''), 4000);
    } catch (e) {
      setCommitNotice('✗ ' + String(e));
    }
    setCommitting(false);
  };

  const checkoutBranch = async (name: string) => {
    await markApi.checkoutGitBranch(serverUrl, name, ws);
    refreshBranches(); refresh();
  };

  const createBranch = async () => {
    if (!newBranch.trim()) return;
    try {
      await markApi.createGitBranch(serverUrl, newBranch.trim(), true, ws);
      setBranchNotice(`✓ Created & checked out '${newBranch}'`);
      setNewBranch('');
      refreshBranches(); refresh();
      setTimeout(() => setBranchNotice(''), 4000);
    } catch (e) { setBranchNotice('✗ ' + String(e)); }
  };

  const doStash = async () => {
    await markApi.gitStash(serverUrl, stashMsg, ws);
    setStashMsg(''); refreshStashes(); refresh();
  };

  const doStashPop = async () => {
    await markApi.gitStashPop(serverUrl, ws);
    refreshStashes(); refresh();
    setStashNotice('✓ Stash applied'); setTimeout(() => setStashNotice(''), 3000);
  };

  const relDate = (iso: string) => {
    try {
      const ms = Date.now() - new Date(iso).getTime();
      if (ms < 60_000)    return 'just now';
      if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
      if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
      return `${Math.floor(ms / 86_400_000)}d ago`;
    } catch { return iso.slice(0, 10); }
  };

  const TABS: { id: Tab; label: string }[] = [
    { id: 'log',      label: `Log (${commits.length})` },
    { id: 'status',   label: `Status (${status?.changes.length ?? 0})` },
    { id: 'stage',    label: 'Stage' },
    { id: 'branches', label: `Branches (${branches.length})` },
    { id: 'stash',    label: `Stash (${stashes.length})` },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 bg-card/40 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
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
            <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-400/30">Clean</Badge>
          )}
          {status?.error && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />{status.error}
            </span>
          )}
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/50 shrink-0 overflow-x-auto">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={cn(
              'px-3 py-2 text-xs font-medium whitespace-nowrap transition-colors',
              tab === t.id ? 'border-b-2 border-accent text-accent' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Log Tab ──────────────────────────────────────────────────────────── */}
      {tab === 'log' && (
        <div className="flex flex-1 overflow-hidden">
          <div className="w-1/2 border-r border-border/50 overflow-hidden flex flex-col">
            <ScrollArea className="flex-1">
              <div className="py-2">
                {commits.length === 0 && !loading && (
                  <p className="text-xs text-muted-foreground text-center py-8 italic">No commits found</p>
                )}
                {commits.map(c => (
                  <button key={c.hash} onClick={() => selectCommit(c)}
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
                    </div>
                  </button>
                ))}
              </div>
            </ScrollArea>
          </div>
          <div className="w-1/2 overflow-hidden flex flex-col bg-card/20">
            {diff ? <DiffViewer diff={diff} /> : (
              <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground italic">
                Click a commit to see its diff
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Status Tab ───────────────────────────────────────────────────────── */}
      {tab === 'status' && (
        <ScrollArea className="flex-1">
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
        </ScrollArea>
      )}

      {/* ── Stage & Commit Tab ────────────────────────────────────────────────── */}
      {tab === 'stage' && (
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="flex flex-1 overflow-hidden">
            {/* Staged files list */}
            <div className="w-1/2 border-r border-border/50 flex flex-col">
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/30 bg-muted/10 shrink-0">
                <span className="text-xs font-medium text-muted-foreground">Staged ({staged?.files.length ?? 0})</span>
                <div className="flex gap-1">
                  <button onClick={stageAll} className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30">
                    +All
                  </button>
                  <button onClick={unstageAll} className="text-[10px] px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30">
                    -All
                  </button>
                </div>
              </div>
              <ScrollArea className="flex-1">
                {staged?.files.length ? (
                  staged.files.map(f => (
                    <div key={f} className="flex items-center gap-2 px-3 py-1.5 border-b border-border/20 hover:bg-muted/10">
                      <FileText className="w-3 h-3 text-emerald-400 shrink-0" />
                      <span className="text-[11px] font-mono truncate">{f}</span>
                      <button
                        onClick={() => markApi.unstageFiles(serverUrl, [f], ws).then(refreshStages)}
                        className="ml-auto text-muted-foreground hover:text-red-400"
                      >
                        <Minus className="w-3 h-3" />
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-muted-foreground text-center py-8 italic">Nothing staged</p>
                )}
              </ScrollArea>
              {staged?.stat && (
                <div className="px-3 py-1.5 border-t border-border/30 bg-muted/10 shrink-0">
                  <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap">{staged.stat}</pre>
                </div>
              )}
            </div>

            {/* Staged diff */}
            <div className="w-1/2 overflow-hidden flex flex-col bg-card/20">
              {staged?.diff ? <DiffViewer diff={staged.diff} /> : (
                <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground italic">
                  Stage files to see the diff
                </div>
              )}
            </div>
          </div>

          {/* Commit form */}
          <div className="border-t border-border/50 px-4 py-3 shrink-0 space-y-2">
            <textarea
              value={commitMsg}
              onChange={e => setCommitMsg(e.target.value)}
              placeholder="Commit message…"
              rows={2}
              className="w-full bg-muted/20 border border-border/50 rounded px-2 py-1.5 text-xs resize-none focus:outline-none focus:border-accent/50"
            />
            <div className="flex items-center gap-2">
              <button
                onClick={doCommit}
                disabled={!commitMsg.trim() || committing || !staged?.files.length}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-accent-foreground rounded text-xs font-medium hover:opacity-90 disabled:opacity-40"
              >
                <Send className="w-3 h-3" />
                {committing ? 'Committing…' : 'Commit'}
              </button>
              {commitNotice && (
                <span className={cn('text-xs', commitNotice.startsWith('✓') ? 'text-emerald-400' : 'text-red-400')}>
                  {commitNotice}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Branches Tab ─────────────────────────────────────────────────────── */}
      {tab === 'branches' && (
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Create branch form */}
          <div className="px-4 py-2.5 border-b border-border/50 shrink-0">
            <div className="flex items-center gap-2">
              <input
                value={newBranch}
                onChange={e => setNewBranch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createBranch()}
                placeholder="New branch name…"
                className="flex-1 bg-muted/20 border border-border/50 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-accent/50"
              />
              <button onClick={createBranch} disabled={!newBranch.trim()}
                className="flex items-center gap-1 px-2.5 py-1.5 bg-accent text-accent-foreground rounded text-xs font-medium hover:opacity-90 disabled:opacity-40">
                <Plus className="w-3 h-3" /> Create
              </button>
            </div>
            {branchNotice && (
              <p className={cn('text-xs mt-1', branchNotice.startsWith('✓') ? 'text-emerald-400' : 'text-red-400')}>
                {branchNotice}
              </p>
            )}
          </div>

          <ScrollArea className="flex-1">
            {branches.map(b => (
              <div key={b.name} className={cn(
                'flex items-center gap-3 px-4 py-2.5 border-b border-border/20 hover:bg-muted/10 transition-colors',
                b.current && 'bg-accent/5',
              )}>
                <GitBranch className={cn('w-3.5 h-3.5 shrink-0', b.current ? 'text-accent' : 'text-muted-foreground')} />
                <div className="flex-1 min-w-0">
                  <p className={cn('text-xs font-medium font-mono', b.current && 'text-accent')}>{b.name}</p>
                  {b.subject && <p className="text-[10px] text-muted-foreground truncate">{b.subject}</p>}
                </div>
                {b.current ? (
                  <Badge variant="outline" className="text-[10px] text-accent border-accent/30">current</Badge>
                ) : (
                  <button onClick={() => checkoutBranch(b.name)}
                    className="text-[10px] px-2 py-0.5 rounded bg-muted/40 hover:bg-accent/20 hover:text-accent transition-colors">
                    checkout
                  </button>
                )}
              </div>
            ))}
            {branches.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-8 italic">No branches found</p>
            )}
          </ScrollArea>
        </div>
      )}

      {/* ── Stash Tab ─────────────────────────────────────────────────────────── */}
      {tab === 'stash' && (
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border/50 shrink-0 space-y-2">
            <div className="flex items-center gap-2">
              <input
                value={stashMsg}
                onChange={e => setStashMsg(e.target.value)}
                placeholder="Stash message (optional)…"
                className="flex-1 bg-muted/20 border border-border/50 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-accent/50"
              />
              <button onClick={doStash}
                className="flex items-center gap-1 px-2.5 py-1.5 bg-muted/40 hover:bg-muted/60 rounded text-xs font-medium">
                <Archive className="w-3 h-3" /> Stash
              </button>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={doStashPop} disabled={stashes.length === 0}
                className="flex items-center gap-1 px-2.5 py-1.5 bg-accent/20 text-accent rounded text-xs font-medium hover:bg-accent/30 disabled:opacity-40">
                <ArchiveRestore className="w-3 h-3" /> Pop
              </button>
              {stashNotice && <span className="text-xs text-emerald-400">{stashNotice}</span>}
            </div>
          </div>

          <ScrollArea className="flex-1">
            {stashes.map((s, i) => (
              <div key={i} className="px-4 py-2.5 border-b border-border/20 hover:bg-muted/10">
                <p className="text-xs font-medium">{s.message || `stash@{${i}}`}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">{s.ref} · {s.when}</p>
              </div>
            ))}
            {stashes.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-8 italic">No stashes</p>
            )}
          </ScrollArea>
        </div>
      )}
    </div>
  );
}
