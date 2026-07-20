#!/usr/bin/env bash
# setup_python.sh — Install MARK's Python dependencies.
# Run automatically on Replit environment boot so the mark-api server
# always starts with all packages present.
set -e

echo "[setup] Installing MARK Python dependencies..."

# Core packages needed for the server to start
pip install --quiet \
  fastapi "uvicorn[standard]" starlette pydantic pydantic-settings python-multipart \
  sqlalchemy asyncpg alembic redis aioredis \
  openai anthropic ollama \
  httpx aiohttp websockets requests \
  python-dotenv pyyaml tomli tomli-w orjson \
  structlog loguru \
  "python-jose[cryptography]" "passlib[bcrypt]" cryptography pyjwt \
  aiofiles watchdog tenacity numpy \
  typer rich motor pymongo

# Voice pipeline — STT + VAD + TTS (local, no cloud)
pip install --quiet faster-whisper silero-vad kokoro-onnx

echo "[setup] Python dependencies ready."
