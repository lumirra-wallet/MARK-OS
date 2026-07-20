/**
 * Streaming PCM16 audio player for MARK's real backend-generated voice.
 *
 * Receives raw PCM16 mono chunks — binary WebSocket frames broadcast by
 * smartagent/server/speech_runtime.py, one real Kokoro-synthesized
 * sentence per chunk — and schedules them back-to-back on a single
 * AudioContext for gapless playback. Chunk 1 starts playing while chunk 2
 * may still be in flight over the wire; nothing here waits for MARK's
 * full reply.
 *
 * stop() cuts all audio immediately (cancels scheduled + currently
 * playing sources) — this is what makes real interruption possible; see
 * use-voice.ts, which calls it the instant the backend's VAD reports the
 * owner started speaking.
 *
 * The browser here only ever plays audio it's told to play — it never
 * generates MARK's voice itself. That happens in the backend.
 */
export class SpeechPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;
  private activeSources = new Set<AudioBufferSourceNode>();
  private sampleRate: number;
  private onStateChange?: (speaking: boolean) => void;

  constructor(sampleRate: number, onStateChange?: (speaking: boolean) => void) {
    this.sampleRate = sampleRate;
    this.onStateChange = onStateChange;
  }

  private ensureContext(): AudioContext {
    if (!this.ctx || this.ctx.state === 'closed') {
      this.ctx = new AudioContext();
      this.nextStartTime = 0;
    }
    return this.ctx;
  }

  /** Enqueue one raw PCM16 mono chunk for gapless playback. */
  enqueue(pcm16: ArrayBuffer): void {
    if (pcm16.byteLength === 0) return;
    if (import.meta.env.DEV) console.debug('[MARK speech] audio chunk received:', pcm16.byteLength, 'bytes');
    const ctx = this.ensureContext();
    if (ctx.state === 'suspended') void ctx.resume();

    const int16 = new Int16Array(pcm16);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buffer = ctx.createBuffer(1, float32.length, this.sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    const startAt = Math.max(ctx.currentTime, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;

    this.activeSources.add(source);
    source.onended = () => {
      this.activeSources.delete(source);
      if (this.activeSources.size === 0) this.onStateChange?.(false);
    };
    this.onStateChange?.(true);
  }

  /** Stop everything immediately — real interruption, not a fade-out. */
  stop(): void {
    for (const source of this.activeSources) {
      source.onended = null;
      try { source.stop(); } catch { /* already stopped/ended */ }
    }
    this.activeSources.clear();
    this.nextStartTime = 0;
    this.onStateChange?.(false);
  }

  get isSpeaking(): boolean {
    return this.activeSources.size > 0;
  }
}
