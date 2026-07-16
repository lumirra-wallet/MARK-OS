---
name: MARK Web Backend Phase 1
description: Architectural decisions and security constraints for the FastAPI+WebSocket server wrapping the MARK Python backend.
---

# MARK Web Backend — Key Decisions

## EventBus wildcard subscription
`subscribe_all(handler)` / `unsubscribe_all(handler)` added to `EventBus` in `smartagent/brain/events.py`. Uses equality (`==`) not identity (`is`) for removal — bound methods create new objects on each access so `is` never matches.

**Why:** The WebSocket broadcaster needs all events without enumerating every name. This is the only backward-compatible way without polling.

## Thread-safe event bridging
`WebSocketBroadcaster._on_event` is called synchronously from `asyncio.to_thread()` worker threads. Uses `asyncio.run_coroutine_threadsafe(manager.broadcast(...), loop)` to schedule async broadcasts without blocking the caller.

**Why:** EventBus.publish() is sync; WebSocket.send_text() is async. They live in different threads during a build.

## Module-level imports in api.py
`SmartAgent`, `SoftwareEngineer`, `Settings`, `EventBus` are imported at the top of `smartagent/server/api.py`, not inside closures. Wrapped in try/except for environments without the full stack.

**Why:** Standard `patch("smartagent.server.api.SmartAgent")` only works for module-level names; local imports inside closures are not patchable.

## Path traversal prevention
`GET /project?file=...` uses `Path.resolve()` + `is_relative_to()` for workspace containment — NOT `normpath` + `startswith`. The sibling-prefix attack (`startswith("/tmp/foo")` passes for `/tmp/foobar`) is real.

**How to apply:** Any future file-serving endpoint must follow the same pattern: resolve both paths fully, then check `is_relative_to`. Also reject absolute input paths before joining, and catch `ValueError`/`OSError` from `resolve()` (covers null bytes).

## PermissionGate asyncio.Event
`PendingPermission.__post_init__` creates the asyncio.Event lazily to allow construction outside async contexts. Phase 4 will hook this into FileEditor for actual file-write approval UI.
