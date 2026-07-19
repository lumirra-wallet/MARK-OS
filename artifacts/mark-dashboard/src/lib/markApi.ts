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

  // ── Git ───────────────────────────────────────────────────────────────────

  getGitStatus: async (baseUrl: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/status'));
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('git status failed');
    return res.json() as Promise<GitStatus>;
  },

  getGitLog: async (baseUrl: string, workspace?: string, limit = 30) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/log'));
    if (workspace) url.searchParams.set('workspace', workspace);
    url.searchParams.set('limit', String(limit));
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('git log failed');
    return res.json() as Promise<{ commits: GitCommit[]; workspace: string }>;
  },

  getGitDiff: async (baseUrl: string, ref: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/diff'));
    url.searchParams.set('ref', ref);
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('git diff failed');
    return res.json() as Promise<{ diff: string; ref: string }>;
  },

  // ── Memory ────────────────────────────────────────────────────────────────

  getMemoryFiles: async (baseUrl: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/memory'));
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('memory list failed');
    return res.json() as Promise<MemoryFilesResponse>;
  },

  getMemoryFile: async (baseUrl: string, path: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/memory/file'));
    url.searchParams.set('path', path);
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('memory file read failed');
    return res.json() as Promise<{ path: string; content: string; size: number }>;
  },

  // ── Models ────────────────────────────────────────────────────────────────

  getModels: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models'));
    if (!res.ok) throw new Error('models list failed');
    return res.json() as Promise<ModelsResponse>;
  },

  switchModel: async (baseUrl: string, model: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/switch'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (!res.ok) throw new Error('model switch failed');
    return res.json() as Promise<{ success: boolean; model: string }>;
  },

  // ── Metrics ───────────────────────────────────────────────────────────────

  getMetrics: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/metrics'));
    if (!res.ok) throw new Error('metrics failed');
    return res.json() as Promise<SystemMetrics>;
  },

  // ── Workspace ─────────────────────────────────────────────────────────────

  detectWorkspace: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/workspace/detect'));
    if (!res.ok) throw new Error('workspace detect failed');
    return res.json() as Promise<WorkspaceDetectResponse>;
  },

  getRecentWorkspaces: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/workspace/recent'));
    if (!res.ok) throw new Error('recent workspaces failed');
    return res.json() as Promise<{ recent: string[] }>;
  },

  // ── Model Router (Feature 15) ─────────────────────────────────────────────

  getModelRouter: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/router'));
    if (!res.ok) throw new Error('model router failed');
    return res.json() as Promise<{ routes: Record<string, string> }>;
  },

  updateModelRouter: async (baseUrl: string, routes: Record<string, string>) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/router'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ routes }),
    });
    if (!res.ok) throw new Error('model router update failed');
    return res.json() as Promise<{ routes: Record<string, string> }>;
  },

  resetModelRouter: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/router/reset'), { method: 'POST' });
    if (!res.ok) throw new Error('model router reset failed');
    return res.json() as Promise<{ routes: Record<string, string> }>;
  },

  // ── Enhanced Git (Feature 12) ─────────────────────────────────────────────

  getGitBranches: async (baseUrl: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/branches'));
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('git branches failed');
    return res.json() as Promise<{ branches: GitBranchInfo[]; current: string }>;
  },

  createGitBranch: async (baseUrl: string, name: string, checkout = true, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/branch'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, checkout, workspace }),
    });
    if (!res.ok) throw new Error('branch create failed');
    return res.json() as Promise<{ success: boolean; branch: string }>;
  },

  checkoutGitBranch: async (baseUrl: string, branch: string, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/checkout'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch, workspace }),
    });
    if (!res.ok) throw new Error('checkout failed');
    return res.json() as Promise<{ success: boolean; branch: string }>;
  },

  getGitStaged: async (baseUrl: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/staged'));
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('staged diff failed');
    return res.json() as Promise<{ diff: string; stat: string; files: string[] }>;
  },

  stageFiles: async (baseUrl: string, files: string[], workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/stage'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files, workspace }),
    });
    if (!res.ok) throw new Error('stage failed');
    return res.json() as Promise<{ success: boolean; stat: string }>;
  },

  unstageFiles: async (baseUrl: string, files: string[], workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/unstage'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files, workspace }),
    });
    if (!res.ok) throw new Error('unstage failed');
    return res.json() as Promise<{ success: boolean }>;
  },

  gitCommit: async (baseUrl: string, message: string, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/commit'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, workspace }),
    });
    if (!res.ok) throw new Error('commit failed');
    return res.json() as Promise<{ success: boolean; hash: string; message: string }>;
  },

  getGitStashes: async (baseUrl: string, workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/stashes'));
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('stashes failed');
    return res.json() as Promise<{ stashes: { ref: string; message: string; when: string }[] }>;
  },

  gitStash: async (baseUrl: string, message: string, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/stash'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, workspace }),
    });
    if (!res.ok) throw new Error('stash failed');
    return res.json() as Promise<{ success: boolean }>;
  },

  gitStashPop: async (baseUrl: string, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/git/stash/pop'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace }),
    });
    if (!res.ok) throw new Error('stash pop failed');
    return res.json() as Promise<{ success: boolean }>;
  },

  getGitPrSummary: async (baseUrl: string, base = 'main', workspace?: string) => {
    const url = new URL(getMarkApiUrl(baseUrl, '/git/pr-summary'));
    url.searchParams.set('base', base);
    if (workspace) url.searchParams.set('workspace', workspace);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error('PR summary failed');
    return res.json() as Promise<{ branch: string; base: string; commits: GitCommit[]; summary: string }>;
  },

  // ── Checkpoints (Feature 10) ──────────────────────────────────────────────

  createCheckpoint: async (baseUrl: string, body: {
    workspace?: string; label?: string; goal?: string;
    messages?: unknown[]; pipeline?: unknown[];
  }) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/checkpoints'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('checkpoint create failed');
    return res.json();
  },

  // ── Task graph (Feature 1) ────────────────────────────────────────────────

  planTaskGraph: async (baseUrl: string, goal: string, runId?: string, workspace?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/task-graph/plan'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, run_id: runId || '', workspace: workspace || '.' }),
    });
    if (!res.ok) throw new Error('task graph plan failed');
    return res.json();
  },

  // ── Evaluations (Feature 17) ──────────────────────────────────────────────

  submitEvaluation: async (baseUrl: string, data: Record<string, unknown>) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/evaluations'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('evaluation submit failed');
    return res.json();
  },

  // ── Provider management (NVIDIA / GitHub Models / OpenAI / Anthropic) ─────

  getProviders: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/providers'));
    if (!res.ok) throw new Error('providers fetch failed');
    return res.json() as Promise<{ providers: ProviderInfo[] }>;
  },

  getCurrentProvider: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/providers/current'));
    if (!res.ok) throw new Error('provider fetch failed');
    return res.json() as Promise<LlmSettings>;
  },

  switchProvider: async (baseUrl: string, provider: string, model?: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/providers/switch'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    });
    if (!res.ok) throw new Error('provider switch failed');
    return res.json() as Promise<LlmSettings & { success: boolean }>;
  },

  selectModel: async (baseUrl: string, model: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/select'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (!res.ok) throw new Error('model select failed');
    return res.json();
  },

  getLlmHealth: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/health/llm'));
    if (!res.ok) throw new Error('llm health failed');
    return res.json() as Promise<LlmHealth>;
  },

  getLlmSettings: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/llm/settings'));
    if (!res.ok) throw new Error('llm settings fetch failed');
    return res.json() as Promise<LlmSettings>;
  },

  updateLlmSettings: async (baseUrl: string, updates: Partial<LlmSettings>) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/llm/settings'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error('llm settings update failed');
    return res.json() as Promise<LlmSettings>;
  },

  getGitHubModels: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/models/github'));
    if (!res.ok) throw new Error('github models fetch failed');
    return res.json() as Promise<{ models: GitHubModelInfo[]; error?: string }>;
  },

  // ── MARK's own presence — self-state and identity ─────────────────────────

  getSelfState: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/self-state'));
    if (!res.ok) throw new Error('self-state fetch failed');
    return res.json() as Promise<SelfState>;
  },

  getIdentity: async (baseUrl: string) => {
    const res = await fetch(getMarkApiUrl(baseUrl, '/identity'));
    if (!res.ok) throw new Error('identity fetch failed');
    return res.json() as Promise<IdentityProfile>;
  },
};

// ── Enhanced git types ────────────────────────────────────────────────────────

export interface GitBranchInfo {
  name: string; hash: string; subject: string; current: boolean;
}

// ── System types ─────────────────────────────────────────────────────────────

export interface GitStatus {
  workspace: string;
  branch:    string;
  ahead:     number;
  behind:    number;
  clean:     boolean;
  changes:   { status: string; path: string }[];
  error?:    string;
}

export interface GitCommit {
  hash:    string;
  short:   string;
  message: string;
  author:  string;
  email:   string;
  date:    string;
  refs:    string;
}

export interface MemoryFilesResponse {
  files:       { name: string; path: string; size: number; preview: string }[];
  workspace:   string;
  memory_dir:  string;
  exists:      boolean;
}

export interface ModelInfo {
  name:     string;
  id:       string;
  size_gb:  number;
  modified: string;
  family:   string;
  params:   string;
  context?: number;
  provider: string;
}

export interface ModelsResponse {
  models:   ModelInfo[];
  active:   string;
  provider: string;
  error?:   string;
}

export interface ProviderInfo {
  id:               string;
  name:             string;
  description:      string;
  base_url:         string;
  requires_token:   boolean;
  token_env:        string | null;
  capabilities:     string[];
  default_model:    string;
  token_present?:   boolean;
  available:        boolean;
  active:           boolean;
}

export interface LlmSettings {
  provider:            string;
  model:               string;
  coding_model:        string;
  temperature:         number;
  max_tokens:          number;
  streaming:           boolean;
  github_available:    boolean;
  nvidia_available:    boolean;
  openai_available:    boolean;
  anthropic_available: boolean;
}

export interface LlmHealth {
  provider:    string;
  model:       string;
  latency_ms:  number | null;
  available:   boolean;
  token_valid: boolean;
  streaming:   boolean;
  error:       string | null;
}

export interface GitHubModelInfo {
  id:             string;
  family:         string;
  context:        number;
  supports_tools: boolean;
}

export interface SystemMetrics {
  cpu_pct:      number;
  mem_pct:      number;
  mem_used_mb:  number;
  mem_total_mb: number;
  disk_pct:     number;
  disk_free_gb: number;
  error?:       string;
}

export interface WorkspaceDetectResponse {
  workspace:  string;
  cwd:        string;
  git_root:   string | null;
  candidates: string[];
  recent:     string[];
}

