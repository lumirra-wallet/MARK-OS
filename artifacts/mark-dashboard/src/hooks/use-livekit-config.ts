/**
 * use-livekit-config.ts
 *
 * Fetches LiveKit connection config from the MARK API on mount.
 * Returns the URL and room name the browser needs to connect.
 *
 * Uses the store's serverUrl (derived from VITE_API_URL / window.location)
 * so it automatically works on Replit, local dev, and production deployments.
 */

import { useEffect, useState } from 'react';
import { useMarkStore } from '@/store/markStore';

export interface LiveKitConfig {
  /** WebSocket URL for the LiveKit server (may be proxied through MARK). */
  url: string;
  /** Room name to join — always 'mark-presence' unless overridden. */
  room: string;
  /** 'self-hosted' | 'cloud' — informational only. */
  mode: string;
  /** Whether LIVEKIT_API_KEY and LIVEKIT_API_SECRET are set on the server. */
  available: boolean;
}

interface UseLiveKitConfigResult {
  config: LiveKitConfig | null;
  loading: boolean;
  error: string | null;
}

export function useLiveKitConfig(): UseLiveKitConfigResult {
  const serverUrl = useMarkStore(s => s.serverUrl);
  const [config,  setConfig]  = useState<LiveKitConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchConfig() {
      try {
        const res = await fetch(`${serverUrl.replace(/\/$/, '')}/voice/config`);
        if (!res.ok) throw new Error(`voice/config returned ${res.status}`);
        const data: LiveKitConfig = await res.json();
        if (!cancelled) setConfig(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    if (serverUrl) fetchConfig();
    return () => { cancelled = true; };
  }, [serverUrl]);

  return { config, loading, error };
}
