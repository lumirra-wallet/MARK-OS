export interface WorkerInfo {
  name: string;
  description: string;
}

export interface StatusResponse {
  running: boolean;
  goal: string;
  workspace: string;
  elapsed: number;
}

export interface ProjectResponse {
  files: string[];
  content?: string; // If file was passed
}

export interface PermissionInfo {
  request_id: string;
  operation: string;
  path: string;
  diff?: string;
}

export const getMarkApiUrl = (baseUrl: string, path: string) => {
  // Ensure no double slashes
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
};

export const markApi = {
  getHealth: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/health'));
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ status: string; version: string }>;
  },
  
  getStatus: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/status'));
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<StatusResponse>;
  },
  
  getWorkers: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/workers'));
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ workers: WorkerInfo[]; count: number }>;
  },
  
  getProject: async (baseUrl: string, file?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/project'));
    if (file) url.searchParams.append('file', file);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<ProjectResponse>;
  },
  
  getPermissions: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/permissions'));
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ pending: PermissionInfo[] }>;
  },
  
  startRun: async (baseUrl: string, goal: string, workspace: string, testCmd?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/run'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, workspace, test_cmd: testCmd }),
    });
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ status: string; goal: string }>;
  },
  
  cancelRun: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/cancel'), {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ status: string }>;
  },
  
  approve: async (baseUrl: string, requestId: string, always?: boolean) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/approve'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, always: !!always }),
    });
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ status: string }>;
  },
  
  deny: async (baseUrl: string, requestId: string, reason?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/deny'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, reason }),
    });
    if (!res.ok) throw new Error('Network response was not ok');
    return res.json() as Promise<{ status: string }>;
  },

  // ── Voice ─────────────────────────────────────────────────────────────────

  getVoiceStatus: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/status'));
    if (!res.ok) throw new Error('Voice status failed');
    return res.json() as Promise<{
      state: string;
      running: boolean;
      settings: VoiceSettings;
    }>;
  },

  startVoice: async (baseUrl: string, mode: VoiceMode) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/start'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    if (!res.ok) throw new Error('Voice start failed');
    return res.json() as Promise<{ success: boolean; state: string }>;
  },

  stopVoice: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/stop'), {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Voice stop failed');
    return res.json() as Promise<{ success: boolean; state: string }>;
  },

  speak: async (baseUrl: string, text: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/speak'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error('TTS speak failed');
    return res.json() as Promise<{ success: boolean }>;
  },

  /**
   * Send a raw audio blob to the backend for Whisper transcription.
   * Returns the transcribed text.
   */
  transcribeAudio: async (baseUrl: string, audioBlob: Blob): Promise<string> => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/transcribe'), {
      method: 'POST',
      headers: { 'Content-Type': audioBlob.type || 'audio/wav' },
      body: audioBlob,
    });
    if (!res.ok) throw new Error('Transcription failed');
    const data = await res.json() as { text: string; duration_ms: number };
    return data.text;
  },

  updateVoiceSettings: async (baseUrl: string, settings: Partial<VoiceSettings>) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/voice/settings'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    if (!res.ok) throw new Error('Voice settings update failed');
    return res.json() as Promise<{ success: boolean; settings: VoiceSettings }>;
  },
};

// ── Voice types ──────────────────────────────────────────────────────────────

export type VoiceMode = 'push_to_talk' | 'continuous' | 'wake_word';

export type VoiceStateValue =
  | 'idle'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'error';

export interface VoiceSettings {
  enabled:        boolean;
  mode:           VoiceMode;
  wake_phrase:    string;
  whisper_model:  string;
  language:       string;
  tts_voice:      string;
  tts_speed:      number;
  muted:          boolean;
  auto_submit:    boolean;
  vad_threshold?: number;
  silence_frames?: number;
}
