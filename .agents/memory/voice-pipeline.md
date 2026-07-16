---
name: Voice Pipeline Architecture
description: Local voice pipeline (Whisper STT + Piper TTS + OpenWakeWord) wired into MARK server and dashboard.
---

## What was built

### Python packages installed
- `faster-whisper` — STT (CPU int8 mode, no cloud)
- `openwakeword` — wake word detection (ONNX, bundled "alexa" model)
- `sounddevice` — audio capture/playback
- `numpy` — audio array processing

### Backend
- `smartagent/server/voice_manager.py` — `VoiceManager` singleton with three modes:
  - `push_to_talk`: browser records via MediaRecorder → POSTs WAV/WebM to `/voice/transcribe`
  - `continuous`: backend captures mic, energy VAD, Whisper on end of utterance
  - `wake_word`: same as continuous but gated on OpenWakeWord activation
- `_emit()` uses `asyncio.run_coroutine_threadsafe()` to broadcast from background thread
- TTS: tries Piper binary → `piper-tts` Python package → emits `VoiceTTSFallback` for browser SpeechSynthesis
- Voice endpoints added to `api.py`: `/voice/status`, `/voice/start`, `/voice/stop`, `/voice/speak`, `/voice/transcribe`, `/voice/settings`
- `app.py` lifespan now installs VoiceManager against live connection_manager at startup

### Frontend
- `VoicePanel.tsx` — mode selector, PTT hold-button with WebAudio MediaRecorder, continuous/wake-word start/stop, mute toggle, settings (Whisper model, TTS voice, speed, language, auto-submit)
- `markStore.ts` — added `voice: VoiceState`, all voice actions (`startVoice`, `stopVoice`, `toggleMute`, `updateVoiceSettings`, `transcribeAudio`, `speak`), WS handlers for all 9 voice events
- `markApi.ts` — typed wrappers for all 6 voice endpoints
- `Dashboard.tsx` — Voice tab in sidebar (mic icon, pulses green when listening), `VoiceMicIndicator` in TopNav, AnimatePresence panel transitions
- `framer-motion` installed in dashboard package

**Why:** All processing is on-device. No cloud required. TTS browser fallback (`window.speechSynthesis`) activates when `VoiceTTSFallback` event is received (Piper not installed).

**How to apply:**
- VoiceManager must be installed (event_bus, conn_manager, loop) before it can broadcast events.
- app.py lifespan handles this at startup for between-run voice events.
- During a run, VoiceManager uses the connection_manager directly (not the EventBus) so it works even when no build EventBus is active.
- For PTT transcription, browser sends raw audio as Content-Type: audio/webm (MediaRecorder default). Backend detects WAV by RIFF magic bytes or Content-Type.
