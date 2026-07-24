# MARK — AI Operating System

MARK is a persistent cognitive AI — not a chatbot, not a coding tool. He is a single intelligence that lives continuously, remembers everything, listens to your voice, speaks back, and grows smarter over time.

> **"MARK is the persistent intelligence. AI models are reasoning instruments MARK may choose to consult, but they never define his identity, memory, personality, or cognition. MARK owns his own mind; external models only extend his capabilities when necessary."**

---

## How to Run

### Start Everything
The workspace uses pnpm. All three services start automatically via Replit workflows:

| Service | Command | Port |
|---|---|---|
| **MARK Python Server** | `pnpm --filter @workspace/mark-api run dev` | 18949 |
| **MARK Dashboard** | `pnpm --filter @workspace/mark-dashboard run dev` | auto |
| **API Server (Node)** | `pnpm --filter @workspace/api-server run dev` | 8080 |

### First Run / After Environment Reset
Run the setup script to install all dependencies:
```bash
bash scripts/setup.sh
```

This installs pnpm packages and the core Python packages. The `requirements.minimal.txt` auto-install in the dev script may fail with a disk quota error (the `/` overlay is 4 MB); the setup script works around this by using `--no-cache-dir`.

If you need to install Python packages manually:
```bash
pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings \
    python-multipart sqlalchemy asyncpg redis motor pymongo \
    openai anthropic ollama httpx aiohttp websockets requests \
    python-dotenv pyyaml tomli tomli-w orjson aiofiles tenacity \
    python-jose[cryptography] passlib[bcrypt] cryptography pyjwt \
    numpy structlog loguru typer rich livekit livekit-api
```

### Ollama (local LLM)
MARK's primary intelligence is **llama3.2:3b via Ollama**. Set `OLLAMA_HOST` in Replit Secrets to point to your Ollama server (e.g. `http://your-server:11434`). Without it, MARK falls back to NVIDIA/GitHub models.

---

## Architecture

```
MARK Brain (single intelligence)
├── Identity & Personality    smartagent/identity/mark_identity.py
├── Memory                    smartagent/memory/memory_manager.py
├── Voice Pipeline            smartagent/server/voice_pipeline.py (STT)
│                             smartagent/server/tts_engine.py     (TTS)
│                             smartagent/server/speech_runtime.py (streaming)
├── Executive Reasoning       smartagent/executive/
├── Engineering Workers       smartagent/engineer/
└── Web API                   smartagent/server/app.py (FastAPI)

Dashboard (React + Vite)      artifacts/mark-dashboard/
Persistent Server (watchdog)  smartagent/server/watchdog.py
```

## Voice System

MARK's voice runs **100% locally** — no browser speech API, no cloud TTS:

- **STT**: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (base.en, CPU int8) — your microphone audio streams from the browser over `/ws/voice`, VAD detects speech boundaries, Whisper transcribes in real-time
- **VAD**: [Silero VAD](https://github.com/snakers4/silero-vad) — detects when you start/stop speaking for natural interruption
- **TTS**: [Kokoro-ONNX](https://github.com/thewh1teagle/kokoro-onnx) (af_bella voice, 82M params) — synthesizes MARK's replies as PCM16 audio, streamed back over `/ws`

To activate: click the **microphone button** on MARK's home screen (browser asks for mic permission once).

## Persistent Server

The MARK Python server never stays down. `smartagent/server/watchdog.py` supervises uvicorn and restarts it automatically within 3 seconds if it crashes. This is MARK's "continuous presence" — he is always available.

## Secrets

| Secret | Purpose |
|---|---|
| `OLLAMA_HOST` | URL of your Ollama server (e.g. `http://192.168.1.x:11434`) |
| `MARK_MODEL` | Override model name (default: `llama3.2:3b`) |
| `NVIDIA_API_KEY` | NVIDIA cloud fallback when Ollama unreachable |
| `GITHUB_TOKEN` | GitHub Models provider |
| `ACTIVE_PROVIDER` | Force a provider (`ollama`, `nvidia`, `github`, `openai`, `anthropic`) |
| `SESSION_SECRET` | Web session signing key |
| `MONGODB_URI` | MongoDB for persistent memory (optional) |

## User Preferences

- MARK is the intelligence — external AI models (Claude, GPT, etc.) are tools MARK may consult, never MARK's identity
- Voice-first: microphone input + local TTS output, never browser speechSynthesis as primary
- Server must never stay down — watchdog auto-restarts on crash
- All Python dependencies auto-install on server start via `requirements.minimal.txt`
