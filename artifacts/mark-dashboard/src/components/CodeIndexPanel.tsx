/**
 * Code Index Panel — Features 5 (RAG), 6 (Codebase Indexer).
 *
 * Lets the user trigger indexing, search symbols, find references,
 * and perform RAG-style retrieval over the codebase.
 */
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import {
  Code2, Search, RefreshCw, Loader2, Database,
  Hash, GitFork, FileCode, Zap,
} from 'lucide-react';

interface Symbol {
  name:      string;
  kind:      string;
  line:      number;
  file:      string;
  docstring: string;
  language?: string;
  score?:    number;
}

interface Stats {
  workspace:   string;
  indexed_at:  string;
  files:       number;
  symbols:     number;
  total_lines: number;
  by_language: Record<string, number>;
}

const KIND_COLORS: Record<string, string> = {
  function: 'text-blue-400',
  class:    'text-purple-400',
  arrow_fn: 'text-green-400',
};

export function CodeIndexPanel() {
  const { serverUrl, workspace } = useMarkStore();
  const [stats,    setStats]    = useState<Stats | null>(null);
  const [query,    setQuery]    = useState('');
  const [results,  setResults]  = useState<Symbol[]>([]);
  const [indexing, setIndexing] = useState(false);
  const [searching, setSearching] = useState(false);
  const [tab,      setTab]      = useState<'search' | 'rag' | 'stats'>('search');

  const loadStats = async () => {
    try {
      const data = await fetch(`${serverUrl}/code/stats`).then(r => r.json());
      if (data.workspace) setStats(data);
    } catch { /* offline */ }
  };

  useEffect(() => { loadStats(); }, [serverUrl]);

  const reindex = async () => {
    setIndexing(true);
    try {
      await fetch(`${serverUrl}/code/index`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ workspace: workspace || '.' }),
      });
      await loadStats();
    } catch { /* offline */ }
    setIndexing(false);
  };

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const endpoint = tab === 'rag'
        ? `${serverUrl}/rag/search?q=${encodeURIComponent(query)}&workspace=${encodeURIComponent(workspace || '.')}&limit=20`
        : `${serverUrl}/code/search?q=${encodeURIComponent(query)}&limit=30`;
      const data = await fetch(endpoint).then(r => r.json());
      setResults(data.results || data.chunks || []);
    } catch { /* offline */ }
    setSearching(false);
  };

  const onKey = (e: React.KeyboardEvent) => { if (e.key === 'Enter') search(); };

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Code2 className="w-4 h-4 text-accent" />
          <span className="font-semibold">Codebase Index</span>
          {stats && (
            <span className="text-xs text-muted-foreground">
              {stats.files} files · {stats.symbols} symbols
            </span>
          )}
        </div>
        <button onClick={reindex} disabled={indexing} className="flex items-center gap-1 px-2 py-1 text-xs bg-muted/30 hover:bg-muted/50 rounded disabled:opacity-50">
          {indexing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          Index
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/40 shrink-0">
        {(['search', 'rag', 'stats'] as const).map(t => (
          <button key={t} onClick={() => { setTab(t); setResults([]); }}
            className={cn('px-4 py-2 text-xs font-medium capitalize transition-colors',
              tab === t ? 'border-b-2 border-accent text-accent' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t === 'rag' ? <><Zap className="w-3 h-3 inline mr-0.5" />RAG Search</> : t}
          </button>
        ))}
      </div>

      {tab !== 'stats' && (
        <div className="px-3 py-2 border-b border-border/40 shrink-0">
          <div className="flex items-center gap-2">
            <Search className="w-3.5 h-3.5 text-muted-foreground" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={onKey}
              placeholder={tab === 'rag' ? 'Ask a question about the codebase…' : 'Search symbols, classes, functions…'}
              className="flex-1 bg-transparent text-xs focus:outline-none placeholder:text-muted-foreground/50"
            />
            {searching && <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {tab === 'stats' && stats ? (
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Files',   val: stats.files,       icon: <FileCode className="w-3.5 h-3.5 text-accent" /> },
                { label: 'Symbols', val: stats.symbols,     icon: <Hash     className="w-3.5 h-3.5 text-purple-400" /> },
                { label: 'Lines',   val: stats.total_lines, icon: <Code2    className="w-3.5 h-3.5 text-blue-400" /> },
                { label: 'Languages', val: Object.keys(stats.by_language).length, icon: <Database className="w-3.5 h-3.5 text-green-400" /> },
              ].map(item => (
                <div key={item.label} className="bg-muted/20 border border-border/50 rounded p-3">
                  <div className="flex items-center gap-1.5 mb-0.5">{item.icon}<span className="text-xs text-muted-foreground">{item.label}</span></div>
                  <p className="text-lg font-bold">{item.val.toLocaleString()}</p>
                </div>
              ))}
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-2">By Language</p>
              {Object.entries(stats.by_language).map(([lang, count]) => (
                <div key={lang} className="flex items-center gap-2 py-1">
                  <span className="text-xs w-20 truncate text-muted-foreground">{lang}</span>
                  <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                    <div className="h-full bg-accent rounded-full" style={{ width: `${(count / stats.files) * 100}%` }} />
                  </div>
                  <span className="text-xs text-muted-foreground w-6 text-right">{count}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground">
              Indexed: {stats.indexed_at ? new Date(stats.indexed_at).toLocaleString() : 'never'}<br/>
              Workspace: {stats.workspace || 'n/a'}
            </p>
          </div>
        ) : results.length === 0 && !searching ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
            <Code2 className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs text-center">
              {stats ? 'Enter a query above to search symbols' : 'Click Index to analyze your codebase'}
            </p>
          </div>
        ) : (
          <div className="space-y-0">
            {results.map((sym, i) => (
              <div key={i} className="px-4 py-2 border-b border-border/20 hover:bg-muted/10">
                <div className="flex items-baseline gap-2">
                  <span className={cn('text-xs font-medium font-mono', KIND_COLORS[sym.kind] || 'text-foreground')}>
                    {sym.name}
                  </span>
                  <span className="text-[10px] text-muted-foreground">{sym.kind}</span>
                  {sym.score !== undefined && (
                    <span className="text-[10px] text-accent/70 ml-auto">score: {sym.score}</span>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                  {sym.file}:{sym.line}
                </p>
                {sym.docstring && (
                  <p className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{sym.docstring}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
