import { create } from 'zustand';
import { markApi, PermissionInfo } from '@/lib/markApi';

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
}

export interface FileOperation {
  path: string;
  operation: 'created' | 'modified' | 'deleted';
}

export interface OpenFile {
  path: string;
  content: string;
  isDiff: boolean;
  originalContent?: string;
}

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

  // Actions
  setServerUrl: (url: string) => void;
  connectWebSocket: () => void;
  startRun: (goal: string, workspace: string, testCmd?: string) => Promise<void>;
  cancelRun: () => Promise<void>;
  approve: (requestId: string, always?: boolean) => Promise<void>;
  deny: (requestId: string, reason?: string) => Promise<void>;
  fetchFileContent: (path: string, isDiff?: boolean) => Promise<void>;
  closeFile: (path: string) => void;
  setActiveFileTab: (path: string | null) => void;
}

const DEFAULT_WORKERS: WorkerState[] = [
  { name: 'Research', status: 'idle' },
  { name: 'Planning', status: 'idle' },
  { name: 'Coding', status: 'idle' },
  { name: 'Testing', status: 'idle' },
  { name: 'Quality', status: 'idle' },
  { name: 'Review', status: 'idle' },
];

let ws: WebSocket | null = null;
let reconnectTimer: any = null;

export const useMarkStore = create<MarkState>((set, get) => ({
  serverUrl: localStorage.getItem('mark_server_url') || 'http://localhost:8000',
  connectionStatus: 'disconnected',
  running: false,
  goal: '',
  workspace: '',
  elapsed: 0,
  cancelRequested: false,
  
  workers: [...DEFAULT_WORKERS],
  currentWorker: null,
  
  pendingPermissions: [],
  streamingTokens: '',
  timeline: [],
  filesInRun: [],
  openFiles: [],
  activeFileTab: null,
  
  lastError: null,
  logs: [],

  setServerUrl: (url) => {
    localStorage.setItem('mark_server_url', url);
    set({ serverUrl: url });
    get().connectWebSocket();
  },

  connectWebSocket: () => {
    if (ws) {
      ws.close();
      ws = null;
    }
    
    const { serverUrl } = get();
    const wsUrl = serverUrl.replace(/^http/, 'ws') + '/ws';
    
    set({ connectionStatus: 'connecting' });
    
    try {
      ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        set({ connectionStatus: 'connected' });
        if (reconnectTimer) clearTimeout(reconnectTimer);
      };
      
      ws.onclose = () => {
        set({ connectionStatus: 'disconnected' });
        // Auto reconnect
        reconnectTimer = setTimeout(() => {
          get().connectWebSocket();
        }, 3000);
      };
      
      ws.onerror = () => {
        // Handled by close
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type !== 'event') return;
          
          const { name, payload, timestamp } = data;
          
          if (name === 'ping') return;

          // Add to raw logs
          set((state) => ({ 
            logs: [...state.logs.slice(-999), JSON.stringify(data)] 
          }));

          const addTimeline = (msg: string) => {
            set((state) => ({
              timeline: [{ id: Math.random().toString(), timestamp, type: name, message: msg }, ...state.timeline].slice(0, 200)
            }));
          };

          switch (name) {
            case 'RunStarted':
              set({ 
                running: true, 
                goal: payload.goal, 
                workspace: payload.workspace,
                elapsed: 0,
                cancelRequested: false,
                streamingTokens: '',
                timeline: [],
                filesInRun: [],
                lastError: null,
                workers: [...DEFAULT_WORKERS]
              });
              addTimeline(`Run started: ${payload.goal}`);
              break;
              
            case 'RunCompleted':
              set({ running: false, elapsed: payload.elapsed });
              addTimeline(`Run completed ${payload.success ? 'successfully' : 'with failures'}.`);
              break;
              
            case 'RunCancelled':
              set({ running: false, cancelRequested: false });
              addTimeline('Run cancelled by user.');
              break;
              
            case 'RunFailed':
              set({ running: false, lastError: payload.error });
              addTimeline(`Run failed: ${payload.error}`);
              break;
              
            case 'StatusChanged':
              set({ 
                running: payload.running,
                goal: payload.goal,
                workspace: payload.workspace,
                elapsed: payload.elapsed
              });
              break;
              
            case 'StreamingToken':
              set((state) => ({
                streamingTokens: state.streamingTokens + payload.text
              }));
              break;
              
            case 'WorkerStarted':
              if (payload.worker) {
                set((state) => ({
                  currentWorker: payload.worker,
                  workers: state.workers.map(w => w.name === payload.worker ? { ...w, status: 'running', task: payload.task } : w)
                }));
                addTimeline(`Worker started: ${payload.worker}`);
              }
              break;
              
            case 'WorkerFinished':
              if (payload.worker) {
                set((state) => ({
                  currentWorker: null,
                  workers: state.workers.map(w => w.name === payload.worker ? { ...w, status: payload.success ? 'success' : 'failed' } : w)
                }));
                addTimeline(`Worker finished: ${payload.worker}`);
              }
              break;
              
            case 'WorkerThinking':
              if (payload.worker) {
                set((state) => ({
                  workers: state.workers.map(w => w.name === payload.worker ? { ...w, thought: payload.thought } : w)
                }));
              }
              break;
              
            case 'PlanningStarted':
              addTimeline('Planning started...');
              break;
            case 'PlanningFinished':
              addTimeline('Planning finished.');
              break;
              
            case 'FileCreated':
            case 'FileModified':
            case 'FileDeleted':
              if (payload.path) {
                const op = name === 'FileCreated' ? 'created' : name === 'FileModified' ? 'modified' : 'deleted';
                set((state) => {
                  const existing = state.filesInRun.filter(f => f.path !== payload.path);
                  return { filesInRun: [...existing, { path: payload.path, operation: op }] };
                });
                addTimeline(`File ${op}: ${payload.path}`);
              }
              break;
              
            case 'TestsStarted':
              addTimeline('Running tests...');
              break;
            case 'TestsPassed':
              addTimeline('Tests passed successfully.');
              break;
            case 'TestsFailed':
              addTimeline('Tests failed.');
              break;
              
            case 'PermissionRequested':
              set((state) => ({
                pendingPermissions: [...state.pendingPermissions, payload]
              }));
              addTimeline(`Permission requested: ${payload.operation} on ${payload.path}`);
              break;
              
            case 'PermissionGranted':
            case 'PermissionDenied':
              set((state) => ({
                pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== payload.request_id)
              }));
              addTimeline(`Permission ${name === 'PermissionGranted' ? 'granted' : 'denied'}.`);
              break;
              
            case 'Error':
              set({ lastError: payload.error || payload.message });
              addTimeline(`Error: ${payload.error || payload.message}`);
              break;
          }
        } catch (err) {
          console.error("Failed to parse WS message", err);
        }
      };
    } catch (err) {
      console.error("Failed to connect WS", err);
    }
  },

  startRun: async (goal, workspace, testCmd) => {
    try {
      await markApi.startRun(get().serverUrl, goal, workspace, testCmd);
    } catch (err) {
      console.error(err);
      set({ lastError: 'Failed to start run' });
    }
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
    try {
      // Optimistically remove
      set(state => ({
        pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== requestId)
      }));
      await markApi.approve(get().serverUrl, requestId, always);
    } catch (err) {
      console.error(err);
    }
  },

  deny: async (requestId, reason) => {
    try {
      set(state => ({
        pendingPermissions: state.pendingPermissions.filter(p => p.request_id !== requestId)
      }));
      await markApi.deny(get().serverUrl, requestId, reason);
    } catch (err) {
      console.error(err);
    }
  },

  fetchFileContent: async (path, isDiff = false) => {
    try {
      const res = await markApi.getProject(get().serverUrl, path);
      if (res.content) {
        set(state => {
          const existing = state.openFiles.filter(f => f.path !== path);
          return {
            openFiles: [...existing, { path, content: res.content!, isDiff }],
            activeFileTab: path
          };
        });
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
        activeFileTab: state.activeFileTab === path ? (remaining[0]?.path || null) : state.activeFileTab
      };
    });
  },
  
  setActiveFileTab: (path) => {
    set({ activeFileTab: path });
  }
}));
