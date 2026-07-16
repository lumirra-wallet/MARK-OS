import { useMarkStore } from '@/store/markStore';
import { ScrollArea } from '@/components/ui/scroll-area';

export function LogsView() {
  const { logs } = useMarkStore();

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="p-4 border-b border-border/50 shrink-0">
        <h2 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Raw Event Stream</h2>
      </div>
      
      <ScrollArea className="flex-1 bg-card/20 p-4">
        <div className="font-mono text-xs flex flex-col gap-2 pb-8">
          {logs.map((log, i) => {
            try {
              const parsed = JSON.parse(log);
              return (
                <div key={i} className="flex gap-4 p-2 hover:bg-muted/50 rounded transition-colors break-all">
                  <span className="text-muted-foreground shrink-0 opacity-50 w-8 text-right">{i+1}</span>
                  <div className="flex flex-col gap-1 w-full">
                    <div className="flex gap-2">
                      <span className="text-accent font-semibold">{parsed.name || 'Unknown'}</span>
                      {parsed.timestamp && <span className="text-muted-foreground">{new Date(parsed.timestamp).toISOString()}</span>}
                    </div>
                    {parsed.payload && (
                      <pre className="text-[10px] text-foreground/80 overflow-hidden whitespace-pre-wrap">
                        {JSON.stringify(parsed.payload, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              );
            } catch (e) {
              return (
                <div key={i} className="text-muted-foreground">{log}</div>
              );
            }
          })}
          
          {logs.length === 0 && (
            <div className="text-muted-foreground italic text-center p-8">No events recorded yet.</div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}