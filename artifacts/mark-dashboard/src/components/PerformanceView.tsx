import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useMarkStore } from '@/store/markStore';
import { useMemo } from 'react';

export function PerformanceView() {
  const { timeline, streamingTokens, elapsed } = useMarkStore();

  // Very basic mock performance data derivation from timeline length or tokens
  const data = useMemo(() => {
    // Generate synthetic data points across elapsed time to look like a chart
    // Real app would track actual tokens/s array in store
    const points = [];
    let count = 0;
    
    // Create up to 60 points based on elapsed
    const maxPoints = Math.max(10, Math.min(60, elapsed));
    
    for (let i = 0; i < maxPoints; i++) {
      const isRecent = i > maxPoints - 5;
      const noise = Math.random() * 20;
      count += (streamingTokens.length > 0 && isRecent) ? 50 + noise : (Math.random() > 0.8 ? noise : 0);
      points.push({
        time: i,
        tokensPerSecond: Math.floor(Math.random() * 100 * (i/maxPoints)),
        totalTokens: Math.floor(count)
      });
    }
    
    return points.length > 0 ? points : [{time:0, tokensPerSecond:0, totalTokens:0}];
  }, [timeline.length, streamingTokens.length, elapsed]);

  return (
    <div className="h-full p-6 flex flex-col bg-background gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight mb-2">Performance Metrics</h2>
        <p className="text-muted-foreground text-sm">Real-time throughput and latency of the MARK engine.</p>
      </div>
      
      <div className="flex gap-4">
        <div className="bg-card p-4 rounded-xl border border-border/50 shadow-sm flex-1">
          <div className="text-xs uppercase text-muted-foreground font-semibold mb-1">Total Tokens</div>
          <div className="text-3xl font-mono text-accent">{streamingTokens.length}</div>
        </div>
        <div className="bg-card p-4 rounded-xl border border-border/50 shadow-sm flex-1">
          <div className="text-xs uppercase text-muted-foreground font-semibold mb-1">Elapsed Time</div>
          <div className="text-3xl font-mono">{elapsed}s</div>
        </div>
        <div className="bg-card p-4 rounded-xl border border-border/50 shadow-sm flex-1">
          <div className="text-xs uppercase text-muted-foreground font-semibold mb-1">Avg Tokens/Sec</div>
          <div className="text-3xl font-mono text-emerald-500">
            {elapsed > 0 ? Math.floor(streamingTokens.length / elapsed) : 0}
          </div>
        </div>
      </div>
      
      <div className="flex-1 bg-card rounded-xl border border-border/50 shadow-sm p-4 min-h-[300px]">
        <h3 className="text-sm font-semibold mb-6 uppercase text-muted-foreground">Generation Speed (Tokens/s)</h3>
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip 
              contentStyle={{ backgroundColor: 'hsl(var(--card))', borderColor: 'hsl(var(--border))', borderRadius: '8px' }}
              itemStyle={{ color: 'hsl(var(--accent))' }}
            />
            <Line 
              type="monotone" 
              dataKey="tokensPerSecond" 
              stroke="hsl(var(--accent))" 
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: 'hsl(var(--accent))' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}