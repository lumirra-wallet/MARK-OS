/**
 * Checkpoints Panel — Feature 10.
 *
 * Creates, lists, and restores workspace snapshots. Every checkpoint captures
 * git state, the conversation, and the pipeline state.
 */
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import {
  Bookmark, Plus, RotateCcw, Trash2, GitCommit, RefreshCw,
  CheckCircle, AlertTriangle,
} from 'lucide-react';

interface Checkpoint {
  id:         string;
  label:      string;
  created_at: string;
  workspace:  string;
  goal:       string;
  git_hash:   string;
  git_branch: string;
  git_tag:    string;
}

export function CheckpointsPanel() {
  const { serverUrl, workspace, messages } = useMarkStore();
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [creating, setCreating] = useState(false);
  const [label,    setLabel]    = useState('');
  const [notice,   setNotice]   = useState<{ text: string; ok: boolean } | null>(null);

  const _notice = (text: string, ok = true) => {
    setNotice({ text, ok });
    setTimeout(() => setNotice(null), 4000);
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetch(`${serverUrl}/checkpoints`).then(r => r.json());
      setCheckpoints(data.checkpoints || []);
    } catch { /* offline */ }
    setLoading(false);
  };

  useEffect(() => { load(); }, [serverUrl]);

  const create = async () => {
    setCreating(true);
    try {
      const body = {
        workspace: workspace || '.',
        label:     label.trim() || `Checkpoint ${new Date().toLocaleTimeString()}`,
        goal:      (messages.find(m => m.role === 'user')?.text as string) || '',
        messages:  messages.slice(-20),
        pipeline:  [],
      };
      const res  = await fetch(`${serverUrl}/checkpoints`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      if (res.ok) {
        _notice('Checkpoint created');
        setLabel('');
        load();
      } else {
        _notice('Failed to create checkpoint', false);
      }
    } catch (e) {
      _notice(String(e), false);
    }
    setCreating(false);
  };

  const restore = async (cp: Checkpoint) => {
    if (!confirm(`Restore checkpoint "${cp.label}"? This will checkout git tag ${cp.git_tag}.`)) return;
    try {
      const res = await fetch(`${serverUrl}/checkpoints/${cp.id}/restore`, { method: 'POST' });
      const data = await res.json();
      if (data.success) _notice(`Restored "${cp.label}"`);
      else _notice(data.detail || 'Restore failed', false);
    } catch (e) {
      _notice(String(e), false);
    }
  };

  const remove = async (cp: Checkpoint) => {
    if (!confirm(`Delete checkpoint "${cp.label}"?`)) return;
    await fetch(`${serverUrl}/checkpoints/${cp.id}`, { method: 'DELETE' });
    load();
  };

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Bookmark className="w-4 h-4 text-accent" />
          <span className="font-semibold">Checkpoints</span>
          <span className="text-xs text-muted-foreground">({checkpoints.length})</span>
        </div>
        <button onClick={load} className="p-1 hover:bg-muted/40 rounded">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Create form */}
      <div className="px-4 py-3 border-b border-border/50 space-y-2 shrink-0">
        <input
          value={label}
          onChange={e => setLabel(e.target.value)}
          placeholder="Checkpoint label (optional)"
          className="w-full bg-muted/20 border border-border/50 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-accent/50"
        />
        <button
          onClick={create}
          disabled={creating}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-accent-foreground rounded text-xs font-medium hover:opacity-90 disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          {creating ? 'Creating…' : 'Create Checkpoint'}
        </button>

        {notice && (
          <div className={cn(
            'flex items-center gap-1.5 text-xs px-2 py-1 rounded',
            notice.ok ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400',
          )}>
            {notice.ok ? <CheckCircle className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
            {notice.text}
          </div>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {checkpoints.length === 0 && !loading ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
            <Bookmark className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs">No checkpoints yet</p>
          </div>
        ) : (
          <div className="space-y-0">
            {checkpoints.map(cp => (
              <div
                key={cp.id}
                className="flex items-start gap-3 px-4 py-3 border-b border-border/30 hover:bg-muted/10 transition-colors group"
              >
                <div className="mt-0.5 p-1.5 bg-accent/10 rounded shrink-0">
                  <Bookmark className="w-3.5 h-3.5 text-accent" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{cp.label}</p>
                  <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <GitCommit className="w-3 h-3" />
                      {cp.git_branch} · {cp.git_hash.slice(0, 7)}
                    </span>
                    <span>{new Date(cp.created_at).toLocaleString()}</span>
                  </div>
                  {cp.goal && (
                    <p className="text-xs text-muted-foreground/70 mt-0.5 truncate">{cp.goal}</p>
                  )}
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <button
                    onClick={() => restore(cp)}
                    className="p-1 hover:bg-muted/40 rounded text-amber-400"
                    title="Restore"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(cp)}
                    className="p-1 hover:bg-muted/40 rounded text-red-400"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
