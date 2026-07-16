import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { markApi } from '@/lib/markApi';
import { useMarkStore } from '@/store/markStore';
import { useState } from 'react';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';

export function SettingsView() {
  const { serverUrl, setServerUrl } = useMarkStore();
  const [testUrl, setTestUrl] = useState(serverUrl);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<'success' | 'error' | null>(null);
  const [testMessage, setTestMessage] = useState('');

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await markApi.getHealth(testUrl);
      setTestResult('success');
      setTestMessage(`Connected to MARK API v${res.version || 'unknown'}`);
      setServerUrl(testUrl);
    } catch (err: any) {
      setTestResult('error');
      setTestMessage(err.message || 'Failed to connect');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="h-full p-8 bg-background max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold tracking-tight mb-6">Settings</h2>
      
      <div className="space-y-6">
        <div className="space-y-4 bg-card p-6 rounded-xl border border-border/50 shadow-sm">
          <div>
            <h3 className="text-lg font-semibold mb-1">MARK Server Configuration</h3>
            <p className="text-sm text-muted-foreground">
              Configure the WebSocket and REST API endpoint for the local MARK daemon.
            </p>
          </div>
          
          <div className="grid gap-2">
            <Label htmlFor="serverUrl">API Base URL</Label>
            <div className="flex gap-2">
              <Input 
                id="serverUrl" 
                value={testUrl} 
                onChange={(e) => setTestUrl(e.target.value)} 
                className="font-mono text-sm"
              />
              <Button onClick={handleTest} disabled={testing} className="min-w-[100px]">
                {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Test & Save'}
              </Button>
            </div>
            
            {testResult && (
              <div className={`text-sm mt-2 flex items-center gap-2 p-3 rounded-md border ${testResult === 'success' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600' : 'bg-destructive/10 border-destructive/30 text-destructive'}`}>
                {testResult === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                {testMessage}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}