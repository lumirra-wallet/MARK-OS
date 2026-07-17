---
name: MARK Web LLM Routing & Provider Bugs
description: Root causes and fixes for MARK dashboard LLM failures, chat routing, and file generation issues
---

## Silent GitHub provider failure — ImportError in factory

`factory.py` `_load_github()` did:
```python
from smartagent.llm.github_provider import GitHubProvider, GITHUB_CODING_MODEL as _CM
```
`GITHUB_CODING_MODEL` is defined in `factory.py` itself, **not** in `github_provider.py`. This `ImportError` was caught by a bare `except Exception` and logged as a warning, silently leaving the model manager with no active model → instant `NoActiveModelError` on every LLM call.

**Fix:** Remove `GITHUB_CODING_MODEL as _CM` from the import; use the module-level constant already in scope.

**Why:** The constant was accidentally placed in the wrong module during the GitHub provider milestone.

## Stale state file sets invalid model name

`.mark_provider_state.json` persists the active GitHub model. A previous test set `"github_model": "my-model"` which produced HTTP 404 from the GitHub Models API. The factory reads this file and silently uses it.

**Fix:** Corrected state file to `"gpt-4.1-mini"`. Added `_KNOWN_GITHUB_MODELS` set in `_load_state()` to validate the saved model name and reset to default with a warning if unknown.

## api.py _run() chat vs code routing

After fixing provider setup, three new paths were added to `_run()`:
1. **`_is_conversational_goal(goal)`** — regex + word-count heuristic; short messages with no code verbs → chat path
2. **Chat path** — calls `_stream_llm_response(goal, _MARK_CHAT_SYSTEM, model_manager, event_bus)` in a thread; streams tokens via `event_bus.publish(STREAMING_TOKEN)`
3. **Code path** — calls `_stream_llm_response(goal, _MARK_PLAN_SYSTEM, ...)` as planning preview first, then runs `SoftwareEngineer.build()`

`SmartAgent()` creation moved to `asyncio.to_thread(_init_agent)` because it does blocking network calls (Ollama discovery, GitHub wiring) that were previously blocking the event loop.

## fast_path.py improvements

- System prompt rewritten with explicit, numbered rules for fence+filename format
- Secondary `_FENCE_NOFILE_RE` pattern added as fallback when LLM omits filename from fence line; derives filename from goal words + language extension
- Diagnostic `print()` calls → `logger.info()` so they don't appear in chat bubbles
- `success = bool(response)` instead of `bool(created)` — success when LLM responded, regardless of file output

## General api.py fixes (earlier in session)

- `ev_name = RUN_FAILED` when `result.success = False` was conflating "build finished with failures" with "exception during build". Now always `RUN_COMPLETED` for normal returns; `RUN_FAILED` reserved for exceptions.
- `CancelledError` no longer re-raised before post-run hooks (complete_job + WS broadcast)
- `ev_name`/`ev_payload`/`ticker_task`/`event_bus` initialized before `try` to guard `finally`
- Post-run hooks switched from `ev_name == RUN_COMPLETED` → `ev_payload["success"]` for success detection
