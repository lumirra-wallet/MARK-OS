import { create } from 'zustand';
import { markApi, PermissionInfo, SelfState } from '@/lib/markApi';
// SpeechPlayer was used for binary-frame PCM audio on /ws.
// Voice now travels over a LiveKit WebRTC track — no binary frames.

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

// ── Preview types ─────────────────────────────────────────────────────────────

// Matches what the backend (api_previews.py) actually ever sends — it never
// emits 'starting'/'ready'/'error'/'stopped'.
export type PreviewStatus = 'active' | 'unreachable' | 'closed';
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

// ── Brain Foundation types ────────────────────────────────────────────────────

/** A single real observable step in MARK's cognitive pipeline. */
export interface CognitiveEvent {
  id: string;
  timestamp: string;
  step: string;
  detail?: string;
}

/** A real memory write from the backend. */
export interface MemoryActivityEntry {
  id: string;
  timestamp: string;
  layer: 'episodic' | 'semantic' | 'owner';
  summary: string;
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

  // Live Engineer panel
  activityFeed:        ActivityEntry[];
  reasoningStage:      ReasoningStage;
  workspaceContext:    WorkspaceContext | null;
  idleSuggestions:     IdleSuggestion[];
  engineeringMemory:   EngineeringMemoryState;

  // Preview Workspace
  previews:        PreviewInfo[];
  activePreviewId: string | null;
  deviceMode:      DeviceMode;
  themeMode:       ThemeMode;

  // MARK's own real-time state — agent.mind, pushed over the WebSocket on
  // every real transition (see SelfStateChanged), plus one fetch on connect
  // for the initial snapshot. No polling: this is either the last real
  // push, or null until the first one arrives.
  selfState: SelfState | null;
  fetchSelfState: () => Promise<void>;

  // MARK's real voice — audio frames are real Kokoro output, broadcast by
  // smartagent/server/speech_runtime.py over this same WebSocket (see
  // ws.onmessage's binary branch). isMarkSpeaking reflects the actual
  // audio player's state (SpeechPlayer), not a guess from text events.
  // speechEngineUnavailable is set once, at most, by a real backend
  // SpeechEngineUnavailable check — it's the only condition under which
  // use-voice.ts is allowed to fall back to the browser's speechSynthesis.
  isMarkSpeaking: boolean;
  speechEngineUnavailable: boolean;
  stopMarkSpeech: () => void;

  // ── Brain Foundation — every field originates from a real backend event ──
  // No counters are incremented here speculatively; every increment is
  // triggered by a real BrainEvent pushed over the WebSocket.
  cognitiveEvents:  CognitiveEvent[];       // last 20 pipeline steps (newest first)
  emotionalState:   string;                 // 'neutral' | 'curious' | 'focused' | 'satisfied' | 'uncertain' | 'frustrated'
  emotionalReason:  string;                 // reason for the current state
  memoryActivity:   MemoryActivityEntry[];  // last 10 real memory writes
  knowledgeGrowth:  number;                 // concepts committed this session

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
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DEFAULT_WORKERS: WorkerState[] = [
  { name: 'Engineer', status: 'idle' },
  { name: 'QA',        status: 'idle' },
  { name: 'Debugger',  status: 'idle' },
  { name: 'Reviewer',  status: 'idle' },
  { name: 'Git',       status: 'idle' },
  { name: 'Research',  status: 'idle' },
  { name: 'Security',  status: 'idle' },
  { name: 'Docs',      status: 'idle' },
  { name: 'Preview',   status: 'idle' },
];

// ── Brain Foundation: self-state sync helper ─────────────────────────────────
// Reads the memory_activity + emotional_state from a self-state snapshot and
// writes them into the store. Called from both the poll path (fetchSelfState)
// and the push path (SelfStateChanged) so the memory panel shows real counts
// on load — before any live BrainEvent has fired.
function _applySelfStateBrainFields(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any,
  _get: () => unknown,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  set: (partial: any) => void,
): void {
  // Treat data as a plain object — works for both SelfState and raw WS payload.
  const d = data as Record<string, unknown>;
  // Emotional state — only overwrite if the server reports a real state
  const emo = d.emotional_state as string | undefined;
  if (emo) {
    set({ emotionalState: emo, emotionalReason: (data.emotional_reason as string) ?? '' });
  }
  // Memory counts — translate the `{ episodic_today, semantic_total,
  // owner_attributes }` summary into one synthetic MemoryActivityEntry so
  // the memory panel shows meaningful numbers immediately on load.
  const ma = data.memory_activity as Record<string, number> | undefined;
  if (ma) {
    const episodic = ma.episodic_today  ?? 0;
    const semantic  = ma.semantic_total  ?? 0;
    const owner     = ma.owner_attributes ?? 0;
    if (episodic + semantic + owner > 0) {
      const entry: MemoryActivityEntry = {
        id:        Math.random().toString(36).slice(2, 10),
        timestamp: new Date().toISOString(),
        layer:     'episodic',
        summary:   `${episodic} events today · ${semantic} concepts · ${owner} owner attributes`,
      };
      // Only add the synthetic entry if the panel is still empty — once real
      // BrainEvents arrive they take over and we don't want stale summaries.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      set((state: any) => ({
        memoryActivity:  state.memoryActivity.length === 0 ? [entry] : state.memoryActivity,
        knowledgeGrowth: state.knowledgeGrowth  === 0      ? semantic  : state.knowledgeGrowth,
      }));
    }
  }
}

// ── WebSocket singleton ───────────────────────────────────────────────────────

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
// Consecutive failed-connect count, reset to 0 the moment a connection
// actually opens — drives the backoff below. MARK should feel "always
// connected": a fresh drop recovers almost instantly, and only a
// genuinely dead server backs off toward a slower retry.
let reconnectAttempts = 0;
const RECONNECT_BASE_MS = 250;
const RECONNECT_MAX_MS  = 30_000;  // back off to 30 s max — never gives up
let liveRecoveryListenersInstalled = false;
// Voice audio is now delivered via a LiveKit WebRTC audio track (use-voice.ts).
// No module-level speech player is needed on the /ws path any more.

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

  // ── Return the store ───────────────────────────────────────────────────────

  return {
    // State
    serverUrl:        (() => {
      if (localStorage.getItem('mark_server_url')) return localStorage.getItem('mark_server_url')!;
      const viteUrl = import.meta.env.VITE_API_URL as string | undefined;
      // Default to /mark-api so the WS URL resolves correctly in Replit's
      // proxied preview — bare origin gives wss://domain/ws which misses the
      // path prefix and every reconnect fails silently.
      if (!viteUrl) return window.location.origin + '/mark-api';
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

    // Live Engineer panel defaults
    activityFeed:        [],
    reasoningStage:      'idle' as ReasoningStage,
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

    // MARK's real-time self-state — null until the first fetch/push lands.
    selfState: null,
    fetchSelfState: async () => {
      try {
        const s = await markApi.getSelfState(get().serverUrl);
        set({ selfState: s });
        // Brain Foundation: seed memory + emotional state from the poll so
        // the panel shows real numbers on load, before any BrainEvent fires.
        _applySelfStateBrainFields(s, get, set);
      } catch {
        /* stay null — the Presence Engine has an honest "unknown" state for this */
      }
    },

    // MARK's real voice
    isMarkSpeaking: false,
    speechEngineUnavailable: false,

    // Brain Foundation — all zero/empty until real events arrive
    cognitiveEvents:  [],
    emotionalState:   'neutral',
    emotionalReason:  '',
    memoryActivity:   [],
    knowledgeGrowth:  0,
    stopMarkSpeech: () => {
      // On the LiveKit path, MARK's audio stops naturally when the agent
      // drains its PCM queue without publishing. Marking isMarkSpeaking=false
      // here unmutes the mic gate in use-voice.ts (after the 350ms holdoff).
      set({ isMarkSpeaking: false });
    },

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
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      const { serverUrl } = get();
      // Normalise trailing slash so we never produce `.../mark-api//ws`.
      const wsUrl = serverUrl.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws';
      set({ connectionStatus: 'connecting' });

      // Recover the instant the tab regains focus or the network comes
      // back — installed once, not per-connect, so it doesn't stack.
      // Without this, a laptop sleep/tab-switch during a genuinely dead
      // stretch waits out the full backoff before even trying again.
      if (!liveRecoveryListenersInstalled) {
        liveRecoveryListenersInstalled = true;
        window.addEventListener('online', () => get().connectWebSocket());
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible' && get().connectionStatus !== 'connected') {
            get().connectWebSocket();
          }
        });
      }

      try {
        ws = new WebSocket(wsUrl);
        // Binary frames on this socket are MARK's real synthesized speech
        // (see speech_runtime.py) — arraybuffer avoids an async Blob hop.
        ws.binaryType = 'arraybuffer';

        ws.onopen = () => {
          set({ connectionStatus: 'connected' });
          reconnectAttempts = 0;
          if (reconnectTimer) clearTimeout(reconnectTimer);
          // No hardcoded greeting here — the real opening message arrives
          // via the MarkOpening event below, generated server-side from an
          // actual look at the repo (and never silent even if that LLM call
          // fails — see reflect_on_run's fallback contract). A canned
          // "I'm MARK — the executive director..." line here just meant
          // every fresh connection showed two openings, and reintroduced
          // the exact engineering-first framing that line was fixed away
          // from server-side.
          get().fetchSelfState();
        };

        ws.onclose = () => {
          set({ connectionStatus: 'disconnected' });
          // Never give up — reconnect forever with exponential backoff capped
          // at RECONNECT_MAX_MS. The connection stays alive until the user
          // deliberately closes the browser. Stats and panels never reset on
          // their own; the server watchdog keeps the backend alive on its side.
          const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempts, RECONNECT_MAX_MS);
          reconnectAttempts += 1;
          reconnectTimer = setTimeout(() => get().connectWebSocket(), delay);
        };

        ws.onerror = () => { /* handled by close */ };

        ws.onmessage = (event) => {
          // Binary frames previously carried raw PCM audio on the WebSocket
          // path. In the LiveKit transport, audio arrives as a WebRTC track
          // directly in the browser — no binary frames come over /ws any
          // more. If any stray binary frame does arrive, drop it silently.
          if (event.data instanceof ArrayBuffer) return;
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
                // No canned opener — this fired on every message regardless
                // of what MARK actually decided to do with it, including
                // plain conversation. The bubble starts empty and fills with
                // MARK's real reply as StreamingToken/block events arrive.
                _startMarkMsg(timestamp);
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
                break;
              }

              // MARK's real internal state changed (agent.mind) — pushed at
              // every real transition (task started, task finished), not
              // polled. The Presence Engine reads this directly.
              case 'SelfStateChanged': {
                set({ selfState: payload });
                // Sync brain fields from pushed self-state (same data as the poll).
                _applySelfStateBrainFields(payload, get, set);
                break;
              }

              // MARK's voice via LiveKit WebRTC track.
              // SpeechStart/SpeechEnd drive isMarkSpeaking directly —
              // the echo gate in use-voice.ts reads this to mute the mic
              // while MARK is speaking.  SpeechInterrupted is the
              // backend-confirmed stop; the frontend usually stops first
              // via the LiveKit data channel speech_start event.
              case 'SpeechStart':
                set({ isMarkSpeaking: true });
                break;

              case 'SpeechEnd':
                set({ isMarkSpeaking: false });
                break;

              case 'SpeechInterrupted': {
                get().stopMarkSpeech();
                break;
              }

              case 'SpeechEngineUnavailable': {
                set({ speechEngineUnavailable: true });
                addTimeline('Real voice engine unavailable — falling back to browser speech as a last resort.');
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
                break;
              }
              case 'TestsFailed': {
                addTimeline('Tests failed.');
                _updateBlock(
                  b => b.type === 'tests' && (b as any).status === 'running',
                  b => ({ ...b, status: 'failed', output: payload.output } as ContentBlock),
                );
                set({ lastTestRun: { status: 'failed', output: payload.output, timestamp: new Date().toISOString() } });
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

              // ── Brain Foundation — every field here originates from a real ──
              // backend brain event. The UI never increments counters on its
              // own; it only records what the brain reports.
              case 'BrainEvent': {
                const brainEvt: string = payload.event ?? '';
                const addCognitiveEvent = (step: string, detail?: string) => {
                  const ev: CognitiveEvent = {
                    id: _id(), timestamp,
                    step, detail,
                  };
                  set(state => ({
                    cognitiveEvents: [ev, ...state.cognitiveEvents].slice(0, 20),
                  }));
                };
                switch (brainEvt) {
                  case 'thinking_started':
                    addCognitiveEvent('reasoning', payload.goal?.slice(0, 60));
                    break;
                  case 'thinking_finished':
                    addCognitiveEvent('decision_made', payload.latency_ms ? `${payload.latency_ms}ms` : undefined);
                    break;
                  case 'memory_written': {
                    const memEntry: MemoryActivityEntry = {
                      id: _id(), timestamp,
                      layer: (payload.layer ?? 'episodic') as MemoryActivityEntry['layer'],
                      summary: payload.summary ?? '',
                    };
                    set(state => ({
                      memoryActivity: [memEntry, ...state.memoryActivity].slice(0, 10),
                    }));
                    addCognitiveEvent('memory_retrieved', payload.summary?.slice(0, 60));
                    break;
                  }
                  case 'knowledge_created':
                    set(state => ({ knowledgeGrowth: state.knowledgeGrowth + 1 }));
                    addCognitiveEvent('knowledge_matched', payload.concept?.slice(0, 60));
                    break;
                  case 'emotion_changed':
                    set({ emotionalState: payload.state ?? 'neutral', emotionalReason: payload.reason ?? '' });
                    break;
                  case 'voice_started':
                    addCognitiveEvent('listening');
                    break;
                  case 'voice_interrupted':
                    get().stopMarkSpeech();
                    addCognitiveEvent('voice_interrupted', 'inference cancelled');
                    break;
                  case 'voice_finished':
                    addCognitiveEvent('decision_made', payload.transcript?.slice(0, 60));
                    break;
                  case 'cognitive_event':
                    addCognitiveEvent(payload.step ?? 'unknown', payload.detail?.slice(0, 60));
                    break;
                  case 'reflection_complete':
                    addCognitiveEvent('reflection_complete', payload.lesson?.slice(0, 60));
                    break;
                }
                break;
              }

              // MARK speaking outside of a run — the proactive opening
              // message composed from the workspace analysis on connect
              // (MarkOpening), or MARK speaking up unprompted mid-session
              // after noticing something while idle (MarkProactive). Both
              // are pushed as a whole, already-finished message (no
              // streaming block, no currentMarkMsgId involvement — neither
              // is a run).
              case 'MarkOpening':
              case 'MarkProactive': {
                if (payload.text) {
                  set(state => ({
                    messages: [...state.messages, {
                      id: _id(),
                      role: 'mark' as const,
                      timestamp,
                      blocks: [{ type: 'text', text: payload.text }],
                      isActive: false,
                    }],
                  }));
                }
                break;
              }

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

              // ── Preview Workspace events ───────────────────────────────────
              case 'PreviewRegistered': {
                const preview: PreviewInfo = {
                  id:           payload.id    ?? payload.url ?? Math.random().toString(36).slice(2),
                  url:          payload.url   ?? '',
                  title:        payload.title ?? payload.framework ?? 'Preview',
                  framework:    payload.framework ?? 'unknown',
                  status:       (payload.status ?? 'active') as PreviewStatus,
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
                break;
              }

              case 'PreviewClosed': {
                set(state => ({
                  previews: state.previews.map(p =>
                    p.id === payload.id ? { ...p, status: 'closed' as PreviewStatus } : p
                  ),
                }));
                addTimeline(`Preview closed: ${payload.id}`);
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
        // 409 = run already active (race between voice interrupt + new turn).
        // The voice hook queues the message and retries — no error UI needed.
        const status = (err as { status?: number })?.status
          ?? ((err as { message?: string })?.message?.includes('409') ? 409 : 0);
        if (status === 409) return;
        const msg = err instanceof Error ? err.message
          : typeof err === 'object' && err !== null ? JSON.stringify(err)
          : String(err);
        console.error('sendUserMessage failed:', msg);
        set(state => ({
          messages: [...state.messages, {
            id: _id(), role: 'mark' as const, timestamp: new Date().toISOString(),
            blocks: [{ type: 'error', text: 'Could not reach the MARK server. Make sure it is running.' }],
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

  };
});
