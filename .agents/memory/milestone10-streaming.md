---
name: Milestone 10 Streaming Upgrade
description: Architecture decisions, patterns, and gotchas for the M10 streaming / performance / optimisation milestone.
---

# Milestone 10 — Streaming Upgrade

## What was built
- `OllamaProvider.generate_stream()` / `chat_stream()` — send `stream: true` to `/api/chat`, yield NDJSON tokens
- `OllamaProvider.stream()` delegates to `generate_stream()` for backward compatibility
- `BaseModel` gains concrete (non-abstract) `generate_stream()` and `chat_stream()` defaults — both delegate to `stream()` — so **all prior providers need zero changes**
- `ModelManager.generate_stream()` / `chat_stream()` — mirror the `generate()` / `stream()` interface
- `ModelManager.switch()` — lazy unload of previous model when `settings.lazy_model_loading=True`
- `ModelManager.load_ollama_models()` — passes `warmup_enabled` from settings to each provider instance
- `OllamaProvider._warmup()` — called from `load()` when `warmup_enabled=True`; silently skipped if server unreachable
- `ModelSettings` — four new fields: `warmup_enabled=True`, `cache_prompts=True`, `show_generation_stats=False`, `lazy_model_loading=False`
- `commands/models.py` — fully rewritten `_send_to_model()`: spinner, streaming to stdout, optional stats, prompt cache
- `tests/test_ollama.py` — ~60 new tests (M10 milestone classes)

## Key decisions

**No new abstract methods on BaseModel**
`generate_stream()` and `chat_stream()` are concrete defaults — prior providers (MockModelProvider) gain them for free without modification and all pre-M10 tests pass unchanged.

**Why:** Adding abstract methods would require touching every existing provider. The delegation to `stream()` preserves backward compat perfectly.

**Streaming prints to stdout, returns ""**
The console streaming path writes tokens directly to `sys.stdout` and returns `""` so the REPL doesn't double-print. The REPL's `print(response)` on `""` is a no-op.

**Why:** REPL architecture assumes handler returns a string → REPL prints it. The streaming path breaks this assumption intentionally and cleanly.

**`tmp_agent` fixture sets `streaming_enabled=False`**
All pre-M10 tests use the non-streaming path (return-value assertions). The new `streaming_agent` fixture inside `TestStreamingConsole` explicitly sets it to `True`.

**Why:** If streaming is on by default, all existing chat tests fail because the handler returns `""` instead of the response text.

**Prompt cache is bounded at 16 entries (LRU-on-insert)**
Cache key = MD5 of `(identity, mind_state, goals)`. Only static context is cached; knowledge snippets and memory hits are always fresh.

**Why:** Static context changes rarely (identity, active goals). Knowledge snippets change per query so must not be cached.

**Warmup on `load()`, not on `switch()`**
`OllamaProvider.load()` calls `_warmup()` when enabled. `ModelManager.switch()` calls `load()` internally, so warmup happens correctly.

**Why:** `load()` is the single authoritative lifecycle hook. Putting warmup there avoids duplication.

**Lazy loading unloads previous model in `switch()`**
After the new model is loaded and `_active_model_id` is updated, the previous provider's `shutdown()` is called if `lazy_model_loading=True`.

**Why:** Keeps only one model resident in memory. Off by default to preserve existing behavior.

## Gotchas

- The streaming mock in tests must return an iterable-by-line context manager (not the `resp.read()` mock used by non-streaming tests). Use `_make_stream_response(tokens)` helper.
- `_stream_messages()` is the single internal streaming implementation shared by both `generate_stream()` and `chat_stream()` on the provider — don't duplicate NDJSON parsing.
- Stats display requires `t_first_token is not None` guard (no stats if no tokens were generated, e.g. server down).

## Test classes added
- `TestOllamaProviderGenerateStream`
- `TestOllamaProviderChatStream`
- `TestBaseModelStreamDefaults`
- `TestModelManagerStreaming`
- `TestWarmup`
- `TestLazyLoading`
- `TestModelSettings10`
- `TestPromptCache`
- `TestStreamingConsole`
- `TestBackwardCompatibility`
