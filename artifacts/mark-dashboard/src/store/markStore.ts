import { create } from 'zustand';
import { markApi, PermissionInfo, VoiceMode, VoiceSettings, VoiceStateValue } from '@/lib/markApi';

// ── Chat message model ────────────────────────────────────────────────────────

export type ContentBlock =
  | { type: 'text';     text: string }
  | { type: 'streaming'; text: string }               // live token accumulation
  | { type: 'worker';   name: string; status: 'running' | 'success' | 'failed'; task?: string }
  | { type: 'file';     op: 'created' | 'modified' | 'deleted'; path: string }
  | { type: 'tests';    status: 'running' | 'passed' | 'failed'; output?: string }
  | { type: 'approval'; requestId: string; operation: string; path: string; diff?: string }
  | { type: 'error';    text: string }
  | { type: 'summary';  text: string; success: boolean; filesCreated: string[]; filesModified: string[]; elapsed: number };

export interface ChatMessage {
  id: string;
  role: 'user' | 'mark';
  timestamp: string;
  text?: string;           // user messages
  blocks: ContentBlock[];  // MARK messages
  isActive: boolean;
}

// ── Supporting types ──────────────────────────────────────────────────────────

export interface TimelineEvent {
  id: string;
  timestamp: string;
  type: string;
  message: string;
}

export interface WorkerState {
  name: string;
  status: 'idle' | 'running' | 'success' | 'failed' | 'skipped';
  task?: string;
  thought?: string;
  progress?: number;
  startedAt?: string;
  filesTouched?: string[];
}

export interface FileOperation {
  path: string;
  operation: 'created' | 'modified' | 'deleted';
}

export interface TestRunState {
  status: 'idle' | 'running' | 'passed' | 'failed';
  output?: string;
  timestamp?: string;
}

export interface OpenFile {
  path: string;
  content: string;
  isDiff: boolean;
  originalContent?: string;
}

export interface VoiceState {
  state: VoiceStateValue;
  running: boolean;
  mode: VoiceMode;
  muted: boolean;
  autoSubmit: boolean;
  whisperModel: string;
  ttsVoice: string;
  ttsSpeed: number;
  ttsVolume: number;
  wakePhraseEnabled: boolean;
  transcript: string;
  isBrowserTTSFallback: boolean;
  /** Which TTS engine to use for narration — kokoro is the default; browser is fallback-only. */
  ttsProvider: 'kokoro' | 'piper' | 'openai' | 'browser';
  /** OpenAI voice ID (alloy | echo | fable | onyx | nova | shimmer) — only used when ttsProvider is 'openai' */
  openaiVoice: string;
}

// ── Preview types ─────────────────────────────────────────────────────────────

export type PreviewStatus = 'starting' | 'ready' | 'error' | 'stopped';
export type DeviceMode    = 'desktop' | 'tablet' | 'mobile' | 'landscape';
export type ThemeMode     = 'dark' | 'light';

export interface PreviewInfo {
  id:        string;
  url:       string;
  title:     string;
  framework: string;
  status:    PreviewStatus;
  port?:     number;
  registeredAt: string;
}

// ── Live Engineer panel types ─────────────────────────────────────────────────

export interface ActivityEntry {
  id: string;
  timestamp: string;
  type: string;
  text: string;
  detail?: string;
  success?: boolean;
  elapsed?: number;
}

export type ReasoningStage =
  | 'idle' | 'analyzing' | 'planning' | 'writing'
  | 'running' | 'testing' | 'reviewing' | 'committing' | 'deploying' | 'done';

export interface NarrationEntry {
  id: string;
  timestamp: string;
  text: string;
  type: 'stage' | 'action' | 'summary' | 'suggestion';
}

export interface WorkspaceContext {
  projectType: string;
  frameworks: string[];
  gitBranch: string;
  lastCommit: string;
  testFramework: string | null;
  todoCount: number;
  fileCount: number;
  hasCI: boolean;
  summary: string;
  workspace: string;
}

export interface IdleSuggestion {
  id: string;
  timestamp: string;
  category: string;
  title: string;
  description: string;
  file?: string;
  priority: 'high' | 'medium' | 'low';
}

export interface EngineeringMemoryState {
  currentGoal: string | null;
  completedMilestones: { text: string; completed: boolean }[];
  blockers: { text: string; resolved: boolean }[];
  context: string;
  sessionElapsed: number;
}

// ── Store interface ───────────────────────────────────────────────────────────

interface MarkState {
  serverUrl: string;
  connectionStatus: 'connecting' | 'connected' | 'disconnected';
  running: boolean;
  goal: string;
  workspace: string;
  elapsed: number;
  cancelRequested: boolean;

  workers: WorkerState[];
  currentWorker: string | null;

  pendingPermissions: PermissionInfo[];
  streamingTokens: string;
  timeline: TimelineEvent[];
  filesInRun: FileOperation[];
  openFiles: OpenFile[];
  activeFileTab: string | null;

  lastError: string | null;
  logs: string[];

  // Project Inspector — persistent test results + real token throughput
  lastTestRun:     TestRunState;
  tokenTimestamps: number[];

  // Chat
  messages: ChatMessage[];
  currentMarkMsgId: string | null;

  // Feature 9 — Conversation Branches
  branches:     Record<string, ChatMessage[]>;
  activeBranch: string;

  // Feature 13 — Token Budget
  tokenBudget: { used: number; window: number };

  // Voice
  voice: VoiceState;

  // Live Engineer panel
  activityFeed:        ActivityEntry[];
  reasoningStage:      ReasoningStage;
  narrationTranscript: NarrationEntry[];
  workspaceContext:    WorkspaceContext | null;
  idleSuggestions:     IdleSuggestion[];
  engineeringMemory:   EngineeringMemoryState;

  // Preview Workspace
  previews:        PreviewInfo[];
  activePreviewId: string | null;
  deviceMode:      DeviceMode;
  themeMode:       ThemeMode;

  // Preview actions
  setActivePreviewId: (id: string | null) => void;
  setDeviceMode:      (mode: DeviceMode) => void;
  setThemeMode:       (mode: ThemeMode) => void;
  removePreview:      (id: string) => void;

  // Actions
  setServerUrl:      (url: string) => void;
  connectWebSocket:  () => void;
  startRun:          (goal: string, workspace: string, testCmd?: string) => Promise<void>;
  sendUserMessage:   (text: string, workspace: string) => Promise<void>;
  clearMessages:     () => void;
  cancelRun:         () => Promise<void>;
  approve:           (requestId: string, always?: boolean) => Promise<void>;
  deny:              (requestId: string, reason?: string) => Promise<void>;
  fetchFileContent:  (path: string, isDiff?: boolean) => Promise<void>;
  closeFile:         (path: string) => void;
  setActiveFileTab:  (path: string | null) => void;
  setWorkspace:      (ws: string) => void;

  // Branch actions (Feature 9)
  createBranch:  (name: string) => void;
  switchBranch:  (name: string) => void;
  deleteBranch:  (name: string) => void;

  // Voice
  startVoice:           (mode: VoiceMode) => Promise<void>;
  stopVoice:            () => Promise<void>;
  toggleMute:           () => Promise<void>;
  updateVoiceSettings:  (s: Partial<VoiceSettings>) => Promise<void>;
  transcribeAudio:      (blob: Blob) => Promise<string>;
  speak:                (text: string) => Promise<void>;
  setTtsProvider:       (provider: 'kokoro' | 'piper' | 'openai' | 'browser') => void;
  setOpenaiVoice:       (voice: string) => void;
  setTtsVoice:          (voice: string) => void;
  setTtsVolume:         (volume: number) => void;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DEFAULT_WORKERS: WorkerState[] = [
  { name: 'Research', status: 'idle' },
  { name: 'Planning', status: 'idle' },
  { name: 'Coding',   status: 'idle' },
  { name: 'Testing',  status: 'idle' },
  { name: 'Quality',  status: 'idle' },
  { name: 'Review',   status: 'idle' },
];

const DEFAULT_VOICE: VoiceState = {
  state: 'idle', running: false, mode: 'push_to_talk',
  muted: false, autoSubmit: true, whisperModel: 'base',
  ttsVoice: 'af_sarah', ttsSpeed: 1.0, ttsVolume: 1.0,
  wakePhraseEnabled: false, transcript: '', isBrowserTTSFallback: false,
  ttsProvider: 'kokoro', openaiVoice: 'nova',
};

// ── Browser TTS ───────────────────────────────────────────────────────────────

function browserSpeak(text: string, speed = 1.0, volume = 1.0): void {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = Math.max(0.5, Math.min(2.0, speed));
  utt.volume = Math.max(0, Math.min(1, volume));
  window.speechSynthesis.speak(utt);
}

// ── Unified TTS provider endpoint (kokoro / piper / openai) ────────────────────
//
// Backend dispatch lives in smartagent/tts/factory.py — whichever provider is
// active there (kept in sync via setTtsProvider below) is what actually
// synthesizes. The frontend doesn't need per-provider branching any more.

async function ttsSpeak(
  text: string, voice: string, speed: number, serverUrl: string, volume = 1.0,
): Promise<void> {
  const res = await fetch(`${serverUrl}/tts/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, speed }),
  });
  if (!res.ok) throw new Error(`TTS ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.volume = Math.max(0, Math.min(1, volume));
  await new Promise<void>((resolve, reject) => {
    audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
    audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error('audio error')); };
    audio.play().catch(reject);
  });
}

function _voiceForProvider(voice: VoiceState): string {
  return voice.ttsProvider === 'openai' ? voice.openaiVoice : voice.ttsVoice;
}

// ── WebSocket singleton ───────────────────────────────────────────────────────

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

// ── Store ─────────────────────────────────────────────────────────────────────

export const useMarkStore = create<MarkState>((set, get) => {

  // ── Chat message helpers ───────────────────────────────────────────────────

  const _id = () => Math.random().toString(36).slice(2, 10);

  /** Start a new MARK message and return its ID. */
  const _startMarkMsg = (timestamp: string): string => {
    const id = _id();
    set(state => ({
      currentMarkMsgId: id,
      messages: [...state.messages, {
        id, role: 'mark' as const, timestamp, blocks: [], isActive: true,
      }],
    }));
    return id;
  };

  /** Append streaming tokens to the last block (or create a streaming block). */
  const _appendText = (text: string) => {
    set(state => {
      const id = state.currentMarkMsgId;
      if (!id) return {};
      return {
        messages: state.messages.map(m => {
          if (m.id !== id) return m;
          const blocks = [...m.blocks];
          const last = blocks[blocks.length - 1];
          if (last?.type === 'streaming') {
            blocks[blocks.length - 1] = { type: 'streaming', text: last.text + text };
          } else {
            blocks.push({ type: 'streaming', text });
          }
          return { ...m, blocks };
        }),
      };
    });
  };

  /**
   * Push a new block to the current MARK message.
   * Automatically finalises any open streaming block first.
   */
  const _pushBlock = (block: ContentBlock) => {
    set(state => {
      const id = state.currentMarkMsgId;
      if (!id) return {};
      return {
        messages: state.messages.map(m => {
          if (m.id !== id) return m;
          const blocks = m.blocks.map(b =>
            b.type === 'streaming' ? { type: 'text' as const, text: b.text } : b
          );
          return { ...m, blocks: [...blocks, block] };
        }),
      };
    });
  };

  /** Update a block inside the current MARK message using a predicate. */
  const _updateBlock = (
    match: (b: ContentBlock) => boolean,
    update: (b: ContentBlock) => ContentBlock,
  ) => {
    set(state => {
      const id = state.currentMarkMsgId;
      if (!id) return {};
      return {
        messages: state.messages.map(m => m.id !== id ? m : {
          ...m,
          blocks: m.blocks.map(b => match(b) ? update(b) : b),
        }),
      };
    });
  };

  /** Close out the current MARK message, optionally appending final blocks. */
  const _finaliseMsg = (extra: ContentBlock[] = []) => {
    set(state => {
      const id = state.currentMarkMsgId;
      if (!id) return {};
      return {
        currentMarkMsgId: null,
        messages: state.messages.map(m => m.id !== id ? m : {
          ...m,
          isActive: false,
          blocks: [
            ...m.blocks.map(b => b.type === 'streaming' ? { type: 'text' as const, text: b.text } : b),
            ...extra,
          ],
        }),
      };
    });
  };

  /** Add an entry to the live narration transcript. */
  const _addNarration = (text: string, type: NarrationEntry['type'] = 'action') => {
    if (!text?.trim()) return;
    set(state => ({
      narrationTranscript: [
        { id: _id(), timestamp: new Date().toISOString(), text: text.trim(), type },
        ...state.narrationTranscript,
      ].slice(0, 100),
    }));
  };

  /** Speak text via TTS unless muted, and track in narration transcript.
   *  Kokoro is the default provider; browser speechSynthesis is fallback-only.
   *  Narration is gated only by mute — it doesn't require an STT "listening"
   *  session, since speaking MARK's own summaries and listening for the
   *  user's voice are independent concerns. */
  const _narrate = (text: string) => {
    if (!text?.trim()) return;
    _addNarration(text, 'action');
    const { voice, serverUrl } = get();
    if (voice.muted) return;
    set(state => ({ voice: { ...state.voice, state: 'speaking' } }));
    const done = () => set(state => ({
      voice: { ...state.voice, state: state.voice.state === 'speaking' ? 'idle' : state.voice.state },
    }));
    if (voice.ttsProvider === 'browser' || voice.isBrowserTTSFallback) {
      browserSpeak(text, voice.ttsSpeed, voice.ttsVolume);
      done();
      return;
    }
    ttsSpeak(text, _voiceForProvider(voice), voice.ttsSpeed, serverUrl, voice.ttsVolume)
      .catch(() => browserSpeak(text, voice.ttsSpeed, voice.ttsVolume))
      .finally(done);
  };

  // ── Return the store ───────────────────────────────────────────────────────

  return {
    // State
    serverUrl:        (() => {
      if (localStorage.getItem('mark_server_url')) return localStorage.getItem('mark_server_url')!;
      const viteUrl = import.meta.env.VITE_API_URL as string | undefined;
      if (!viteUrl) return window.location.origin;
      // Relative path like /mark-api → prepend origin so WebSocket URLs work
      if (viteUrl.startsWith('/')) return window.location.origin + viteUrl;
      // Full URL like http://localhost:8000 → use directly
      return viteUrl;
    })(),
    connectionStatus: 'disconnected',
    running:          false,
    goal:             '',
    workspace:        localStorage.getItem('mark_workspace') || '',
    elapsed:          0,
    cancelRequested:  false,
    workers:          [...DEFAULT_WORKERS],
    currentWorker:    null,
    pendingPermissions: [],
    streamingTokens:  '',
    timeline:         [],
    filesInRun:       [],
    openFiles:        [],
    activeFileTab:    null,
    lastError:        null,
    logs:             [],
    lastTestRun:      { status: 'idle' },
    tokenTimestamps:  [],
    messages:         [],
    currentMarkMsgId: null,
    branches:         { main: [] },
    activeBranch:     'main',
    tokenBudget:      { used: 0, window: 8192 },
    voice:            { ...DEFAULT_VOICE },

    // Live Engineer panel defaults
    activityFeed:        [],
    reasoningStage:      'idle' as ReasoningStage,
    narrationTranscript: [],
    workspaceContext:    null,
    idleSuggestions:     [],
    engineeringMemory: {
      currentGoal:         null,
      completedMilestones: [],
      blockers:            [],
      context:             '',
      sessionElapsed:      0,
    },

    // Preview Workspace defaults
    previews:        [],
    activePreviewId: null,
    deviceMode:      'desktop',
    themeMode:       'dark',

    // ── Branch actions (Feature 9) ────────────────────────────────────────────

    createBranch: (name) => set(state => ({
      branches: { ...state.branches, [name]: [...state.messages] },
    })),

    switchBranch: (name) => set(state => {
      // Save current messages into current branch, then restore target branch
      const currentBranch = state.activeBranch;
      const updated = {
        ...state.branches,
        [currentBranch]: [...state.messages],
      };
      return {
        branches:     updated,
        activeBranch: name,
        messages:     updated[name] ?? [],
        currentMarkMsgId: null,
      };
    }),

    deleteBranch: (name) => set(state => {
      if (name === 'main') return {};
      const branches = { ...state.branches };
      delete branches[name];
      if (state.activeBranch === name) {
        return { branches, activeBranch: 'main', messages: branches['main'] ?? [], currentMarkMsgId: null };
      }
      return { branches };
    }),

    // ── Preview actions ───────────────────────────────────────────────────────

    setActivePreviewId: (id) => set({ activePreviewId: id }),
    setDeviceMode:      (mode) => set({ deviceMode: mode }),
    setThemeMode:       (mode) => set({ themeMode: mode }),
    removePreview: (id) => set(state => {
      const remaining = state.previews.filter(p => p.id !== id);
      return {
        previews: remaining,
        activePreviewId: state.activePreviewId === id ? (remaining[0]?.id ?? null) : state.activePreviewId,
      };
    }),

    // ── Actions ───────────────────────────────────────────────────────────────

    setServerUrl: (url) => {
      localStorage.setItem('mark_server_url', url);
      set({ serverUrl: url });
      get().connectWebSocket();
    },

    setWorkspace: (ws) => {
      localStorage.setItem('mark_workspace', ws);
      set({ workspace: ws });
    },

    connectWebSocket: () => {
      if (ws) { ws.close(); ws = null; }
      const { serverUrl } = get();
      const wsUrl = serverUrl.replace(/^http/, 'ws') + '/ws';
      set({ connectionStatus: 'connecting' });

      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          set({ connectionStatus: 'connected' });
          if (reconnectTimer) clearTimeout(reconnectTimer);
          // Auto-enable browser TTS narration (zero config, instant)
          set(state => ({ voice: { ...state.voice, running: true, isBrowserTTSFallback: true } }));
          // Greeting on first connect
          if (get().messages.length === 0) {
            set(state => ({
              messages: [...state.messages, {
                id: _id(), role: 'mark' as const,
                timestamp: new Date().toISOString(),
                blocks: [{
                  type: 'text',
                  text: "Good morning. I'm MARK — your AI software engineer.\n\nType a goal or hold the microphone button to speak. I'll plan, write, test, and narrate everything as I build.",
                }],
                isActive: false,
              }],
            }));
          }
        };

        ws.onclose = () => {
          set({ connectionStatus: 'disconnected' });
          reconnectTimer = setTimeout(() => get().connectWebSocket(), 3000);
        };

        ws.onerror = () => { /* handled by close */ };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type !== 'event') return;
            const { name, payload, timestamp } = data;
            if (name === 'ping') return;

            // Raw logs
            set(state => ({ logs: [...state.logs.slice(-999), JSON.stringify(data)] }));

            const addTimeline = (msg: string) => set(state => ({
              timeline: [
                { id: Math.random().toString(), timestamp, type: name, message: msg },
                ...state.timeline,
              ].slice(0, 200),
            }));

            switch (name) {

              // ── Run lifecycle ──────────────────────────────────────────────
              case 'RunStarted': {
                set(state => ({
                  running: true, goal: payload.goal, workspace: payload.workspace,
                  elapsed: 0, cancelRequested: false, streamingTokens: '',
                  timeline: [], filesInRun: [], lastError: null,
                  workers: [...DEFAULT_WORKERS],
                  activityFeed:   [],
                  reasoningStage: 'analyzing' as ReasoningStage,
                  engineeringMemory: { ...state.engineeringMemory, currentGoal: payload.goal },
                }));
                addTimeline(`Run started: ${payload.goal}`);
                _startMarkMsg(timestamp);
                _pushBlock({ type: 'text', text: `I'll get started on that right away.\n` });
                _narrate('On it — analyzing the workspace.');
                break;
              }

              case 'RunCompleted': {
                set({ running: false, elapsed: payload.elapsed, reasoningStage: 'done' as ReasoningStage });
                addTimeline(`Run completed ${payload.success ? 'successfully' : 'with failures'}.`);
                const { filesInRun } = get();
                const created  = filesInRun.filter(f => f.operation === 'created').map(f => f.path);
                const modified = filesInRun.filter(f => f.operation === 'modified').map(f => f.path);
                const summaryText = payload.success
                  ? created.length + modified.length > 0
                    ? `Done! Created ${created.length} file(s), modified ${modified.length} file(s).`
                    : 'Done!'
                  : payload.summary
                    ? `Finished: ${payload.summary}`
                    : 'Completed with some failures.';
                _finaliseMsg([{
                  type: 'summary', text: summaryText, success: payload.success,
                  filesCreated: created, filesModified: modified, elapsed: payload.elapsed,
                }]);
                _narrate(summaryText);
                break;
              }

              case 'RunCancelled': {
                set({ running: false, cancelRequested: false });
                addTimeline('Run cancelled by user.');
                _finaliseMsg([{ type: 'text', text: 'Run cancelled.' }]);
                break;
              }

              case 'RunFailed': {
                const failMsg = payload.error || payload.summary || 'Run failed unexpectedly.';
                set({ running: false, lastError: failMsg });
                addTimeline(`Run failed: ${failMsg}`);
                _finaliseMsg([{ type: 'error', text: failMsg }]);
                _narrate('The run encountered an error.');
                break;
              }

              case 'StatusChanged': {
                set({
                  running: payload.running, goal: payload.goal,
                  workspace: payload.workspace, elapsed: payload.elapsed,
                });
                break;
              }

              // ── Streaming tokens ───────────────────────────────────────────
              case 'StreamingToken': {
                set(state => ({
                  streamingTokens: state.streamingTokens + payload.text,
                  // Real arrival timestamps for Project Inspector's tokens/sec chart —
                  // capped so a long run doesn't grow this unbounded.
                  tokenTimestamps: [...state.tokenTimestamps, Date.now()].slice(-2000),
                }));
                _appendText(payload.text);
                break;
              }

              // ── Workers ────────────────────────────────────────────────────
              case 'WorkerStarted': {
                if (payload.worker) {
                  set(state => ({
                    currentWorker: payload.worker,
                    workers: state.workers.map(w =>
                      w.name === payload.worker
                        ? { ...w, status: 'running', task: payload.task, progress: 0, startedAt: new Date().toISOString(), filesTouched: [] }
                        : w
                    ),
                  }));
                  addTimeline(`Worker started: ${payload.worker}`);
                  _pushBlock({ type: 'worker', name: payload.worker, status: 'running', task: payload.task });
                  const phrases: Record<string, string> = {
                    Planning:  'Planning the implementation…',
                    Research:  'Researching the codebase…',
                    Coding:    'Writing code…',
                    Testing:   'Running tests…',
                    Quality:   'Checking code quality…',
                    Review:    'Reviewing the work…',
                  };
                  if (phrases[payload.worker]) _narrate(phrases[payload.worker]);
                }
                break;
              }

              case 'WorkerFinished': {
                if (payload.worker) {
                  set(state => ({
                    currentWorker: null,
                    workers: state.workers.map(w =>
                      w.name === payload.worker
                        ? { ...w, status: payload.success ? 'success' : 'failed', progress: 100 }
                        : w
                    ),
                  }));
                  addTimeline(`Worker finished: ${payload.worker}`);
                  _updateBlock(
                    b => b.type === 'worker' && (b as any).name === payload.worker && (b as any).status === 'running',
                    b => ({ ...b, status: payload.success ? 'success' : 'failed' } as ContentBlock),
                  );
                }
                break;
              }

              case 'WorkerThinking': {
                if (payload.worker) {
                  set(state => ({
                    workers: state.workers.map(w =>
                      w.name === payload.worker ? { ...w, thought: payload.thought } : w
                    ),
                  }));
                }
                break;
              }

              // ── Planning ───────────────────────────────────────────────────
              case 'PlanningStarted':
                addTimeline('Planning started…');
                break;
              case 'PlanningFinished':
                addTimeline('Planning finished.');
                break;

              // ── File events ────────────────────────────────────────────────
              case 'FileCreated':
              case 'FileModified':
              case 'FileDeleted': {
                if (payload.path) {
                  const op = name === 'FileCreated' ? 'created' : name === 'FileModified' ? 'modified' : 'deleted';
                  set(state => ({
                    filesInRun: [
                      ...state.filesInRun.filter(f => f.path !== payload.path),
                      { path: payload.path, operation: op as FileOperation['operation'] },
                    ],
                    // Attribute the touched file to whichever worker is active —
                    // no new backend event needed, correlated from timing alone.
                    workers: state.currentWorker
                      ? state.workers.map(w =>
                          w.name === state.currentWorker && !(w.filesTouched ?? []).includes(payload.path)
                            ? { ...w, filesTouched: [...(w.filesTouched ?? []), payload.path] }
                            : w
                        )
                      : state.workers,
                  }));
                  addTimeline(`File ${op}: ${payload.path}`);
                  _pushBlock({ type: 'file', op: op as any, path: payload.path });
                }
                break;
              }

              // ── Tests ──────────────────────────────────────────────────────
              case 'TestsStarted': {
                addTimeline('Running tests…');
                _pushBlock({ type: 'tests', status: 'running' });
                set({ lastTestRun: { status: 'running', timestamp: new Date().toISOString() } });
                break;
              }
              case 'TestsPassed': {
                addTimeline('Tests passed successfully.');
                _updateBlock(
                  b => b.type === 'tests' && (b as any).status === 'running',
                  b => ({ ...b, status: 'passed' } as ContentBlock),
                );
                set({ lastTestRun: { status: 'passed', output: payload.output, timestamp: new Date().toISOString() } });
                _narrate('Tests passed!');
                break;
              }
              case 'TestsFailed': {
                addTimeline('Tests failed.');
                _updateBlock(
                  b => b.type === 'tests' && (b as any).status === 'running',
                  b => ({ ...b, status: 'failed', output: payload.output } as ContentBlock),
                );
                set({ lastTestRun: { status: 'failed', output: payload.output, timestamp: new Date().toISOString() } });
                _narrate('Tests failed. Attempting to fix…');
                break;
              }

              // ── Quality ────────────────────────────────────────────────────
              case 'QualityStarted':
                addTimeline('Quality checks started…');
                break;
              case 'QualityFinished':
                addTimeline('Quality checks finished.');
                break;

              // ── Permissions ────────────────────────────────────────────────
              case 'PermissionRequested': {
                set(state => ({ pendingPermissions: [...state.pendingPermissions, payload] }));
                addTimeline(`Permission requested: ${payload.operation} on ${payload.path}`);
                _pushBlock({ type: 'approval', requestId: payload.request_id, operation: payload.operation, path: payload.path, diff: payload.diff });
                _narrate(`I need your approval to ${payload.operation} ${payload.path.split('/').pop()}`);
                break;
              }

              case 'PermissionGranted':
              case 'PermissionDenied': {
                set(state => ({
                  pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== payload.request_id),
                }));
                addTimeline(`Permission ${name === 'PermissionGranted' ? 'granted' : 'denied'}.`);
                break;
              }

              // ── Error ──────────────────────────────────────────────────────
              case 'Error': {
                const msg = payload.error || payload.message || 'Unknown error';
                set({ lastError: msg });
                addTimeline(`Error: ${msg}`);
                break;
              }

              // ── Voice events ───────────────────────────────────────────────
              case 'VoiceStateChanged':
                set(state => ({ voice: { ...state.voice, state: payload.state as VoiceStateValue } }));
                break;
              case 'VoiceStarted':
                set(state => ({ voice: { ...state.voice, running: true, mode: payload.mode as VoiceMode } }));
                break;
              case 'VoiceStopped':
                set(state => ({ voice: { ...state.voice, running: false, state: 'idle' } }));
                break;
              case 'VoiceWakeWordDetected':
                addTimeline('Wake word detected');
                break;
              case 'VoiceTranscribed':
                set(state => ({ voice: { ...state.voice, transcript: payload.text } }));
                break;
              case 'VoiceSpeakingStarted':
                set(state => ({ voice: { ...state.voice, state: 'speaking' } }));
                break;
              case 'VoiceSpeakingDone':
                set(state => ({ voice: { ...state.voice, state: state.voice.running ? 'listening' : 'idle' } }));
                break;
              case 'VoiceTTSFallback':
                set(state => ({ voice: { ...state.voice, isBrowserTTSFallback: true } }));
                browserSpeak(payload.text, get().voice.ttsSpeed);
                break;
              case 'VoiceError':
                set(state => ({ voice: { ...state.voice, state: 'error' } }));
                addTimeline(`Voice error: ${payload.error}`);
                break;

              // ── Feature 13: Token Budget ───────────────────────────────────
              case 'TokenBudgetUpdate':
                set({ tokenBudget: { used: payload.used ?? 0, window: payload.window ?? 8192 } });
                break;

              // ── Feature 8: Self Reflection ─────────────────────────────────
              case 'ReflectionComplete':
                addTimeline(`Reflection: ${payload.lesson || 'completed'}`);
                break;

              // ── Feature 17: Evaluation ────────────────────────────────────
              case 'EvaluationComplete':
                addTimeline(`Evaluation complete · run ${payload.run_id}`);
                break;

              // ── Live Engineer panel ────────────────────────────────────────
              case 'WorkspaceAnalyzed': {
                const ctx: WorkspaceContext = {
                  projectType:   payload.project_type ?? 'Unknown',
                  frameworks:    payload.frameworks ?? [],
                  gitBranch:     payload.git_branch ?? 'unknown',
                  lastCommit:    payload.last_commit ?? '',
                  testFramework: payload.test_framework ?? null,
                  todoCount:     payload.todo_count ?? 0,
                  fileCount:     payload.file_count ?? 0,
                  hasCI:         payload.has_ci ?? false,
                  summary:       payload.summary ?? '',
                  workspace:     payload.workspace ?? '',
                };
                set({ workspaceContext: ctx });
                _addNarration(ctx.summary || `${ctx.projectType} workspace ready`, 'stage');
                _narrate(ctx.summary || `${ctx.projectType} project ready`);
                break;
              }

              case 'ReasoningStage':
                set({ reasoningStage: (payload.stage ?? 'idle') as ReasoningStage });
                break;

              case 'ActivityFeedEntry': {
                const entry: ActivityEntry = {
                  id: _id(), timestamp,
                  type:    payload.type    ?? 'run',
                  text:    payload.text    ?? '',
                  detail:  payload.detail,
                  success: payload.success,
                  elapsed: payload.elapsed,
                };
                set(state => ({
                  activityFeed: [entry, ...state.activityFeed].slice(0, 300),
                }));
                break;
              }

              case 'IdleSuggestion': {
                const sug: IdleSuggestion = {
                  id: _id(), timestamp,
                  category:    payload.category    ?? 'docs',
                  title:       payload.title       ?? '',
                  description: payload.description ?? '',
                  file:        payload.file,
                  priority:    payload.priority    ?? 'medium',
                };
                set(state => ({
                  idleSuggestions: [sug, ...state.idleSuggestions].slice(0, 30),
                }));
                _addNarration(`Suggestion: ${sug.title}`, 'suggestion');
                break;
              }

              case 'MemoryUpdated':
                set({
                  engineeringMemory: {
                    currentGoal:         payload.current_goal ?? null,
                    completedMilestones: payload.milestones   ?? [],
                    blockers:            payload.blockers     ?? [],
                    context:             payload.context      ?? '',
                    sessionElapsed:      payload.session_elapsed ?? 0,
                  },
                });
                break;

              case 'Narration': {
                const text = payload.text ?? '';
                if (text) {
                  _addNarration(text, (payload.narration_type ?? 'action') as NarrationEntry['type']);
                  _narrate(text);
                }
                break;
              }

              // ── Preview Workspace events ───────────────────────────────────
              case 'PreviewRegistered': {
                const preview: PreviewInfo = {
                  id:           payload.id    ?? payload.url ?? Math.random().toString(36).slice(2),
                  url:          payload.url   ?? '',
                  title:        payload.title ?? payload.framework ?? 'Preview',
                  framework:    payload.framework ?? 'unknown',
                  status:       (payload.status ?? 'ready') as PreviewStatus,
                  port:         payload.port,
                  registeredAt: timestamp,
                };
                set(state => {
                  const exists = state.previews.find(p => p.id === preview.id);
                  return {
                    previews: exists
                      ? state.previews.map(p => p.id === preview.id ? preview : p)
                      : [...state.previews, preview],
                    activePreviewId: state.activePreviewId ?? preview.id,
                  };
                });
                addTimeline(`Preview registered: ${preview.title} → ${preview.url}`);
                const feedEntry: ActivityEntry = {
                  id: _id(), timestamp,
                  type: 'preview',
                  text: `Preview ready: ${preview.title}`,
                  detail: preview.url,
                  success: true,
                };
                set(state => ({ activityFeed: [feedEntry, ...state.activityFeed].slice(0, 300) }));
                _narrate(`Your app is now live in the preview — ${preview.title}`);
                break;
              }

              case 'PreviewUpdated': {
                set(state => ({
                  previews: state.previews.map(p =>
                    p.id === payload.id
                      ? { ...p, url: payload.url ?? p.url, status: (payload.status ?? p.status) as PreviewStatus, title: payload.title ?? p.title }
                      : p
                  ),
                }));
                addTimeline(`Preview updated: ${payload.id}`);
                const updateEntry: ActivityEntry = {
                  id: _id(), timestamp,
                  type: 'preview',
                  text: `Preview updated: ${payload.title ?? payload.id}`,
                  detail: payload.url,
                  success: true,
                };
                set(state => ({ activityFeed: [updateEntry, ...state.activityFeed].slice(0, 300) }));
                _narrate('Preview has been updated — hot-reloading now.');
                break;
              }

              case 'PreviewStopped': {
                set(state => ({
                  previews: state.previews.map(p =>
                    p.id === payload.id ? { ...p, status: 'stopped' as PreviewStatus } : p
                  ),
                }));
                addTimeline(`Preview stopped: ${payload.id}`);
                break;
              }
            }
          } catch (err) {
            console.error('WS message parse error', err);
          }
        };
      } catch (err) {
        console.error('WebSocket connect failed', err);
      }
    },

    // ── Run actions ─────────────────────────────────────────────────────────

    startRun: async (goal, workspace, testCmd) => {
      try {
        await markApi.startRun(get().serverUrl, goal, workspace, testCmd);
      } catch (err) {
        console.error(err);
        set({ lastError: 'Failed to start run' });
      }
    },

    sendUserMessage: async (text, workspace) => {
      const ts = new Date().toISOString();
      // Push the user's message to the chat thread
      set(state => ({
        messages: [...state.messages, {
          id: _id(), role: 'user' as const, timestamp: ts, text, blocks: [], isActive: false,
        }],
        workspace,
      }));
      // Kick off the actual run
      try {
        await markApi.startRun(get().serverUrl, text, workspace);
      } catch (err) {
        console.error(err);
        set(state => ({
          messages: [...state.messages, {
            id: _id(), role: 'mark' as const, timestamp: new Date().toISOString(),
            blocks: [{ type: 'error', text: 'Could not connect to the MARK server. Make sure it is running on the configured URL.' }],
            isActive: false,
          }],
          lastError: 'Failed to start run',
        }));
      }
    },

    clearMessages: () => {
      set({ messages: [], currentMarkMsgId: null, streamingTokens: '', timeline: [] });
    },

    cancelRun: async () => {
      try {
        set({ cancelRequested: true });
        await markApi.cancelRun(get().serverUrl);
      } catch (err) {
        console.error(err);
      }
    },

    approve: async (requestId, always) => {
      set(state => ({ pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== requestId) }));
      try {
        await markApi.approve(get().serverUrl, requestId, always);
      } catch (err) {
        console.error(err);
      }
    },

    deny: async (requestId, reason) => {
      set(state => ({ pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== requestId) }));
      try {
        await markApi.deny(get().serverUrl, requestId, reason);
      } catch (err) {
        console.error(err);
      }
    },

    fetchFileContent: async (path, isDiff = false) => {
      try {
        const res = await markApi.getProject(get().serverUrl, path);
        if (res.content) {
          set(state => ({
            openFiles: [...state.openFiles.filter(f => f.path !== path), { path, content: res.content!, isDiff }],
            activeFileTab: path,
          }));
        }
      } catch (err) {
        console.error(err);
      }
    },

    closeFile: (path) => {
      set(state => {
        const remaining = state.openFiles.filter(f => f.path !== path);
        return {
          openFiles: remaining,
          activeFileTab: state.activeFileTab === path ? (remaining[0]?.path || null) : state.activeFileTab,
        };
      });
    },

    setActiveFileTab: (path) => set({ activeFileTab: path }),

    // ── Voice actions ────────────────────────────────────────────────────────

    startVoice: async (mode) => {
      try {
        await markApi.startVoice(get().serverUrl, mode);
        set(state => ({ voice: { ...state.voice, running: true, mode } }));
      } catch (err) { console.error('startVoice', err); }
    },

    stopVoice: async () => {
      try {
        await markApi.stopVoice(get().serverUrl);
        set(state => ({ voice: { ...state.voice, running: false, state: 'idle' } }));
      } catch (err) { console.error('stopVoice', err); }
    },

    toggleMute: async () => {
      const muted = !get().voice.muted;
      try {
        await markApi.updateVoiceSettings(get().serverUrl, { muted });
        set(state => ({ voice: { ...state.voice, muted } }));
      } catch (err) { console.error('toggleMute', err); }
    },

    updateVoiceSettings: async (settings) => {
      try {
        const res = await markApi.updateVoiceSettings(get().serverUrl, settings);
        set(state => ({
          voice: {
            ...state.voice,
            mode:         (res.settings.mode          as VoiceMode) ?? state.voice.mode,
            muted:        res.settings.muted           ?? state.voice.muted,
            autoSubmit:   res.settings.auto_submit     ?? state.voice.autoSubmit,
            whisperModel: res.settings.whisper_model   ?? state.voice.whisperModel,
            ttsVoice:     res.settings.tts_voice       ?? state.voice.ttsVoice,
            ttsSpeed:     res.settings.tts_speed       ?? state.voice.ttsSpeed,
          },
        }));
      } catch (err) { console.error('updateVoiceSettings', err); }
    },

    transcribeAudio: async (blob) => {
      try {
        const text = await markApi.transcribeAudio(get().serverUrl, blob);
        if (text) set(state => ({ voice: { ...state.voice, transcript: text } }));
        return text;
      } catch (err) {
        console.error('transcribeAudio', err);
        return '';
      }
    },

    speak: async (text) => {
      const { voice, serverUrl } = get();
      if (voice.ttsProvider === 'browser' || voice.isBrowserTTSFallback) {
        browserSpeak(text, voice.ttsSpeed, voice.ttsVolume);
        return;
      }
      try {
        await ttsSpeak(text, _voiceForProvider(voice), voice.ttsSpeed, serverUrl, voice.ttsVolume);
      } catch {
        browserSpeak(text, voice.ttsSpeed, voice.ttsVolume);
      }
    },

    setTtsProvider: (provider) => {
      set(state => ({ voice: { ...state.voice, ttsProvider: provider } }));
      if (provider === 'browser') return;
      const { serverUrl } = get();
      fetch(`${serverUrl}/tts/provider`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      }).catch(() => { /* best-effort — /tts/speak will just use whatever the backend still has active */ });
    },

    setOpenaiVoice: (voice) =>
      set(state => ({ voice: { ...state.voice, openaiVoice: voice } })),

    setTtsVoice: (voice) =>
      set(state => ({ voice: { ...state.voice, ttsVoice: voice } })),

    setTtsVolume: (volume) =>
      set(state => ({ voice: { ...state.voice, ttsVolume: Math.max(0, Math.min(1, volume)) } })),
  };
});
