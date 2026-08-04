#!/usr/bin/env bash
# setup.sh — First-run and post-reset setup for MARK on Replit
# Run: bash scripts/setup.sh

set -e

echo "=== MARK Setup ==="

# 1. Install pnpm workspace packages
echo "[1/2] Installing Node packages..."
pnpm install

# 2. Install Python runtime packages
#    Use --no-cache-dir to avoid disk quota errors on the 4 MB overlay root.
echo "[2/2] Installing Python packages..."
pip install --no-cache-dir \
    fastapi "uvicorn[standard]" pydantic pydantic-settings \
    python-multipart "sqlalchemy[asyncio]" asyncpg redis motor pymongo \
    openai anthropic ollama httpx aiohttp websockets requests \
    python-dotenv pyyaml tomli tomli-w orjson aiofiles tenacity \
    "python-jose[cryptography]" "passlib[bcrypt]" cryptography pyjwt \
    numpy structlog loguru typer rich livekit livekit-api

echo ""
echo "=== Setup complete ==="
echo "Services start automatically via Replit workflows:"
echo "  - MARK Python server  →  port 18949 (artifacts/mark-api: MARK Server)"
echo "  - MARK Dashboard      →  /mark-dashboard/ (artifacts/mark-dashboard: web)"
echo "  - API Server (Node)   →  port 8080 (artifacts/api-server: API Server)"
