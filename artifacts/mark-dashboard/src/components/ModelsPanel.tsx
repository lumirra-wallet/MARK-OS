/**
 * ModelsPanel — View available Ollama models and switch the active one.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Cpu, RefreshCw, CheckCircle2, Circle, Zap, HardDrive,
  AlertTriangle, ExternalLink, Server,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface OllamaModel {
  name:     string;
  size_gb:  number;
  modified: string;
  family:   string;
  params:   string;
}

export function ModelsPanel() {
  const { serverUrl } = useMarkStore();
  const [models,   setModels]   = useState<OllamaModel[]>([]);
  const [active,   setActive]   = useState<string>('');
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string>('');
  const [switching, setSwitching] = useState<string>('');
  const [routes,   setRoutes]   = useState<Record<string, string>>({});
  const [routeTab, setRouteTab] = useState(false);
  const [editRoute, setEditRoute] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await markApi.getModels(serverUrl) as any;
      setModels(data.models ?? []);
      setActive(data.active ?? '');
      if (data.error) setError(data.error);
    } catch (err: any) {
      setError(err.message ?? 'Failed to load models');
    } finally {
      setLoading(false);
    }
  }, [serverUrl]);

  useEffect(() => { refresh(); }, [refresh]);

  const switchTo = async (name: string) => {
    setSwitching(name);
    try {
      await markApi.switchModel(serverUrl, name);
      setActive(name);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSwitching('');
    }
  };

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch { return iso.slice(0, 10); }
  };

  const familyColor: Record<string, string> = {
    llama:   'text-orange-400 bg-orange-400/10 border-orange-400/30',
    gemma:   'text-blue-400 bg-blue-400/10 border-blue-400/30',
    qwen:    'text-purple-400 bg-purple-400/10 border-purple-400/30',
    mistral: 'text-rose-400 bg-rose-400/10 border-rose-400/30',
    phi:     'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
    deepseek:'text-teal-400 bg-teal-400/10 border-teal-400/30',
    codellama:'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  };

  const getFamilyClass = (family: string) => {
    const key = Object.keys(familyColor).find(k => family?.toLowerCase().includes(k));
    return key ? familyColor[key] : 'text-muted-foreground bg-muted/20 border-border/50';
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-card/40 shrink-0">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold">Models</span>
          {models.length > 0 && (
            <span className="text-xs text-muted-foreground">({models.length} available)</span>
          )}
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {/* Active model banner */}
      {active && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-accent/8 border-b border-accent/20 shrink-0">
          <CheckCircle2 className="w-3.5 h-3.5 text-accent shrink-0" />
          <div>
            <span className="text-xs font-medium text-accent">Active: </span>
            <span className="text-xs font-mono text-foreground">{active}</span>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 px-4 py-3 bg-red-500/8 border-b border-red-500/20 shrink-0">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-red-400">Ollama unreachable</p>
            <p className="text-[11px] text-red-400/70 mt-0.5">{error}</p>
            <a
              href="https://ollama.com/download"
              target="_blank"
              rel="noreferrer"
              className="text-[11px] text-red-400 flex items-center gap-1 mt-1 hover:underline"
            >
              <ExternalLink className="w-3 h-3" /> Get Ollama
            </a>
          </div>
        </div>
      )}

      {/* Model list */}
      <ScrollArea className="flex-1">
        {models.length === 0 && !loading && !error && (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-center px-8">
            <Server className="w-10 h-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">No models installed</p>
            <p className="text-xs text-muted-foreground/60">
              Run <code className="text-accent">ollama pull llama3</code> to download a model.
            </p>
          </div>
        )}

        <div className="p-3 space-y-2">
          {models.map(m => {
            const isActive = m.name === active;
            const isSwitching = switching === m.name;
            return (
              <motion.div
                key={m.name}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn(
                  'rounded-xl border p-4 transition-all cursor-pointer group',
                  isActive
                    ? 'border-accent/60 bg-accent/8 shadow-sm shadow-accent/10'
                    : 'border-border/50 bg-card/40 hover:border-accent/30 hover:bg-card/60',
                )}
                onClick={() => !isActive && switchTo(m.name)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2 min-w-0">
                    <div className="mt-0.5">
                      {isActive
                        ? <CheckCircle2 className="w-4 h-4 text-accent" />
                        : <Circle className="w-4 h-4 text-muted-foreground group-hover:text-accent/60 transition-colors" />
                      }
                    </div>
                    <div className="min-w-0">
                      <p className={cn('text-sm font-mono font-medium truncate', isActive ? 'text-accent' : 'text-foreground')}>
                        {m.name}
                      </p>
                      <div className="flex flex-wrap gap-1.5 mt-1.5">
                        {m.family && (
                          <Badge variant="outline" className={cn('text-[10px] h-4 px-1.5', getFamilyClass(m.family))}>
                            {m.family}
                          </Badge>
                        )}
                        {m.params && (
                          <Badge variant="outline" className="text-[10px] h-4 px-1.5 text-muted-foreground border-border/50">
                            <Zap className="w-2.5 h-2.5 mr-0.5" />{m.params}
                          </Badge>
                        )}
                        {m.size_gb > 0 && (
                          <Badge variant="outline" className="text-[10px] h-4 px-1.5 text-muted-foreground border-border/50">
                            <HardDrive className="w-2.5 h-2.5 mr-0.5" />{m.size_gb} GB
                          </Badge>
                        )}
                      </div>
                      {m.modified && (
                        <p className="text-[10px] text-muted-foreground/50 mt-1">
                          Updated {formatDate(m.modified)}
                        </p>
                      )}
                    </div>
                  </div>

                  {!isActive && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-xs shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={e => { e.stopPropagation(); switchTo(m.name); }}
                      disabled={isSwitching}
                    >
                      {isSwitching ? (
                        <RefreshCw className="w-3 h-3 animate-spin mr-1" />
                      ) : 'Use'}
                    </Button>
                  )}
                  {isActive && (
                    <Badge className="text-[10px] bg-accent/20 text-accent border-0 shrink-0">Active</Badge>
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>
      </ScrollArea>

      {/* ── Model Router section (Feature 15) ─────────────────────────────── */}
      <div className="border-t border-border/50 shrink-0">
        <button
          onClick={async () => {
            if (!routeTab) {
              try {
                const r = await markApi.getModelRouter(serverUrl);
                setRoutes(r.routes);
                setEditRoute({ ...r.routes });
              } catch { /* offline */ }
            }
            setRouteTab(v => !v);
          }}
          className="w-full flex items-center justify-between px-4 py-2 hover:bg-muted/20 transition-colors"
        >
          <span className="text-xs font-medium text-muted-foreground">Model Router</span>
          <span className="text-[10px] text-muted-foreground">{routeTab ? '▲ hide' : '▼ show'}</span>
        </button>

        {routeTab && (
          <div className="px-4 pb-3 space-y-2 max-h-64 overflow-y-auto">
            <p className="text-[10px] text-muted-foreground/60 mb-1">
              Assign a specific model to each worker role. Overrides the global active model.
            </p>
            {Object.entries(editRoute).map(([worker, model]) => (
              <div key={worker} className="flex items-center gap-2">
                <span className="text-[10px] font-mono w-28 shrink-0 text-muted-foreground">{worker}</span>
                <input
                  value={model}
                  onChange={e => setEditRoute(r => ({ ...r, [worker]: e.target.value }))}
                  className="flex-1 bg-muted/20 border border-border/50 rounded px-2 py-0.5 text-[11px] font-mono focus:outline-none focus:border-accent/50"
                />
              </div>
            ))}
            <div className="flex gap-2 pt-1">
              <button
                onClick={async () => {
                  try {
                    const r = await markApi.updateModelRouter(serverUrl, editRoute);
                    setRoutes(r.routes);
                  } catch { /* offline */ }
                }}
                className="text-[10px] px-2.5 py-1 bg-accent/20 text-accent rounded hover:bg-accent/30"
              >
                Apply
              </button>
              <button
                onClick={async () => {
                  try {
                    const r = await markApi.resetModelRouter(serverUrl);
                    setRoutes(r.routes); setEditRoute({ ...r.routes });
                  } catch { /* offline */ }
                }}
                className="text-[10px] px-2.5 py-1 bg-muted/40 rounded hover:bg-muted/60"
              >
                Reset defaults
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="px-4 py-2 border-t border-border/50 bg-card/20 shrink-0">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          Powered by Ollama · <code className="font-mono">ollama pull &lt;model&gt;</code> to add more
        </p>
      </div>
    </div>
  );
}
