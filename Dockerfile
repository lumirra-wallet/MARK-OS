# ── MARK AI OS — Production Dockerfile ────────────────────────────────────────
#
# Build:
#   docker build -t mark-ai .
#
# Run (GitHub Models + SQLite):
#   docker run -p 8000:8000 -e GITHUB_TOKEN=ghp_... mark-ai
#
# Run (full cloud stack):
#   docker run -p 8000:8000 \
#     -e ACTIVE_PROVIDER=openai \
#     -e OPENAI_API_KEY=sk-... \
#     -e DATABASE_URL=postgresql://... \
#     -e VECTOR_PROVIDER=pgvector \
#     mark-ai
#
# See docs/deployment.md for full options.
# ──────────────────────────────────────────────────────────────────────────────

FROM node:22-slim AS frontend-builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy workspace config first for better layer caching
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY artifacts/mark-dashboard/package.json ./artifacts/mark-dashboard/

RUN pnpm install --frozen-lockfile --ignore-scripts

COPY artifacts/mark-dashboard ./artifacts/mark-dashboard
RUN pnpm --filter @workspace/mark-dashboard run build


# ── Python backend ─────────────────────────────────────────────────────────────

FROM python:3.11-slim AS backend

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY smartagent ./smartagent
COPY SMARTAGENT.md* ./

# Copy built frontend into static/ so the Python server can serve it
COPY --from=frontend-builder /app/artifacts/mark-dashboard/dist ./static/mark-dashboard

# Non-root user for security
RUN useradd -m -u 1000 mark
RUN chown -R mark:mark /app
USER mark

# Storage and vector DB dirs (overridable via env)
RUN mkdir -p .mark_storage .mark_chroma

EXPOSE 8000

ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV ROOT_PATH_PREFIX=""

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["python", "-m", "uvicorn", "smartagent.server.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
