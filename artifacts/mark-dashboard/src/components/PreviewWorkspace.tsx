/**
 * PreviewWorkspace — Live Preview panel for the MARK dashboard.
 *
 * Layout
 * ──────
 * ┌─────────────────────────────────────────────────────────────────────┐
 * │  Device toolbar  ·  Theme toggle  ·  open-in-new-tab               │
 * ├──────────────────────────────────────────────────────────────────────┤
 * │  Preview Manager strip (tabs per registered preview)                │
 * ├──────────────────────────────────────────────────────────────────────┤
 * │  Browser chrome: ← → ↻  URL bar  ↗                                │
 * ├──────────────────────────────────────────────────────────────────────┤
 * │                                                                      │
 * │   iframe viewport  (device-framed + scaled)                         │
 * │                                                                      │
 * └──────────────────────────────────────────────────────────────────────┘
 */
import React, { useRef, useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Monitor, Tablet, Smartphone, RotateCcw,
  Sun, Moon, RefreshCw, ArrowLeft, ArrowRight,
  ExternalLink, Globe, X, Plus, Wifi, WifiOff, AlertCircle,
  Play,
} from 'lucide-react';
import { useMarkStore, DeviceMode, ThemeMode, PreviewInfo } from '@/store/markStore';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// ── Device configurations ─────────────────────────────────────────────────────

interface DeviceConfig {
  label:    string;
  icon:     React.ComponentType<any>;
  width:    number | null; // null = full width
  height:   number | null;
  rotate?:  boolean;
}

const DEVICES: Record<DeviceMode, DeviceConfig> = {
  desktop:   { label: 'Desktop',   icon: Monitor,    width: null,  height: null },
  tablet:    { label: 'Tablet',    icon: Tablet,     width: 768,   height: 1024 },
  mobile:    { label: 'Mobile',    icon: Smartphone, width: 390,   height: 844  },
  landscape: { label: 'Landscape', icon: RotateCcw,  width: 844,   height: 390, rotate: true  },
};

// ── Framework badge colours ───────────────────────────────────────────────────

const FRAMEWORK_COLORS: Record<string, string> = {
  react:    'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  vite:     'bg-purple-500/20 text-purple-400 border-purple-500/30',
  // Backend classify() emits "nextjs" (see api_previews.py FrameworkHeuristics) —
  // "next" kept as an alias so a manually-registered/legacy label still styles correctly.
  nextjs:   'bg-white/10 text-white/70 border-white/20',
  next:     'bg-white/10 text-white/70 border-white/20',
  vue:      'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  svelte:   'bg-orange-500/20 text-orange-400 border-orange-500/30',
  angular:  'bg-red-500/20 text-red-400 border-red-500/30',
  express:  'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  flask:    'bg-gray-500/20 text-gray-400 border-gray-500/30',
  fastapi:  'bg-teal-500/20 text-teal-400 border-teal-500/30',
  django:      'bg-lime-500/20 text-lime-400 border-lime-500/30',
  storybook:   'bg-pink-500/20 text-pink-400 border-pink-500/30',
  streamlit:   'bg-red-400/20 text-red-300 border-red-400/30',
  flutter:     'bg-sky-500/20 text-sky-400 border-sky-500/30',
  electron:    'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  'react-native-web': 'bg-cyan-400/20 text-cyan-300 border-cyan-400/30',
  unknown:  'bg-muted/40 text-muted-foreground border-border/40',
};

function frameworkColor(fw: string): string {
  const key = fw.toLowerCase();
  return FRAMEWORK_COLORS[key] ?? FRAMEWORK_COLORS.unknown;
}

// ── Status indicator ──────────────────────────────────────────────────────────

function StatusDot({ status }: { status: PreviewInfo['status'] }) {
  const cfg: Record<string, { cls: string; pulse: boolean }> = {
    active:      { cls: 'bg-success glow-sm',    pulse: false },
    unreachable: { cls: 'bg-warning',            pulse: true  },
    closed:      { cls: 'bg-muted-foreground',   pulse: false },
  };
  const { cls, pulse } = cfg[status] ?? cfg.closed;
  return (
    <motion.span
      className={cn('inline-block w-2 h-2 rounded-full shrink-0', cls)}
      animate={pulse ? { opacity: [1, 0.3, 1] } : {}}
      transition={{ duration: 1.2, repeat: Infinity }}
    />
  );
}

// ── Preview tab ───────────────────────────────────────────────────────────────

function PreviewTab({
  preview, active, onClick, onClose,
}: {
  preview:  PreviewInfo;
  active:   boolean;
  onClick:  () => void;
  onClose:  () => void;
}) {
  return (
    <motion.button
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      onClick={onClick}
      className={cn(
        'group flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all shrink-0',
        active
          ? 'bg-accent/15 border-accent/40 text-accent'
          : 'bg-muted/30 border-border/40 text-muted-foreground hover:text-foreground hover:border-border/60',
      )}
    >
      <StatusDot status={preview.status} />
      <span className="max-w-[120px] truncate">{preview.title}</span>
      <Badge
        variant="outline"
        className={cn('text-[9px] px-1 py-0 border font-normal', frameworkColor(preview.framework))}
      >
        {preview.framework}
      </Badge>
      <button
        onClick={e => { e.stopPropagation(); onClose(); }}
        className="opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity ml-0.5 shrink-0"
      >
        <X className="w-3 h-3" />
      </button>
    </motion.button>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyPreview() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground select-none">
      <motion.div
        animate={{ opacity: [0.4, 0.7, 0.4] }}
        transition={{ duration: 3, repeat: Infinity }}
        className="w-16 h-16 rounded-2xl bg-muted/30 border border-border/30 flex items-center justify-center"
      >
        <Globe className="w-8 h-8 text-muted-foreground/50" />
      </motion.div>
      <div className="text-center space-y-1">
        <p className="text-sm font-medium text-foreground/60">No live previews yet</p>
        <p className="text-xs text-muted-foreground/60 max-w-[260px]">
          When Elena starts an app, it will appear here automatically.
          You can also enter a URL manually below.
        </p>
      </div>
    </div>
  );
}

// ── Manual URL adder ──────────────────────────────────────────────────────────

function AddPreviewBar({ onAdd }: { onAdd: (url: string) => void }) {
  const [url, setUrl] = useState('');
  const submit = () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    const full = trimmed.startsWith('http') ? trimmed : `https://${trimmed}`;
    onAdd(full);
    setUrl('');
  };
  return (
    <form
      onSubmit={e => { e.preventDefault(); submit(); }}
      className="flex items-center gap-2 px-3 py-2 border-t border-border/40 bg-card/30"
    >
      <Globe className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      <input
        type="url"
        value={url}
        onChange={e => setUrl(e.target.value)}
        placeholder="Enter URL to preview… (e.g. http://localhost:3000)"
        className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground/50 outline-none min-w-0"
      />
      <button
        type="submit"
        disabled={!url.trim()}
        className="flex items-center gap-1 text-[11px] text-accent hover:text-accent/80 disabled:opacity-30 transition-colors shrink-0"
      >
        <Plus className="w-3 h-3" />
        Add
      </button>
    </form>
  );
}

// ── Device frame wrapper ──────────────────────────────────────────────────────

function DeviceFrame({
  mode, children,
}: {
  mode: DeviceMode;
  children: React.ReactNode;
}) {
  const cfg = DEVICES[mode];
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  // Compute scale so the device frame fits the container
  useEffect(() => {
    if (!cfg.width || !cfg.height) { setScale(1); return; }
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      const sw = width  / cfg.width!;
      const sh = height / cfg.height!;
      setScale(Math.min(sw, sh, 1));
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [cfg.width, cfg.height]);

  if (!cfg.width || !cfg.height) {
    // Desktop: fill container
    return <div className="flex-1 overflow-hidden">{children}</div>;
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-hidden flex items-center justify-center bg-muted/10 p-4"
    >
      <motion.div
        key={mode}
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.18 }}
        style={{
          width:     cfg.width,
          height:    cfg.height,
          transform: `scale(${scale})`,
          transformOrigin: 'center center',
        }}
        className="rounded-2xl border-2 border-border/60 overflow-hidden shadow-2xl shadow-black/30 bg-background shrink-0"
      >
        {children}
      </motion.div>
    </div>
  );
}

// ── Browser chrome ────────────────────────────────────────────────────────────

function BrowserChrome({
  url, onReload, onBack, onForward, onOpenExternal, loading,
}: {
  url:            string;
  onReload:       () => void;
  onBack:         () => void;
  onForward:      () => void;
  onOpenExternal: () => void;
  loading:        boolean;
}) {
  const [editUrl, setEditUrl]       = useState(url);
  const [editing, setEditing]       = useState(false);

  // Keep in sync when parent url changes
  useEffect(() => { if (!editing) setEditUrl(url); }, [url, editing]);

  const IconBtn = ({
    icon: Icon, onClick, tooltip, disabled = false,
  }: { icon: React.ComponentType<any>; onClick: () => void; tooltip: string; disabled?: boolean }) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          disabled={disabled}
          className="w-7 h-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-30 shrink-0"
        >
          <Icon className="w-3.5 h-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">{tooltip}</TooltipContent>
    </Tooltip>
  );

  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border/40 bg-card/50 shrink-0">
      <IconBtn icon={ArrowLeft}  onClick={onBack}    tooltip="Back" />
      <IconBtn icon={ArrowRight} onClick={onForward} tooltip="Forward" />
      <IconBtn
        icon={loading ? RefreshCw : RefreshCw}
        onClick={onReload}
        tooltip="Reload"
      />

      {/* URL bar */}
      <div className="flex-1 flex items-center gap-1.5 bg-muted/40 border border-border/40 rounded-md px-2 py-1 min-w-0">
        {loading
          ? <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
              <RefreshCw className="w-3 h-3 text-accent shrink-0" />
            </motion.div>
          : <Globe className="w-3 h-3 text-muted-foreground shrink-0" />
        }
        <input
          className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground/50 outline-none font-mono min-w-0"
          value={editUrl}
          onFocus={() => setEditing(true)}
          onBlur={() => { setEditing(false); setEditUrl(url); }}
          onChange={e => setEditUrl(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              setEditing(false);
              // parent handles navigation via activeUrl state
              (e.target as HTMLInputElement).blur();
            }
          }}
        />
      </div>

      <IconBtn icon={ExternalLink} onClick={onOpenExternal} tooltip="Open in new tab" />
    </div>
  );
}

// ── Main PreviewWorkspace ─────────────────────────────────────────────────────

export function PreviewWorkspace() {
  const {
    previews, activePreviewId,
    deviceMode, themeMode,
    setActivePreviewId, setDeviceMode, setThemeMode, removePreview,
  } = useMarkStore();

  const iframeRef  = useRef<HTMLIFrameElement>(null);
  const [loading, setLoading] = useState(false);
  const [iframeError, setIframeError] = useState(false);

  // Active preview
  const activePreview = previews.find(p => p.id === activePreviewId) ?? null;

  // Manual-preview state (for the Add bar)
  const [manualPreviews, setManualPreviews] = useState<PreviewInfo[]>([]);
  const allPreviews = [...previews, ...manualPreviews];
  const current = allPreviews.find(p => p.id === activePreviewId) ?? null;

  // Append theme param to URL for light mode (best-effort hint)
  const effectiveUrl = useCallback((base: string) => {
    if (!base) return base;
    try {
      const u = new URL(base);
      if (themeMode === 'light') {
        u.searchParams.set('theme', 'light');
      } else {
        u.searchParams.delete('theme');
      }
      return u.toString();
    } catch {
      return base;
    }
  }, [themeMode]);

  const currentUrl = current ? effectiveUrl(current.url) : '';

  const reload = useCallback(() => {
    if (!iframeRef.current) return;
    setLoading(true);
    setIframeError(false);
    iframeRef.current.src = currentUrl;
  }, [currentUrl]);

  const goBack = useCallback(() => {
    try { iframeRef.current?.contentWindow?.history.back(); } catch { /* cross-origin */ }
  }, []);

  const goForward = useCallback(() => {
    try { iframeRef.current?.contentWindow?.history.forward(); } catch { /* cross-origin */ }
  }, []);

  const openExternal = useCallback(() => {
    if (currentUrl) window.open(currentUrl, '_blank', 'noreferrer');
  }, [currentUrl]);

  // When device theme changes, try to inject color-scheme into same-origin iframes
  useEffect(() => {
    if (!iframeRef.current) return;
    try {
      const doc = iframeRef.current.contentDocument;
      if (doc?.documentElement) {
        doc.documentElement.style.colorScheme = themeMode;
        doc.documentElement.classList.toggle('dark', themeMode === 'dark');
        doc.documentElement.classList.toggle('light', themeMode === 'light');
      }
    } catch { /* cross-origin — no-op */ }
  }, [themeMode, currentUrl]);

  // Add a manual URL preview
  const addManual = useCallback((url: string) => {
    const id = `manual-${Math.random().toString(36).slice(2)}`;
    const p: PreviewInfo = {
      id, url, title: url, framework: 'unknown',
      status: 'active', registeredAt: new Date().toISOString(),
    };
    setManualPreviews(prev => [...prev, p]);
    setActivePreviewId(id);
  }, [setActivePreviewId]);

  const closePreview = useCallback((id: string) => {
    // Remove from store previews
    removePreview(id);
    // Also remove from manual list
    setManualPreviews(prev => prev.filter(p => p.id !== id));
  }, [removePreview]);

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">

      {/* ── Toolbar row ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40 bg-card/30 shrink-0">
        <span className="text-xs font-semibold text-muted-foreground tracking-wide uppercase mr-1">
          Preview
        </span>

        <div className="h-3.5 w-px bg-border/40" />

        {/* Device mode buttons */}
        {(Object.entries(DEVICES) as [DeviceMode, DeviceConfig][]).map(([key, cfg]) => (
          <Tooltip key={key}>
            <TooltipTrigger asChild>
              <button
                onClick={() => setDeviceMode(key)}
                className={cn(
                  'flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-all',
                  deviceMode === key
                    ? 'bg-accent/15 border-accent/40 text-accent'
                    : 'text-muted-foreground border-transparent hover:border-border/40 hover:text-foreground',
                )}
              >
                <cfg.icon className="w-3.5 h-3.5" />
                <span className="hidden md:inline">{cfg.label}</span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">{cfg.label}</TooltipContent>
          </Tooltip>
        ))}

        <div className="h-3.5 w-px bg-border/40" />

        {/* Theme toggle */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => setThemeMode(themeMode === 'dark' ? 'light' : 'dark')}
              className={cn(
                'flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-all',
                'text-muted-foreground border-transparent hover:border-border/40 hover:text-foreground',
              )}
            >
              {themeMode === 'dark'
                ? <Moon className="w-3.5 h-3.5" />
                : <Sun  className="w-3.5 h-3.5" />
              }
              <span className="hidden md:inline capitalize">{themeMode}</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Toggle Dark / Light mode
          </TooltipContent>
        </Tooltip>

        {/* Connection status badge */}
        <div className="ml-auto flex items-center gap-1.5">
          {current?.status === 'active'      && <Wifi    className="w-3.5 h-3.5 text-success" />}
          {current?.status === 'unreachable' && <motion.div animate={{ opacity: [1, 0.4, 1] }} transition={{ duration: 1.2, repeat: Infinity }}><AlertCircle className="w-3.5 h-3.5 text-warning" /></motion.div>}
          {current?.status === 'closed'      && <WifiOff  className="w-3.5 h-3.5 text-muted-foreground" />}
          {current && (
            <span className="text-[10px] text-muted-foreground capitalize">{current.status}</span>
          )}
        </div>
      </div>

      {/* ── Preview manager strip (tabs) ─────────────────────────────────── */}
      {allPreviews.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border/40 bg-card/20 overflow-x-auto shrink-0">
          {allPreviews.map(p => (
            <PreviewTab
              key={p.id}
              preview={p}
              active={p.id === activePreviewId}
              onClick={() => setActivePreviewId(p.id)}
              onClose={() => closePreview(p.id)}
            />
          ))}
        </div>
      )}

      {/* ── Browser chrome ────────────────────────────────────────────────── */}
      {current && (
        <BrowserChrome
          url={current.url}
          loading={loading}
          onReload={reload}
          onBack={goBack}
          onForward={goForward}
          onOpenExternal={openExternal}
        />
      )}

      {/* ── Main viewport ─────────────────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        {current ? (
          <DeviceFrame key={deviceMode} mode={deviceMode}>
            {iframeError ? (
              <div className="w-full h-full flex flex-col items-center justify-center gap-3 text-muted-foreground bg-background">
                <AlertCircle className="w-8 h-8 text-destructive/60" />
                <p className="text-sm font-medium">Failed to load preview</p>
                <p className="text-xs opacity-60 max-w-[200px] text-center">{current.url}</p>
                <button
                  onClick={reload}
                  className="flex items-center gap-1.5 text-xs text-accent hover:text-accent/80 transition-colors border border-accent/30 rounded-md px-2.5 py-1"
                >
                  <RefreshCw className="w-3 h-3" />
                  Retry
                </button>
              </div>
            ) : (
              <iframe
                ref={iframeRef}
                key={currentUrl}
                src={currentUrl}
                title={current.title}
                className="w-full h-full border-0"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads"
                onLoad={() => {
                  setLoading(false);
                  setIframeError(false);
                  // Inject color-scheme on same-origin loads
                  try {
                    const doc = iframeRef.current?.contentDocument;
                    if (doc?.documentElement) {
                      doc.documentElement.style.colorScheme = themeMode;
                      doc.documentElement.classList.toggle('dark',  themeMode === 'dark');
                      doc.documentElement.classList.toggle('light', themeMode === 'light');
                    }
                  } catch { /* cross-origin */ }
                }}
                onError={() => { setLoading(false); setIframeError(true); }}
              />
            )}
          </DeviceFrame>
        ) : (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex-1 flex flex-col"
          >
            <EmptyPreview />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Manual URL entry ──────────────────────────────────────────────── */}
      <AddPreviewBar onAdd={addManual} />
    </div>
  );
}
