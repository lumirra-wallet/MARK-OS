import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useMarkStore } from '@/store/markStore';
import { useMemo } from 'react';

export function PerformanceView() {
  const { streamingTokens, elapsed, tokenTimestamps } = useMarkStore();

  // Real tokens/sec series — bucket actual StreamingToken arrival timestamps
  // (markStore.tokenTimestamps) into 1-second windows over the last 60s.
  const data = useMemo(() => {
    const now = Date.now();
    const windowSeconds = 60;
    const buckets = new Array(windowSeconds).fill(0);
    for (const t of tokenTimestamps) {
      const secAgo = Math.floor((now - t) / 1000);
      if (secAgo >= 0 && secAgo < windowSeconds) {
        buckets[windowSeconds - 1 - secAgo] += 1;
      }
    }
    return buckets.map((count, i) => ({
      time: i - windowSeconds,
      tokensPerSecond: count,
    }));
  }, [tokenTimestamps]);

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