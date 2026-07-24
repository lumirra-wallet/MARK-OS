/**
 * Tools Panel — Feature 3 (Tool Calling Framework), Feature 18 (Plugins), Feature 19 (Security).
 *
 * Lists all registered tools, lets the user invoke them, and shows the audit log.
 */
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { markApi } from '@/lib/markApi';
import { useMarkStore } from '@/store/markStore';
import {
  Wrench, Play, Shield, ChevronDown, ChevronRight,
  CheckCircle, XCircle, Package, RefreshCw, Plug,
} from 'lucide-react';

interface Tool {
  id: string; name: string; description: string;
  version: string; author: string; category: string;
  status: 'enabled' | 'disabled'; permissions: string[];
}

interface AuditEntry {
  ts: string; action: string; tool_id: string;
  params: Record<string, unknown>; result_ok: boolean;
  elapsed_ms: number; allowed: boolean;
}

interface Plugin {
  name: string; version: string; description: string;
  tools: string[]; permissions: string[]; has_ui: boolean; status: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  filesystem: 'text-blue-400',
  system:     'text-purple-400',
  utilities:  'text-amber-400',
  text:       'text-green-400',
  future:     'text-muted-foreground',
};

export function ToolsPanel() {
  const { serverUrl, workspace } = useMarkStore();
  const [tools,    setTools]    = useState<Tool[]>([]);
  const [plugins,  setPlugins]  = useState<Plugin[]>([]);
  const [audit,    setAudit]    = useState<AuditEntry[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [selected, setSelected] = useState<Tool | null>(null);
  const [params,   setParams]   = useState('{}');
  const [running,  setRunning]  = useState(false);
  const [result,   setResult]   = useState<unknown>(null);
  const [tab,      setTab]      = useState<'tools' | 'plugins' | 'audit'>('tools');

  const load = async () => {
    setLoading(true);
    try {
      const [t, a, p] = await Promise.all([
        fetch(`${serverUrl}/tools`).then(r => r.json()),
        fetch(`${serverUrl}/tools/audit?limit=50`).then(r => r.json()),
        fetch(`${serverUrl}/plugins?workspace=${encodeURIComponent(workspace || '.')}`).then(r => r.json()),
      ]);
      setTools(t.tools   || []);
      setAudit(a.entries || []);
      setPlugins(p.plugins || []);
    } catch { /* server offline */ }
    setLoading(false);
  };

  useEffect(() => { load(); }, [serverUrl, workspace]);

  const runTool = async () => {
    if (!selected) return;
    setRunning(true);
    setResult(null);
    try {
      let parsed = {};
      try { parsed = JSON.parse(params); } catch { /* ignore */ }
      const res = await fetch(`${serverUrl}/tools/${selected.id}/execute`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ params: parsed, workspace: workspace || '.' }),
      });
      setResult(await res.json());
    } catch (e) {
      setResult({ error: String(e) });
    }
    setRunning(false);
    load(); // refresh audit
  };

  const toggleStatus = async (tool: Tool) => {
    const action = tool.status === 'enabled' ? 'disable' : 'enable';
    await fetch(`${serverUrl}/tools/${tool.id}/${action}`, { method: 'POST' });
    load();
  };

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-accent" />
          <span className="font-semibold">Tools & Plugins</span>
          <span className="text-xs text-muted-foreground ml-1">({tools.length} tools)</span>
        </div>
        <button onClick={load} className="p-1 hover:bg-muted/40 rounded">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/50 shrink-0">
        {(['tools', 'plugins', 'audit'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              'px-4 py-2 text-xs font-medium capitalize transition-colors',
              tab === t ? 'border-b-2 border-accent text-accent' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t === 'audit' ? <><Shield className="w-3 h-3 inline mr-1" />Audit</> : t}
          </button>
        ))}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Tool list / plugin list / audit */}
        {tab === 'tools' && (
          <>
            <div className="w-56 border-r border-border/50 overflow-y-auto shrink-0">
              {tools.length === 0 && !loading && (
                <p className="text-xs text-muted-foreground p-4 text-center">No tools loaded<br/>Start the MSART OS server</p>
              )}
              {tools.map(tool => (
                <button
                  key={tool.id}
                  onClick={() => { setSelected(tool); setResult(null); setParams('{}'); }}
                  className={cn(
                    'w-full text-left px-3 py-2.5 hover:bg-muted/30 transition-colors border-b border-border/20',
                    selected?.id === tool.id && 'bg-muted/50',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium truncate">{tool.name}</span>
                    <span className={cn('w-1.5 h-1.5 rounded-full ml-1',
                      tool.status === 'enabled' ? 'bg-emerald-400' : 'bg-muted-foreground/40',
                    )} />
                  </div>
                  <div className={cn('text-xs mt-0.5', CATEGORY_COLORS[tool.category] || 'text-muted-foreground')}>
                    {tool.category}
                  </div>
                </button>
              ))}
            </div>

            {/* Tool detail + executor */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {selected ? (
                <>
                  <div>
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold">{selected.name}</h3>
                      <button
                        onClick={() => toggleStatus(selected)}
                        className={cn(
                          'text-xs px-2 py-0.5 rounded',
                          selected.status === 'enabled'
                            ? 'bg-emerald-500/20 text-emerald-400 hover:bg-red-500/20 hover:text-red-400'
                            : 'bg-muted/40 text-muted-foreground hover:bg-emerald-500/20 hover:text-emerald-400',
                        )}
                      >
                        {selected.status}
                      </button>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{selected.description}</p>
                    <div className="flex gap-2 mt-2">
                      <span className={cn('text-xs px-1.5 py-0.5 bg-muted/40 rounded', CATEGORY_COLORS[selected.category])}>
                        {selected.category}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 bg-muted/40 rounded text-muted-foreground">
                        v{selected.version}
                      </span>
                    </div>
                    {selected.permissions.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {selected.permissions.map(p => (
                          <span key={p} className="text-[10px] px-1 py-0.5 bg-amber-500/10 text-amber-400 rounded">
                            <Shield className="w-2.5 h-2.5 inline mr-0.5" />{p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Parameters (JSON)</label>
                    <textarea
                      value={params}
                      onChange={e => setParams(e.target.value)}
                      rows={4}
                      className="w-full bg-muted/20 border border-border/50 rounded p-2 text-xs font-mono resize-none focus:outline-none focus:border-accent/50"
                    />
                    <button
                      onClick={runTool}
                      disabled={running || selected.status !== 'enabled'}
                      className="mt-2 flex items-center gap-1.5 px-3 py-1.5 bg-accent text-accent-foreground rounded text-xs font-medium hover:opacity-90 disabled:opacity-50"
                    >
                      <Play className="w-3 h-3" />
                      {running ? 'Running…' : 'Execute'}
                    </button>
                  </div>

                  {result && (
                    <div className="bg-muted/20 border border-border/50 rounded p-3">
                      <div className="flex items-center gap-1.5 mb-2">
                        {(result as any).success
                          ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                          : <XCircle    className="w-3.5 h-3.5 text-red-400" />
                        }
                        <span className="text-xs font-medium">
                          {(result as any).success ? 'Success' : 'Failed'}
                          {(result as any).elapsed_ms && ` · ${(result as any).elapsed_ms}ms`}
                        </span>
                      </div>
                      <pre className="text-xs font-mono whitespace-pre-wrap break-all text-foreground/80">
                        {(result as any).output || JSON.stringify(result, null, 2)}
                      </pre>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
                  <Wrench className="w-8 h-8 mb-2 opacity-30" />
                  <p className="text-xs">Select a tool to inspect and run it</p>
                </div>
              )}
            </div>
          </>
        )}

        {tab === 'plugins' && (
          <div className="flex-1 overflow-y-auto p-4 space-y-2">
            {plugins.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
                <Package className="w-8 h-8 mb-2 opacity-30" />
                <p className="text-xs text-center">
                  No plugins found.<br/>
                  Add a <code className="text-accent">plugins/</code> folder to your workspace<br/>
                  with a <code className="text-accent">plugin.json</code> manifest.
                </p>
              </div>
            ) : plugins.map(p => (
              <div key={p.name} className="bg-muted/20 border border-border/50 rounded p-3">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-sm flex items-center gap-1.5">
                      <Plug className="w-3.5 h-3.5 text-accent" />
                      {p.name}
                      <span className="text-xs text-muted-foreground">v{p.version}</span>
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">{p.description}</p>
                  </div>
                  <span className={cn(
                    'text-[10px] px-1.5 py-0.5 rounded',
                    p.status === 'installed' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400',
                  )}>
                    {p.status}
                  </span>
                </div>
                {p.tools.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {p.tools.map((t: string) => (
                      <span key={t} className="text-[10px] px-1 py-0.5 bg-muted/40 rounded">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === 'audit' && (
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border/50">
                  {['Time', 'Tool', 'Action', 'ms', 'OK', 'Allowed'].map(h => (
                    <th key={h} className="px-3 py-1.5 text-left text-muted-foreground font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {audit.map((e, i) => (
                  <tr key={i} className="border-b border-border/20 hover:bg-muted/10">
                    <td className="px-3 py-1.5 text-muted-foreground font-mono">{e.ts.slice(11, 19)}</td>
                    <td className="px-3 py-1.5 font-medium">{e.tool_id}</td>
                    <td className="px-3 py-1.5">{e.action}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{e.elapsed_ms}</td>
                    <td className="px-3 py-1.5">
                      {e.result_ok ? <CheckCircle className="w-3 h-3 text-emerald-400" /> : <XCircle className="w-3 h-3 text-red-400" />}
                    </td>
                    <td className="px-3 py-1.5">
                      {e.allowed ? <CheckCircle className="w-3 h-3 text-emerald-400" /> : <XCircle className="w-3 h-3 text-red-400" />}
                    </td>
                  </tr>
                ))}
                {audit.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">No audit entries yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
