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
};
