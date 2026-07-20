---
name: MARK Web Voice Pipeline & Persistent Server
description: Voice pipeline wiring, watchdog supervisor, and dependency bootstrapping for the MARK AI OS on Replit.
---

## Persistent Server
- `smartagent/server/watchdog.py` — Python supervisor that runs uvicorn as a child process and restarts it within 3s on any crash.
- `artifacts/mark-api/package.json` dev script: `pip install -q -r requirements.minimal.txt && python -m smartagent.server.watchdog`
- `requirements.minimal.txt` at repo root — the reliable subset of requirements.txt that installs cleanly on Replit (excludes chromadb, pinecone-client, sentence-transformers which are blocked/unavailable).

**Why:** Replit environment resets lose pip packages. Watchdog ensures MARK's "continuous presence" — server never stays down.

**How to apply:** Watchdog env vars: `MARK_WATCHDOG_BACKOFF` (default 3s), `MARK_WATCHDOG_MAX_RESTARTS` (default 20/hour).

## Voice Pipeline
- STT: Faster-Whisper (`base.en`, CPU int8) — `smartagent/server/voice_pipeline.py` (streaming+VAD) + `smartagent/voice/speech_to_text.py` (one-shot)
- VAD: Silero VAD v6.2.1 — `load_silero_vad()` and `VADIterator` API confirmed working at this version
- TTS: Kokoro-ONNX (af_bella voice, 82M params) — `smartagent/server/tts_engine.py` + `smartagent/voice/text_to_speech.py`
- Streaming path: `speech_runtime.py` buffers LLM tokens into sentences → Kokoro synthesis → PCM16 bytes broadcast over `/ws`
- Browser: `use-voice.ts` captures mic at 16kHz, streams PCM16 binary frames to `/ws/voice`; no browser SpeechRecognition or speechSynthesis on primary path

## Windows → Linux Migration
- Removed `scriptShell: "C:\\Program Files\\Git\\bin\\bash.exe"` from `pnpm-workspace.yaml` — was causing ENOENT on all workflow starts
- Removed Windows OS conditional from mark-api dev script
- Windows-only npm packages remain in devDeps but are overridden to `-` in pnpm-workspace.yaml — harmless on Linux

## WebGL / PresenceEngine
- `PresenceEngine.tsx` line ~189: `new THREE.WebGLRenderer()` wrapped in try/catch — Replit preview has no GPU; dashboard loads cleanly with blank center instead of crashing the whole app.
