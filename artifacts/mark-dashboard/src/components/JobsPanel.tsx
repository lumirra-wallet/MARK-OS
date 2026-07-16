/**
 * Jobs Panel — Feature 14 (Long Running Jobs).
 *
 * Lists all MARK jobs (current and historical). Supports pause, resume, cancel.
 */
import React, { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useMarkStore } from '@/store/markStore';
import {
  Briefcase, Play, Pause, X, RefreshCw, CheckCircle,
  XCircle, Clock, Loader2, AlertTriangle,
} from 'lucide-react';

interface Job {
  id:           string;
  goal:         string;
  workspace:    string;
  status:       'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
  created_at:   string;
  updated_at:   string;
  paused:       boolean;
  progress:     number;
  current_step: string;
  result:       unknown | null;
}

const STATUS_ICON: Record<string, React.ReactElement> = {
  running:   <Loader2    className="w-3.5 h-3.5 text-blue-400 animate-spin" />,
  paused:    <Pause      className="w-3.5 h-3.5 text-amber-400" />,
  completed: <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />,
  failed:    <XCircle    className="w-3.5 h-3.5 text-red-400" />,
  cancelled: <X          className="w-3.5 h-3.5 text-muted-foreground" />,
};

export function JobsPanel() {
  const { serverUrl } = useMarkStore();
  const [jobs,    setJobs]    = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetch(`${serverUrl}/jobs`).then(r => r.json());
      setJobs(data.jobs || []);
    } catch { /* offline */ }
    setLoading(false);
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [serverUrl]);

  const action = async (id: string, act: 'pause' | 'resume') => {
    await fetch(`${serverUrl}/jobs/${id}/${act}`, { method: 'POST' });
    load();
  };

  const cancel = async (id: string) => {
    if (!confirm('Cancel this job?')) return;
    await fetch(`${serverUrl}/jobs/${id}`, { method: 'DELETE' });
    load();
  };

  return (
    <div className="flex flex-col h-full text-sm">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-accent" />
          <span className="font-semibold">Long Running Jobs</span>
          <span className="text-xs text-muted-foreground">({jobs.length})</span>
        </div>
        <button onClick={load} className="p-1 hover:bg-muted/40 rounded">
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
            <Briefcase className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs">No jobs yet. Start a run to create one.</p>
          </div>
        ) : (
          <div className="space-y-0">
            {jobs.map(job => (
              <div key={job.id} className="px-4 py-3 border-b border-border/30 hover:bg-muted/10 transition-colors">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 shrink-0">
                    {STATUS_ICON[job.status] || <Clock className="w-3.5 h-3.5 text-muted-foreground" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-xs truncate">{job.goal}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {job.workspace} · {new Date(job.created_at).toLocaleString()}
                    </p>
                    {job.status === 'running' && (
                      <div className="mt-1.5">
                        <div className="flex justify-between text-[10px] text-muted-foreground mb-0.5">
                          <span>{job.current_step}</span>
                          <span>{job.progress}%</span>
                        </div>
                        <div className="h-1 bg-muted/30 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-accent rounded-full transition-all"
                            style={{ width: `${job.progress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {job.status === 'paused' && (
                      <p className="text-[10px] text-amber-400/80 mt-0.5 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" /> Paused · click Resume to continue
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {job.status === 'running' && (
                      <button onClick={() => action(job.id, 'pause')}
                        className="p-1 hover:bg-muted/40 rounded text-amber-400" title="Pause">
                        <Pause className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {job.status === 'paused' && (
                      <button onClick={() => action(job.id, 'resume')}
                        className="p-1 hover:bg-muted/40 rounded text-emerald-400" title="Resume">
                        <Play className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {['running', 'paused'].includes(job.status) && (
                      <button onClick={() => cancel(job.id)}
                        className="p-1 hover:bg-muted/40 rounded text-red-400" title="Cancel">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
