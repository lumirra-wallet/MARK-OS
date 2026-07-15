---
name: Milestone 9 Ollama Integration
description: Architecture, key decisions, and quirks for the Ollama provider and related changes in Milestone 9.
---

## Rule
OllamaProvider uses `_exclude_from_discovery = True` so `model_loader` skips it.
`ModelManager.load_ollama_models()` registers instances explicitly with correct settings.

**Why:** auto-discovery instantiates with zero args; OllamaProvider needs `model_name` + `base_url` from Settings.

**How to apply:** any new provider that needs constructor args must set `_exclude_from_discovery = True` and be registered explicitly from SmartAgent.__init__ or ModelManager.

## Key API shapes
- `OllamaProvider(model_name="llama3.1:8b", base_url="http://127.0.0.1:11434")` — id == model_name
- `OllamaModelDiscovery.list_models()` — always returns `[]` on error, never raises
- `OllamaProvider.health()` calls urllib directly (NOT via list_models) so it can distinguish "unreachable" vs "model not installed"
- `ModelManager.load_ollama_models(base_url, default_model, coding_model)` — idempotent
- Alias methods on ModelManager: `list_models()`, `load_model()`, `unload_model()`, `switch_model()`, `active_model()`

## Fallback
- `generate()` / `chat()` — Ollama down → `{"content": "Ollama server unavailable.", "finish_reason": "error"}` — never raises
- `load()` — always sets LOADED even when offline; use `health()` for real connectivity
- Console fallback: `CommandRouter.set_fallback(handler)` — handler receives `(agent, raw_str)` not `(agent, args)`

## Free-text routing
- `Console._register_commands()` sets `router.set_fallback(fallback_chat)`
- `fallback_chat` checks `agent.model_manager.active_model_id is None` → returns "Unknown command" if no model active
- Existing `test_unknown_command` passes because `tmp_agent` has no active model

## PromptBuilder extensions (Milestone 9, backward-compatible)
- New Prompt fields: `knowledge_context`, `mind_state`, `identity`, `goals` — all default to empty
- `build()` gains keyword-only args: `knowledge_snippets`, `mind_state`, `identity`, `goals`
- `render()` and `to_messages()` include them when non-empty

## MARK system prompt
`smartagent/models/prompts/mark_system_prompt.py` → `MARK_SYSTEM_PROMPT` constant

## Coding auto-routing
`_is_coding_request(message)` — frozenset of keywords → routes to `settings.ollama_coding_model` (qwen2.5-coder:7b)

## Test count
763 total (105 new in test_ollama.py). All HTTP calls mocked via `patch("urllib.request.urlopen")`.
