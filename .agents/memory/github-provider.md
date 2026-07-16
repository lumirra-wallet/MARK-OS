---
name: GitHub Models provider integration
description: GitHubProvider, ProviderFactory, REST endpoints, and frontend changes for GitHub Models as MARK's primary LLM provider.
---

## Architecture

Provider selection order:
1. `ACTIVE_PROVIDER` env var (`"github"` or `"ollama"`)
2. `.mark_provider_state.json` persisted state (set by REST API)
3. Default: `"ollama"` (backward-compatible; tests never set ACTIVE_PROVIDER)

`SmartAgent.__init__` only calls `wire_agent()` when `ACTIVE_PROVIDER=github` is explicitly set — all 2460 existing tests pass unchanged.

## New files

- `smartagent/llm/__init__.py` — package marker
- `smartagent/llm/base.py` — LLMProvider protocol + re-exports
- `smartagent/llm/github_provider.py` — `GitHubProvider(BaseModel)` using OpenAI SDK; `_exclude_from_discovery=True`
- `smartagent/llm/factory.py` — `get_active_provider()`, `get_model_for_role()`, `switch_provider()`, `wire_agent()`, `ProviderFactory`
- `smartagent/server/api_providers.py` — 8 REST endpoints mounted in app.py
- `tests/test_github_provider.py` — 70 tests, all mocked (no real network)

## Modified files

- `smartagent/models/manager/model_manager.py` — added `load_github_models()`
- `smartagent/executive/workers/ollama_mixin.py` — `_resolve_model_id()` queries factory first; returns `None` → falls back to Ollama when provider != github
- `smartagent/brain/agent.py` — calls `wire_agent()` only when `ACTIVE_PROVIDER=github`
- `smartagent/config/settings.py` — added `github_*` model fields + `active_provider`
- `smartagent/models/config/model_settings.py` — added `github_*` model fields
- `smartagent/server/app.py` — mounts `providers_router`
- `smartagent/server/api_system.py` — `GET /models` now routes to GitHub or Ollama based on active provider
- `artifacts/mark-dashboard/src/lib/markApi.ts` — added provider/LLM API methods + TypeScript types
- `artifacts/mark-dashboard/src/components/ModelsPanel.tsx` — full rewrite with provider pill selector
- `artifacts/mark-dashboard/src/components/SettingsView.tsx` — added AI Provider section with health check + generation settings

## Critical test fixture note

Tests that check `health()` with no token must set `p._token = ""` explicitly — the constructor reads `GITHUB_TOKEN` from env which IS set in this workspace.

## Factory mocker pattern

`pytest-mock` is NOT installed. Use `monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")` instead of `mocker.patch(...)`.

## Default models

- GitHub default: `gpt-4.1-mini`, coding: `gpt-4.1`, fallback: `gpt-4o-mini`
- Embedding: `text-embedding-3-small`

**Why:** gpt-4.1-mini balances cost/quality; gpt-4.1 for coding tasks; fallback for when 4.1-mini is rate-limited.
