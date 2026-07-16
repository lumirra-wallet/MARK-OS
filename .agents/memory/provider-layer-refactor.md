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

## GitHub as default provider
`factory._auto_default_provider()` — explicit `ACTIVE_PROVIDER` env var wins, then GITHUB_TOKEN presence → "github", else → "ollama".
`agent.py` intentionally stays conservative — only wires GitHub when ACTIVE_PROVIDER=github is explicit (not auto-detect) so unit tests are unaffected.
`ACTIVE_PROVIDER=github` is set as a Replit shared env var so the running server uses GitHub.

## Test isolation
`tests/conftest.py` has an `autouse=True` fixture that clears ACTIVE_PROVIDER and GITHUB_TOKEN before every test. Tests that need a specific provider set them explicitly inside the test body. This is required because ACTIVE_PROVIDER=github is set in the Replit environment.

## MARK Python server — Replit routing
`artifacts/mark-api/` — Python MARK server artifact, registered at path `/mark-api`, port 18949.
Run command: `cd ../.. && python -m uvicorn smartagent.server.app:app --host 0.0.0.0 --port ${PORT:-18949} --reload`
Dashboard `VITE_API_URL=/mark-api` (set in mark-dashboard artifact.toml `[services.env]`).
markStore.ts serverUrl: relative VITE_API_URL gets `window.location.origin` prepended; full URLs used directly.

## Path-prefix stripping middleware
`_StripPrefixMiddleware` in `app.py` — appended AFTER all `add_middleware`/`include_router` calls (placing it before breaks `add_middleware`). Gated by `ROOT_PATH_PREFIX` env var. Handles both HTTP and WebSocket scope types.
`mark-api` artifact.toml `[services.env]` sets `ROOT_PATH_PREFIX=/mark-api`.

## Cached provider state
`.mark_provider_state.json` caches the provider selection and overrides auto-detection. Delete it when switching defaults. The `_load_state()` `state.update(saved)` makes saved state win over auto-detect.

## Test counts
2536 passed (conftest autouse isolation fixture added).
