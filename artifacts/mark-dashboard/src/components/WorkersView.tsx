import { useMarkStore } from '@/store/markStore';

export function WorkersView() {
  const { workers } = useMarkStore();

  return (
    <div className="h-full p-6 flex flex-col gap-6 bg-background overflow-y-auto">
      <div>
        <h2 className="text-2xl font-bold tracking-tight mb-2">Worker Status</h2>
        <p className="text-muted-foreground text-sm">Detailed view of individual agent worker states.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {workers.map(worker => (
          <div key={worker.name} className="bg-card border border-border/50 rounded-xl p-5 shadow-sm">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold text-lg">{worker.name}</h3>
              <span className={`text-xs px-2 py-1 rounded font-mono uppercase tracking-wider
                ${worker.status === 'running' ? 'bg-accent/20 text-accent border border-accent/30' : ''}
                ${worker.status === 'success' ? 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30' : ''}
                ${worker.status === 'failed' ? 'bg-destructive/20 text-destructive border border-destructive/30' : ''}
                ${worker.status === 'idle' ? 'bg-muted text-muted-foreground border border-border' : ''}
              `}>
                {worker.status}
              </span>
            </div>
            
            <div className="flex flex-col gap-3">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Current Task</div>
                <div className="text-sm min-h-[1.25rem]">
                  {worker.task || <span className="text-muted-foreground italic">None</span>}
                </div>
              </div>
              
              <div>
                <div className="text-xs text-muted-foreground mb-1">Last Thought</div>
                <div className="text-sm min-h-[2.5rem] italic text-foreground/80 break-words">
                  {worker.thought || <span className="text-muted-foreground not-italic">None</span>}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}