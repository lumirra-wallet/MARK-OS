/**
 * MARK audio worklet processor — runs on the dedicated audio render thread.
 *
 * The AudioWorkletProcessor API replaced the deprecated ScriptProcessorNode.
 * It runs in its own AudioWorkletGlobalScope thread — no main-thread jitter,
 * no dropped frames during heavy JS work (React renders, LLM streaming, etc.).
 *
 * Protocol
 * ────────
 * process() accumulates native-rate float32 samples into a 4 096-sample ring.
 * When full (~85 ms at 48 kHz, matching the old ScriptProcessorNode chunk
 * size) it transfers the ArrayBuffer to the main thread via port.postMessage
 * with zero-copy transfer semantics.  The main thread then:
 *   1. Resamples the chunk to 16 kHz (linear interpolation)
 *   2. Converts to PCM16 little-endian
 *   3. Sends the binary frame over the /ws/voice WebSocket
 *
 * Energy gating (speech vs silence) is intentionally kept in the main thread
 * so it can check the micMutedRef and WebSocket readyState without
 * cross-thread messaging overhead.
 */
class MarkAudioProcessor extends AudioWorkletProcessor {
  constructor () {
    super();
    // 4 096 samples per chunk — same as the old bufferSize on ScriptProcessorNode.
    // At 48 kHz this is ≈85 ms; at 44.1 kHz ≈93 ms.  The server VAD and
    // Whisper normalisation handle any chunk-size variation gracefully.
    this._buf = new Float32Array(4096);
    this._pos = 0;
  }

  /**
   * Called every 128 samples (~2.67 ms at 48 kHz) on the audio thread.
   * Must return true to keep the processor alive.
   */
  process (inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;

    let i = 0;
    while (i < ch.length) {
      const space = this._buf.length - this._pos;
      const copy  = Math.min(space, ch.length - i);
      this._buf.set(ch.subarray(i, i + copy), this._pos);
      this._pos += copy;
      i         += copy;

      if (this._pos >= this._buf.length) {
        // Transfer (zero-copy) — the ArrayBuffer moves to the main thread.
        // A fresh buffer is allocated immediately so the next 128-sample
        // callback never stalls waiting for the transfer to complete.
        const out   = this._buf;
        this._buf   = new Float32Array(4096);
        this._pos   = 0;
        this.port.postMessage(out.buffer, [out.buffer]);
      }
    }
    return true;
  }
}

registerProcessor('mark-audio-processor', MarkAudioProcessor);
