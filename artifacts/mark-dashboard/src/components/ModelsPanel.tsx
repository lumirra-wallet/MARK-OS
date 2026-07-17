/**
 * ModelsPanel — Provider-agnostic model selector.
 *
 * Top section: Provider switcher, one pill per entry the backend reports
 * (NVIDIA, GitHub Models, OpenAI, Anthropic — all cloud-hosted).
 * Middle section: Model list for the active provider, with ✓ Active badge.
 * Bottom section: Collapsible Model Router (per-worker overrides, Feature 15).
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Cpu, RefreshCw, CheckCircle2, Circle, Zap, HardDrive,
  AlertTriangle, ExternalLink, Cloud, ChevronDown,
  ChevronUp, Wifi, WifiOff, Activity,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi, type LlmSettings, type ModelInfo, type ProviderInfo } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// ── Family colour mapping ────────────────────────────────────────────────────

const familyColor: Record<string, string> = {
  llama:    'text-orange-400 bg-orange-400/10 border-orange-400/30',
  gemma:    'text-blue-400  bg-blue-400/10  border-blue-400/30',
  qwen:     'text-purple-400 bg-purple-400/10 border-purple-400/30',
  mistral:  'text-rose-400  bg-rose-400/10  border-rose-400/30',
  phi:      'text-cyan-400  bg-cyan-400/10  border-cyan-400/30',
  deepseek: 'text-teal-400  bg-teal-400/10  border-teal-400/30',
  codestral:'text-indigo-400 bg-indigo-400/10 border-indigo-400/30',
  gpt:      'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  o1:       'text-violet-400 bg-violet-400/10 border-violet-400/30',
  o3:       'text-violet-400 bg-violet-400/10 border-violet-400/30',
  codellama:'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  embedding:'text-gray-400  bg-gray-400/10  border-gray-400/30',
};

const getFamilyClass = (family: string) => {
  const key = Object.keys(familyColor).find(k => family?.toLowerCase().includes(k));
  return key ? familyColor[key] : 'text-muted-foreground bg-muted/20 border-border/50';
};

const PROVIDER_TOKEN_URLS: Record<string, string> = {
  nvidia:    'https://build.nvidia.com',
  github:    'https://github.com/settings/tokens',
  openai:    'https://platform.openai.com/api-keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
};

const formatDate = (iso: string) => {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return iso.slice(0, 10); }
};

// ── Provider pill ────────────────────────────────────────────────────────────

function ProviderPill({
  label,
  icon: Icon,
  active,
  available,
  unavailableHint,
  onClick,
  disabled,
}: {
  label: string;
  icon: React.ElementType;
  active: boolean;
  available: boolean;
  unavailableHint: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || !available}
      title={!available ? unavailableHint : undefined}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border',
        active
          ? 'bg-accent text-accent-foreground border-accent shadow-sm'
          : available
            ? 'border-border/50 text-muted-foreground hover:border-accent/40 hover:text-foreground'
            : 'border-border/30 text-muted-foreground/40 cursor-not-allowed opacity-50',
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
      {active && <CheckCircle2 className="w-3 h-3 ml-0.5" />}
    </button>
  );
}

// ── Model card ───────────────────────────────────────────────────────────────

function ModelCard({
  model,
  isActive,
  isSwitching,
  onSelect,
}: {
  model: ModelInfo;
  isActive: boolean;
  isSwitching: boolean;
  onSelect: () => void;
}) {
  const displayName = model.name || model.id;
  return (
    <motion.div
      key={displayName}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-xl border p-3.5 transition-all cursor-pointer group',
        isActive
          ? 'border-accent/60 bg-accent/8 shadow-sm shadow-accent/10'
          : 'border-border/50 bg-card/40 hover:border-accent/30 hover:bg-card/60',
      )}
      onClick={() => !isActive && onSelect()}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          <div className="mt-0.5 shrink-0">
            {isActive
              ? <CheckCircle2 className="w-4 h-4 text-accent" />
              : <Circle className="w-4 h-4 text-muted-foreground group-hover:text-accent/60 transition-colors" />
            }
          </div>
          <div className="min-w-0">
            <p className={cn(
              'text-sm font-mono font-medium truncate',
              isActive ? 'text-accent' : 'text-foreground',
            )}>
              {displayName}
            </p>
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {model.family && (
                <Badge variant="outline" className={cn('text-[10px] h-4 px-1.5', getFamilyClass(model.family))}>
                  {model.family}
                </Badge>
              )}
              {model.params && (
                <Badge variant="outline" className="text-[10px] h-4 px-1.5 text-muted-foreground border-border/50">
                  <Zap className="w-2.5 h-2.5 mr-0.5" />{model.params}
                </Badge>
              )}
              {model.size_gb > 0 && (
                <Badge variant="outline" className="text-[10px] h-4 px-1.5 text-muted-foreground border-border/50">
                  <HardDrive className="w-2.5 h-2.5 mr-0.5" />{model.size_gb} GB
                </Badge>
              )}
              {model.context && model.context > 0 && (
                <Badge variant="outline" className="text-[10px] h-4 px-1.5 text-muted-foreground border-border/50">
                  {Math.round(model.context / 1000)}k ctx
                </Badge>
              )}
            </div>
            {model.modified && (
              <p className="text-[10px] text-muted-foreground/50 mt-1">
                Updated {formatDate(model.modified)}
              </p>
            )}
          </div>
        </div>

        {!isActive && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={e => { e.stopPropagation(); onSelect(); }}
            disabled={isSwitching}
          >
            {isSwitching ? <RefreshCw className="w-3 h-3 animate-spin mr-1" /> : 'Use'}
          </Button>
        )}
        {isActive && (
          <Badge className="text-[10px] bg-accent/20 text-accent border-0 shrink-0">
            ✓ Active
          </Badge>
        )}
      </div>
    </motion.div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function ModelsPanel() {
  const { serverUrl } = useMarkStore();
  const [models,    setModels]    = useState<ModelInfo[]>([]);
  const [active,    setActive]    = useState('');
  const [provider,  setProvider]  = useState('nvidia');
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');
  const [switching, setSwitching] = useState('');
  const [health,    setHealth]    = useState<{ available: boolean; latency_ms: number | null } | null>(null);

  // Model Router (Feature 15)
  const [routes,    setRoutes]    = useState<Record<string, string>>({});
  const [routeTab,  setRouteTab]  = useState(false);
  const [editRoute, setEditRoute] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [modelsData, providersData] = await Promise.all([
        markApi.getModels(serverUrl) as Promise<any>,
        markApi.getProviders(serverUrl).catch(() => ({ providers: [] })),
      ]);
      setModels(modelsData.models ?? []);
      setActive(modelsData.active ?? '');
      setProvider(modelsData.provider ?? 'nvidia');
      setProviders(providersData.providers ?? []);
      if (modelsData.error) setError(modelsData.error);
    } catch (err: any) {
      setError(err.message ?? 'Failed to load models');
    } finally {
      setLoading(false);
    }
    // LLM health check (non-blocking)
    markApi.getLlmHealth(serverUrl)
      .then(h => setHealth({ available: h.available, latency_ms: h.latency_ms }))
      .catch(() => {});
  }, [serverUrl]);

  useEffect(() => { refresh(); }, [refresh]);

  const switchTo = async (modelName: string) => {
    setSwitching(modelName);
    try {
      await markApi.switchModel(serverUrl, modelName);
      setActive(modelName);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSwitching('');
    }
  };

  const switchToProvider = async (newProvider: string) => {
    if (newProvider === provider) return;
    setSwitching('__provider__');
    try {
      await markApi.switchProvider(serverUrl, newProvider);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSwitching('');
    }
  };

  const activeProviderInfo = providers.find(p => p.id === provider);
  const activeAvailable    = activeProviderInfo?.available ?? true; // optimistic until loaded
  const isSwitchingProvider = switching === '__provider__';

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-card/40 shrink-0">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold">Models</span>
          {models.length > 0 && (
            <span className="text-xs text-muted-foreground">({models.length})</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {health && (
            <span className={cn(
              'flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded',
              health.available
                ? 'text-emerald-400 bg-emerald-400/10'
                : 'text-red-400 bg-red-400/10',
            )}>
              {health.available ? <Wifi className="w-2.5 h-2.5" /> : <WifiOff className="w-2.5 h-2.5" />}
              {health.available && health.latency_ms != null ? `${health.latency_ms}ms` : health.available ? 'online' : 'offline'}
            </span>
          )}
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {/* Provider selector */}
      <div className="px-4 py-3 border-b border-border/50 bg-card/20 shrink-0">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">Provider</p>
        <div className="flex gap-2 flex-wrap">
          {providers.map(p => (
            <ProviderPill
              key={p.id}
              label={p.name}
              icon={Cloud}
              active={provider === p.id}
              available={p.available || providers.length === 0}
              unavailableHint={p.token_env ? `${p.token_env} not set` : 'unavailable'}
              onClick={() => switchToProvider(p.id)}
              disabled={isSwitchingProvider}
            />
          ))}
          {isSwitchingProvider && (
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <RefreshCw className="w-3 h-3 animate-spin" /> switching…
            </span>
          )}
        </div>

        {/* Missing token/key hint */}
        {!activeAvailable && providers.length > 0 && (
          <p className="text-[10px] text-amber-400/80 mt-2 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            {activeProviderInfo?.token_env
              ? `${activeProviderInfo.token_env} env var not set — ${activeProviderInfo.name} unavailable`
              : `${activeProviderInfo?.name ?? provider} unavailable`}
          </p>
        )}
      </div>

      {/* Active model banner */}
      {active && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-accent/8 border-b border-accent/20 shrink-0">
          <Activity className="w-3.5 h-3.5 text-accent shrink-0" />
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
            <p className="text-xs font-medium text-red-400">
              {activeProviderInfo?.name ?? provider} error
            </p>
            <p className="text-[11px] text-red-400/70 mt-0.5">{error}</p>
            {!activeAvailable && PROVIDER_TOKEN_URLS[provider] && (
              <a
                href={PROVIDER_TOKEN_URLS[provider]}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] text-red-400 flex items-center gap-1 mt-1 hover:underline"
              >
                <ExternalLink className="w-3 h-3" /> Get a {activeProviderInfo?.name ?? provider} key
              </a>
            )}
          </div>
        </div>
      )}

      {/* Model list */}
      <ScrollArea className="flex-1">
        {models.length === 0 && !loading && !error && (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-center px-8">
            <Cloud className="w-10 h-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">No models returned</p>
            <p className="text-xs text-muted-foreground/60">
              {activeProviderInfo?.token_env
                ? `Ensure ${activeProviderInfo.token_env} is set with the right access.`
                : 'Check the provider configuration.'}
            </p>
          </div>
        )}

        <div className="p-3 space-y-2">
          {models.map(m => (
            <ModelCard
              key={m.name || m.id}
              model={m}
              isActive={(m.name || m.id) === active}
              isSwitching={switching === (m.name || m.id)}
              onSelect={() => switchTo(m.name || m.id)}
            />
          ))}
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
          <span className="text-xs font-medium text-muted-foreground">Per-Worker Model Router</span>
          {routeTab ? <ChevronUp className="w-3 h-3 text-muted-foreground" /> : <ChevronDown className="w-3 h-3 text-muted-foreground" />}
        </button>

        <AnimatePresence>
          {routeTab && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-3 space-y-2 max-h-64 overflow-y-auto">
                <p className="text-[10px] text-muted-foreground/60 mb-1">
                  Assign a specific model to each worker role (overrides the global active model).
                </p>
                {Object.entries(editRoute).map(([worker, model]) => (
                  <div key={worker} className="flex items-center gap-2">
                    <span className="text-[10px] font-mono w-28 shrink-0 text-muted-foreground truncate">{worker}</span>
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
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border/50 bg-card/20 shrink-0">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          {activeProviderInfo?.name ?? provider} · cloud inference · no local GPU needed
        </p>
      </div>
    </div>
  );
}
