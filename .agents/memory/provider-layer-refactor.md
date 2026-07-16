---
name: Provider Layer Refactor
description: Environment-aware frontend URL, centralised backend config, OllamaProvider LLMProvider compliance, Diagnostics page.
---

## Frontend localhost fix
`markStore.ts` serverUrl default order:
1. `localStorage.getItem('mark_server_url')`
2. `import.meta.env.VITE_API_URL`
3. `window.location.origin` (same-origin — works on Replit with no config)

`.env.example` documents `VITE_API_URL=http://localhost:8000` for local dev.
No `localhost:NNNN` hardcodes remain in `artifacts/mark-dashboard/src/`.

## Backend config module
`smartagent/server/config.py` — frozen `ServerConfig` dataclass, `cfg` singleton.
Reads: ACTIVE_PROVIDER, GITHUB_TOKEN, GITHUB_DEFAULT_MODEL, GITHUB_CODING_MODEL, OLLAMA_HOST, OLLAMA_DEFAULT_MODEL, SESSION_SECRET, VITE_API_URL, DEBUG, LOG_LEVEL.
Import: `from smartagent.server.config import cfg`.

## OllamaProvider — LLMProvider compliance
Added to `smartagent/models/providers/ollama_provider.py`:
- `embed(text)` — tries `/api/embed` (Ollama ≥0.1.26), falls back to `/api/embeddings`
- `embeddings(text)` — alias for embed()
- `list_models()` — delegates to OllamaModelDiscovery, returns [] if offline
- `stream_chat(messages)` — alias for chat_stream()
- `switch_model(name)` — updates _model_name

**Why:** OllamaProvider now fully satisfies the LLMProvider protocol, so feature code can treat GitHub and Ollama identically.

## Diagnostics
- Backend: `smartagent/server/api_diagnostics.py` → `GET /diagnostics`
- Frontend: `artifacts/mark-dashboard/src/components/DiagnosticsView.tsx`
- Nav: Stethoscope icon in Observability group, tab key `'diagnostics'`
- Checks: backend, llm_provider, embeddings, git, workspace, vector_db, memory, websocket
- Polls every 30s; manual refresh button

## Test counts
2535 passed (5 new OllamaProvider embed/alias tests replace the old NotImplementedError test).
