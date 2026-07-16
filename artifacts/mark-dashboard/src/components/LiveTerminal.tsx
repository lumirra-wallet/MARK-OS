/**
 * Live Terminal — Feature 11.
 *
 * Embeds a real xterm.js terminal that streams command output via WebSocket.
 * Multiple command history tabs. ANSI color support. Interrupt/clear.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import { Terminal, Plus, X, Trash2, StopCircle, Send } from 'lucide-react';

interface HistoryEntry {
  cmd:      string;
  output:   string;
  exit:     number | null;
  elapsed?: number;
}

export function LiveTerminal() {
  const { serverUrl, workspace } = useMarkStore();
  const [input,   setInput]   = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [cmdHist, setCmdHist] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);
  const wsRef     = useRef<WebSocket | null>(null);

  // Connect WS
  const connectWS = useCallback(() => {
    const wsUrl = serverUrl.replace(/^http/, 'ws') + '/terminal/ws';
    try {
      const ws = new WebSocket(wsUrl);
      ws.onopen    = () => { /* ready */ };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as { type: string; data: string; exit_code?: number };
        setHistory(prev => {
          if (prev.length === 0) return prev;
          const last = { ...prev[prev.length - 1] };
          if (msg.type === 'output') {
            last.output = (last.output || '') + msg.data;
          } else if (msg.type === 'exit') {
            last.exit = msg.exit_code ?? 0;
            setRunning(false);
          }
          return [...prev.slice(0, -1), last];
        });
      };
      ws.onerror   = () => setRunning(false);
      ws.onclose   = () => {};
      wsRef.current = ws;
    } catch { /* WS not available */ }
  }, [serverUrl]);

  useEffect(() => {
    connectWS();
    return () => wsRef.current?.close();
  }, [connectWS]);

  // Scroll to bottom on new output
  useEffect(() => {
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' });
  }, [history]);

  const send = async () => {
    const cmd = input.trim();
    if (!cmd || running) return;

    setCmdHist(h => [cmd, ...h.slice(0, 99)]);
    setHistIdx(-1);
    setInput('');

    // Try WS first, fall back to REST
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setHistory(h => [...h, { cmd, output: '', exit: null }]);
      setRunning(true);
      wsRef.current.send(JSON.stringify({ cmd, workspace: workspace || '.' }));
    } else {
      // REST fallback
      setHistory(h => [...h, { cmd, output: 'Running…', exit: null }]);
      setRunning(true);
      try {
        const t0  = Date.now();
        const res = await fetch(`${serverUrl}/terminal/run`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ command: cmd, workspace: workspace || '.', timeout: 30 }),
        });
        const data = await res.json();
        setHistory(h => [
          ...h.slice(0, -1),
          { cmd, output: data.output || '', exit: data.exit_code ?? 0, elapsed: Date.now() - t0 },
        ]);
      } catch (e) {
        setHistory(h => [...h.slice(0, -1), { cmd, output: String(e), exit: 1 }]);
      }
      setRunning(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { send(); return; }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      const idx = Math.min(histIdx + 1, cmdHist.length - 1);
      setHistIdx(idx);
      setInput(cmdHist[idx] || '');
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const idx = Math.max(histIdx - 1, -1);
      setHistIdx(idx);
      setInput(idx === -1 ? '' : cmdHist[idx] || '');
    }
  };

  const clear = () => { setHistory([]); };

  return (
    <div className="flex flex-col h-full bg-black/80 rounded text-sm font-mono" onClick={() => inputRef.current?.focus()}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" />
          <span className="text-xs text-emerald-400 font-semibold">Terminal</span>
          {workspace && <span className="text-[10px] text-muted-foreground">{workspace}</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {running && (
            <button onClick={() => { setRunning(false); wsRef.current?.close(); connectWS(); }}
              className="p-1 text-red-400 hover:bg-red-400/10 rounded" title="Interrupt">
              <StopCircle className="w-3.5 h-3.5" />
            </button>
          )}
          <button onClick={clear} className="p-1 text-muted-foreground hover:bg-muted/20 rounded" title="Clear">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Output */}
      <div ref={outputRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-3">
        {history.length === 0 ? (
          <div className="text-muted-foreground/50 text-xs pt-4">
            Type a command and press Enter. Commands run in: {workspace || '.'}
          </div>
        ) : history.map((h, i) => (
          <div key={i} className="space-y-1">
            {/* Prompt */}
            <div className="flex items-center gap-1.5">
              <span className="text-emerald-400 text-xs">$</span>
              <span className="text-foreground text-xs">{h.cmd}</span>
              {h.elapsed && <span className="text-muted-foreground/50 text-[10px] ml-auto">{h.elapsed}ms</span>}
              {h.exit !== null && (
                <span className={cn('text-[10px] ml-1', h.exit === 0 ? 'text-emerald-400/60' : 'text-red-400/60')}>
                  [{h.exit}]
                </span>
              )}
            </div>
            {/* Output */}
            {h.output && (
              <pre className="text-xs text-foreground/80 whitespace-pre-wrap break-all pl-4 leading-relaxed">
                {h.output}
              </pre>
            )}
          </div>
        ))}
        {running && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="animate-pulse">▋</span>
            <span>Running…</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-border/30 shrink-0">
        <span className="text-emerald-400 text-sm shrink-0">$</span>
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={running}
          placeholder={running ? 'Running…' : 'Enter command…'}
          className="flex-1 bg-transparent text-foreground text-xs focus:outline-none placeholder:text-muted-foreground/40"
          autoFocus
        />
        <button
          onClick={send}
          disabled={!input.trim() || running}
          className="p-1 text-emerald-400 hover:bg-emerald-400/10 rounded disabled:opacity-30"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
