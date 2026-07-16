# MARK AI OS — Deployment Guide

## Environments

MARK supports three deployment environments with zero code changes — only environment variables differ.

---

## 1. Local development

### Quick start

```bash
# Clone and install
git clone https://github.com/your-org/mark-ai
cd mark-ai
pnpm install

# Configure (copy and edit)
cp .env.example .env

# Start everything
pnpm dev
```

`pnpm dev` starts:
- Python MARK backend (uvicorn, hot-reload)
- React dashboard (Vite, HMR)
- WebSocket server (embedded in backend)

### Local with Ollama

```bash
# Install Ollama: https://ollama.ai
ollama pull llama3.1:8b
ollama pull qwen2.5-coder:7b

# .env
OLLAMA_HOST=http://localhost:11434
# No ACTIVE_PROVIDER needed — auto-detected
```

### Local with ChromaDB

```bash
pip install chromadb

# .env
VECTOR_PROVIDER=chroma
CHROMA_PATH=.mark_chroma
```

---

## 2. Replit

### One-click setup

1. Fork this repl on Replit.
2. Set secrets in the Secrets tab:
   - `GITHUB_TOKEN` — your GitHub token (Models API access)
   - `SESSION_SECRET` — random string for sessions
3. Click **Run** — the dashboard opens automatically at `/mark-dashboard/`.

### Replit environment variables

| Secret            | Required | Description                   |
|-------------------|----------|-------------------------------|
| `GITHUB_TOKEN`    | Yes*     | GitHub token for LLM access   |
| `SESSION_SECRET`  | Yes      | Session signing key           |
| `ACTIVE_PROVIDER` | No       | Override auto-detection       |

*Or set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` instead.

### URL routing

| Path            | Service               | Port  |
|-----------------|------------------------|-------|
| `/mark-dashboard/` | React frontend      | 18947 |
| `/mark-api/*`   | Python FastAPI backend | 18949 |

The frontend uses `window.location.origin + /mark-api` automatically — no URL configuration needed.

---

## 3. Docker / Production

### Single container

```bash
# Build
docker build -t mark-ai .

# Run with GitHub Models (simplest)
docker run -p 8000:8000 \
  -e GITHUB_TOKEN=ghp_... \
  -e SESSION_SECRET=$(openssl rand -hex 32) \
  mark-ai
```

### Full stack with Docker Compose

```bash
# Local stack (Ollama + SQLite + Chroma)
docker compose up

# Cloud stack (GitHub Models + PostgreSQL + pgvector)
GITHUB_TOKEN=ghp_... \
DATABASE_URL=postgresql://mark:mark@postgres/mark \
docker compose --profile cloud up
```

### Environment variables for production

```bash
# Provider
ACTIVE_PROVIDER=github
GITHUB_TOKEN=ghp_...

# Database (PostgreSQL)
DATABASE_PROVIDER=postgres
DATABASE_URL=postgresql://user:pass@host:5432/mark

# Vector store (pgvector)
VECTOR_PROVIDER=pgvector

# Server
PORT=8000
SESSION_SECRET=<random-32-bytes>
API_BASE_URL=https://your-domain.com
```

### Reverse proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Health check

```bash
curl https://your-domain.com/health
# → {"status": "ok", "version": "2.0.0"}

curl https://your-domain.com/diagnostics
# → full system health report
```

---

## Environment variables reference

See `.env.example` for the complete list with descriptions.

| Variable            | Default               | Description                              |
|---------------------|-----------------------|------------------------------------------|
| `ACTIVE_PROVIDER`   | auto                  | LLM provider selection                   |
| `GITHUB_TOKEN`      | —                     | GitHub Models access                     |
| `OPENAI_API_KEY`    | —                     | OpenAI API key                           |
| `ANTHROPIC_API_KEY` | —                     | Anthropic API key                        |
| `OLLAMA_HOST`       | http://localhost:11434 | Ollama server URL                       |
| `DATABASE_PROVIDER` | sqlite                | Storage backend                          |
| `DATABASE_URL`      | —                     | PostgreSQL connection string             |
| `VECTOR_PROVIDER`   | keyword               | Vector store backend                     |
| `CHROMA_PATH`       | .mark_chroma          | ChromaDB persistence directory           |
| `STORAGE_DIR`       | .mark_storage         | Local JSON storage directory             |
| `PORT`              | 8000                  | Server port                              |
| `SESSION_SECRET`    | —                     | Session signing key (required in prod)   |
| `API_BASE_URL`      | auto                  | External URL for link generation         |
| `VITE_API_URL`      | auto                  | Frontend → backend URL                   |
| `ROOT_PATH_PREFIX`  | —                     | Path prefix when behind a proxy          |
