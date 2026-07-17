---
name: Production Architecture v3
description: All 15 production-readiness spec tasks — storage/vector/provider abstractions, Docker, docs, unified launcher.
---

## What was built

### Storage abstraction (Task 4)
`smartagent/storage/` — `StorageProvider` ABC, `LocalStorageProvider` (JSON files), `PostgresStorageProvider` (SQLAlchemy).
Factory at `smartagent/storage/factory.py` — defaults to `sqlite`; selects `postgres` ONLY when `DATABASE_PROVIDER=postgres` is explicit.
**Why:** Replit auto-sets `DATABASE_URL` to its built-in Postgres; auto-selecting postgres on DATABASE_URL presence would break default deployments.

### Vector abstraction (Task 5)
`smartagent/vector/` — `VectorProvider` ABC, `KeywordProvider` (TF-IDF, default), `ChromaProvider`, `PGVectorProvider`.
Factory at `smartagent/vector/factory.py` — defaults to `keyword`; selects `chroma`/`pgvector` via `VECTOR_PROVIDER`.

### New LLM providers (Task 3)
`smartagent/llm/openai_provider.py` — full OpenAI chat/stream/embed/list_models/health.
`smartagent/llm/anthropic_provider.py` — full Anthropic chat/stream; embed falls back to OpenAI text-embedding-3-small.
`_VALID_PROVIDERS = {"github","ollama","openai","anthropic"}` in factory.py.
Auto-detect order: ACTIVE_PROVIDER env → GITHUB_TOKEN → OPENAI_API_KEY → ANTHROPIC_API_KEY → ollama.

### Localhost removal (Task 2)
All `http://127.0.0.1:11434` replaced with `os.environ.get("OLLAMA_HOST", "http://localhost:11434")`.
`Settings.__post_init__` resolves `ollama_base_url` from `OLLAMA_HOST` env var.
`app.py` startup log uses `API_BASE_URL` env var instead of localhost.

### Health dashboard expansion (Task 10)
`/diagnostics` now checks 10 subsystems: backend, database, llm_provider, embeddings, vector_db, git, workspace, memory, websocket, system(CPU/RAM).
`DiagnosticsView.tsx` added summary cards (provider/model, CPU bar, RAM bar, storage type) + usage visualizations.

### Auto-workspace detection (Task 11)
`app.py` lifespan auto-runs `git rev-parse --show-toplevel` on startup; sets `_api._state.workspace` if found.

### Unified launcher (Task 1)
Root `package.json` `dev` script uses `concurrently` to start both the Python backend and React frontend.

### Docker (Task 9)
`Dockerfile` — multi-stage (node frontend builder + python backend). Serves frontend from `/static/mark-dashboard`.
`docker-compose.yml` — local stack (ollama + SQLite) and cloud profile (postgres+pgvector).

### Documentation (Task 15)
`docs/architecture.md`, `docs/providers.md`, `docs/storage.md`, `docs/deployment.md`.
`.env.example` — comprehensive with all env vars documented.

## Test count
2840 passed, 0 failed (103 new tests in test_diagnostics.py).

## Key constraints
- `DATABASE_PROVIDER` must be EXPLICITLY set to "postgres" to activate PostgreSQL — never auto-detect from DATABASE_URL alone (Replit sets DATABASE_URL automatically).
- `VECTOR_PROVIDER` defaults to "keyword" (no deps) — not "chroma" even if chromadb is installed, to avoid accidental heavy deps.
- "anthropic" is now a valid provider in `switch_provider` — tests that test "invalid provider" must use a different invalid name (e.g. "gemini").
- `Settings.ollama_base_url` is empty by default, resolved in `__post_init__` via `OLLAMA_HOST`.
