import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { markApi, type LlmSettings } from '@/lib/markApi';
import { useMarkStore } from '@/store/markStore';
import {
  Loader2, CheckCircle2, XCircle, Cloud, Server, Sliders,
  Zap, Activity, ChevronDown, ChevronUp,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4 bg-card p-6 rounded-xl border border-border/50 shadow-sm">
      <div>
        <h3 className="text-base font-semibold mb-0.5">{title}</h3>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}

// ── Provider pill ────────────────────────────────────────────────────────────

function ProviderButton({
  id, label, icon: Icon, active, available, onClick,
}: {
  id: string; label: string; icon: React.ElementType;
  active: boolean; available: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!available}
      className={cn(
        'flex items-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all',
        active
          ? 'bg-accent text-accent-foreground border-accent shadow-sm'
          : available
            ? 'border-border/60 text-muted-foreground hover:border-accent/40 hover:text-foreground'
            : 'border-border/30 text-muted-foreground/40 cursor-not-allowed opacity-40',
      )}
    >
      <Icon className="w-4 h-4" />
      {label}
      {active && <CheckCircle2 className="w-3.5 h-3.5 ml-auto" />}
    </button>
  );
}

// ── Slider field ─────────────────────────────────────────────────────────────

function SliderField({
  label, value, min, max, step, onChange, hint,
}: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; hint?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between">
        <Label className="text-sm">{label}</Label>
        <span className="text-sm font-mono text-accent">{value}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full accent-accent cursor-pointer"
      />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SettingsView() {
  const { serverUrl, setServerUrl } = useMarkStore();

  // ── Server connection ──────────────────────────────────────────────────────
  const [testUrl,     setTestUrl]     = useState(serverUrl);
  const [testing,     setTesting]     = useState(false);
  const [testResult,  setTestResult]  = useState<'success' | 'error' | null>(null);
  const [testMessage, setTestMessage] = useState('');

  // ── LLM settings ──────────────────────────────────────────────────────────
  const [llmSettings,  setLlmSettings]  = useState<LlmSettings | null>(null);
  const [llmLoading,   setLlmLoading]   = useState(false);
  const [llmSaving,    setLlmSaving]    = useState(false);
  const [llmSaved,     setLlmSaved]     = useState(false);
  const [llmError,     setLlmError]     = useState('');
  const [llmHealth,    setLlmHealth]    = useState<{ available: boolean; latency_ms: number | null; error: string | null } | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Local editable copies
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens,   setMaxTokens]   = useState(4096);
  const [streaming,   setStreaming]   = useState(true);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await markApi.getHealth(testUrl);
      setTestResult('success');
      setTestMessage(`Connected to MARK API v${res.version || 'unknown'}`);
      setServerUrl(testUrl);
    } catch (err: any) {
      setTestResult('error');
      setTestMessage(err.message || 'Failed to connect');
    } finally {
      setTesting(false);
    }
  };

  const loadLlmSettings = async () => {
    setLlmLoading(true);
    setLlmError('');
    try {
      const s = await markApi.getLlmSettings(serverUrl);
      setLlmSettings(s);
      setTemperature(s.temperature);
      setMaxTokens(s.max_tokens);
      setStreaming(s.streaming);
    } catch (err: any) {
      setLlmError(err.message || 'Failed to load LLM settings');
    } finally {
      setLlmLoading(false);
    }
  };

  const checkHealth = async () => {
    setHealthLoading(true);
    try {
      const h = await markApi.getLlmHealth(serverUrl);
      setLlmHealth({ available: h.available, latency_ms: h.latency_ms, error: h.error });
    } catch {
      setLlmHealth({ available: false, latency_ms: null, error: 'Server unreachable' });
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    loadLlmSettings();
  }, [serverUrl]);

  const switchProvider = async (provider: string) => {
    try {
      const result = await markApi.switchProvider(serverUrl, provider);
      if (result.success !== false) {
        setLlmSettings(prev => prev ? { ...prev, ...result } : result);
      }
    } catch (err: any) {
      setLlmError(err.message);
    }
  };

  const saveLlmSettings = async () => {
    setLlmSaving(true);
    setLlmSaved(false);
    try {
      const updated = await markApi.updateLlmSettings(serverUrl, {
        temperature,
        max_tokens: maxTokens,
        streaming,
      });
      setLlmSettings(updated);
      setLlmSaved(true);
      setTimeout(() => setLlmSaved(false), 2000);
    } catch (err: any) {
      setLlmError(err.message);
    } finally {
      setLlmSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-8 bg-background">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight mb-1">Settings</h2>
          <p className="text-sm text-muted-foreground">Configure MARK server connection and AI provider.</p>
        </div>

        {/* ── MARK Server Configuration ─────────────────────────────────────── */}
        <Section
          title="MARK Server"
          description="WebSocket and REST API endpoint for the local MARK daemon."
        >
          <div className="grid gap-2">
            <Label htmlFor="serverUrl">API Base URL</Label>
            <div className="flex gap-2">
              <Input
                id="serverUrl"
                value={testUrl}
                onChange={e => setTestUrl(e.target.value)}
                className="font-mono text-sm"
              />
              <Button onClick={handleTest} disabled={testing} className="min-w-[110px]">
                {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Test & Save'}
              </Button>
            </div>

            {testResult && (
              <div className={cn(
                'text-sm mt-1 flex items-center gap-2 p-3 rounded-md border',
                testResult === 'success'
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
                  : 'bg-destructive/10 border-destructive/30 text-destructive',
              )}>
                {testResult === 'success'
                  ? <CheckCircle2 className="w-4 h-4 shrink-0" />
                  : <XCircle className="w-4 h-4 shrink-0" />
                }
                {testMessage}
              </div>
            )}
          </div>
        </Section>

        {/* ── LLM Provider ────────────────────────────────────────────────────── */}
        <Section
          title="AI Provider"
          description="Choose between GitHub Models (cloud) and Ollama (local). The selected provider is used for all chat, agents, and planning."
        >
          {llmLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : llmError ? (
            <p className="text-sm text-destructive">{llmError}</p>
          ) : llmSettings ? (
            <div className="space-y-5">
              {/* Provider selector */}
              <div className="flex gap-3">
                <ProviderButton
                  id="github"
                  label="GitHub Models"
                  icon={Cloud}
                  active={llmSettings.provider === 'github'}
                  available={llmSettings.github_available}
                  onClick={() => switchProvider('github')}
                />
                <ProviderButton
                  id="ollama"
                  label="Ollama"
                  icon={Server}
                  active={llmSettings.provider === 'ollama'}
                  available={true}
                  onClick={() => switchProvider('ollama')}
                />
              </div>

              {!llmSettings.github_available && (
                <p className="text-xs text-amber-500/80 flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5" />
                  GitHub Models requires a GITHUB_TOKEN env var with Models access.
                </p>
              )}

              {/* Active model */}
              <div className="flex items-center gap-2 p-3 bg-accent/8 rounded-lg border border-accent/20">
                <Activity className="w-4 h-4 text-accent shrink-0" />
                <div>
                  <p className="text-xs text-muted-foreground">Active model</p>
                  <p className="text-sm font-mono font-medium">{llmSettings.model}</p>
                </div>
              </div>

              {/* Health check */}
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={checkHealth}
                  disabled={healthLoading}
                  className="h-7 text-xs"
                >
                  {healthLoading
                    ? <Loader2 className="w-3 h-3 animate-spin mr-1" />
                    : <Activity className="w-3 h-3 mr-1" />
                  }
                  Check Health
                </Button>
                {llmHealth && (
                  <span className={cn(
                    'text-xs flex items-center gap-1',
                    llmHealth.available ? 'text-emerald-500' : 'text-red-400',
                  )}>
                    {llmHealth.available
                      ? <CheckCircle2 className="w-3.5 h-3.5" />
                      : <XCircle className="w-3.5 h-3.5" />
                    }
                    {llmHealth.available
                      ? `Online · ${llmHealth.latency_ms ?? '?'}ms`
                      : `Offline · ${llmHealth.error ?? 'unreachable'}`
                    }
                  </span>
                )}
              </div>

              {/* Advanced settings collapsible */}
              <div className="border border-border/50 rounded-lg overflow-hidden">
                <button
                  onClick={() => setAdvancedOpen(v => !v)}
                  className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-muted/20 transition-colors"
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <Sliders className="w-4 h-4 text-muted-foreground" />
                    Generation Settings
                  </span>
                  {advancedOpen
                    ? <ChevronUp className="w-4 h-4 text-muted-foreground" />
                    : <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  }
                </button>

                {advancedOpen && (
                  <div className="px-4 pb-4 pt-2 space-y-5 border-t border-border/50">
                    <SliderField
                      label="Temperature"
                      value={temperature}
                      min={0} max={2} step={0.05}
                      onChange={setTemperature}
                      hint="Higher = more creative. Lower = more deterministic. Recommended: 0.7"
                    />
                    <SliderField
                      label="Max Tokens"
                      value={maxTokens}
                      min={256} max={16384} step={256}
                      onChange={setMaxTokens}
                      hint="Maximum tokens per response. GitHub Models supports up to 16k+."
                    />

                    <div className="flex items-center justify-between">
                      <div>
                        <Label className="text-sm">Streaming</Label>
                        <p className="text-xs text-muted-foreground mt-0.5">Stream tokens as they arrive</p>
                      </div>
                      <button
                        onClick={() => setStreaming(v => !v)}
                        className={cn(
                          'relative w-10 h-5.5 rounded-full transition-colors',
                          streaming ? 'bg-accent' : 'bg-muted',
                        )}
                        style={{ height: '22px', width: '40px' }}
                      >
                        <span className={cn(
                          'absolute top-0.5 w-4.5 h-4 rounded-full bg-white shadow transition-transform',
                          streaming ? 'translate-x-5' : 'translate-x-0.5',
                        )} style={{ width: '18px', height: '18px', top: '2px', left: streaming ? '20px' : '2px', transition: 'left 0.2s' }} />
                      </button>
                    </div>

                    <div className="flex items-center gap-2 pt-1">
                      <Button onClick={saveLlmSettings} disabled={llmSaving} size="sm">
                        {llmSaving
                          ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
                          : llmSaved
                            ? <CheckCircle2 className="w-3.5 h-3.5 mr-1 text-emerald-400" />
                            : null
                        }
                        {llmSaved ? 'Saved!' : 'Save Settings'}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </Section>
      </div>
    </div>
  );
}
