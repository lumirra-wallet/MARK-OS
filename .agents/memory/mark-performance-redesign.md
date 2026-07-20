---
name: MARK Performance & Conversation Redesign
description: Architectural changes to make MARK feel like a persistent executive director — fast responses, no repeated introductions, no repeated idle findings, cached workspace analysis.
---

# MARK Performance & Conversation Redesign

## What Was Changed

Four targeted fixes to the problems described in the spec:

### 1. Repository Analysis Caching (git-HEAD based)
- `_send_workspace_analysis()` in `api.py` now gets git HEAD + branch before doing any analysis.
- If HEAD unchanged since last scan AND cached context exists → skip full filesystem walk, reuse cache.
- `conversation_store.update_workspace_git_head()` / `get_workspace_git_head()` store HEAD per workspace.
- Result: full scan only on first connect, git push, branch switch, or server restart.

### 2. Reconnect Detection (no repeated introductions)
- After workspace analysis, `_send_workspace_analysis()` checks `conversation_store.get_last_greeting_age(ws_path)`.
- If age < 30 min → send brief reconnect text ("I'm still here." / "Back — still on main.") instead of full LLM opening.
- `conversation_store.record_greeting(ws_path)` called after every opening (full or brief).
- `RECONNECT_WINDOW_SECS = 1800` (30 min) in conversation_store.py.

### 3. Idle Suggestion Repeat Detection
- `_idle_inspector_loop()` now calls `conversation_store.filter_unreported_suggestions()` before broadcasting.
- `conversation_store.mark_suggestions_reported()` called after each broadcast batch.
- Each suggestion tracked by `sha256(title:file)[:16]` key in persistent storage namespace `"reported_suggestions"`.
- TTL: 24 hours. After 24h the same finding can surface again (it may still be unresolved).
- If ALL suggestions are already reported → MARK stays quiet (resets idle timer silently).

### 4. Broader Conversational Fast Path
- Expanded engineering keyword exclusion list (added migrate, scaffold, configure, code review, etc.).
- Added `_conv_starters` list — if message starts with a conversational signal word ("what ", "how ", "thanks", "hi", etc.), it's fast-chat even if longer than 80 chars.
- Fast-chat condition: no engineering kw AND (< 80 chars OR starts with conv starter).
- Was: length < 120 AND no engineering kw. Now: more nuanced, catches longer conversational questions.

### 5. Personality / System Prompt Updates (`mark_identity.py`)
- `CHAT_SURFACE_NOTES`: Added "Never open with 'I'm MARK' unless asked", "Avoid robotic filler (Certainly!, Of course!)"
- `OPENING_SURFACE_NOTES`: Added "Do NOT introduce yourself by name — the user already knows you."
- `IDLE_SURFACE_NOTES`: Vary openers (not always "While you were away") — "Quick heads-up:", "I spotted something worth flagging:", etc.

## Spec Additions (Session 2 — Implementation Principles doc)

### 1. Implementation Principles (in code, not just docs)
Enforced through the patterns below: additive routing, no rewrites, backward-compatible.

### 2. Latency Budgets
`LATENCY_BUDGET_MS` dict in `api.py` with four measurable targets. `_check_latency(label, ms)` logs WARNING when exceeded. Budgets: voice_detection 150ms, intent_classify 50ms, memory_lookup 50ms, first_token 500ms.

### 3. Agent Activation Matrix
`ACTIVATION_MATRIX` dict in `api.py` maps route → component list. `_ACTIVATION_EXAMPLES` documents all scenario aliases. `_log_activation(route)` logs which components engage on each request.

### 4. Conversation State Machine
`ConversationState` class with five states: IDLE, LISTENING, UNDERSTANDING, RESPONDING, BACKGROUND_PROCESSING. `conv_state` field on `RunState`. `_set_conv_state()` async helper broadcasts `CONV_STATE` events. State transitions wired into every path in the `/run` handler. Key invariant enforced: state returns to IDLE after response, never waits for background workers.

### 5. Cache Invalidation Rules (5 explicit rules)
All five rules implemented: (1) HEAD change → rescan, (2) dirty-file count change → rescan, (3) branch change → rescan, (4) explicit `POST /workspace/refresh` → rescan via `invalidate_workspace_cache()`, (5) first start → rescan. `_get_git_info()` returns `(head, branch, dirty_count)` as a 3-tuple. Backward-compat: old 2-tuple entries handled.

### 6. Memory Hierarchy (4 tiers documented in conversation_store.py)
`MEMORY_TIERS` dict labels all four tiers. `memory_hierarchy_status(workspace)` returns a snapshot dict showing what each tier currently holds. Tiers: short-term (8 turns), project (300s TTL), long-term (200 turns, durable), repo-cache (git-HEAD, commit-invalidated).

### 7. Executive Decision Layer
`_executive_decision(goal)` function implements the 4-question tree. Q1 (immediate answer) bypasses classify_intent entirely for fast-path latency. Q2/Q3 run the full intent engine with timing. `LISTENING → UNDERSTANDING` state transition fires before the call. Handler re-calls `plan_response(agent, ...)` with real agent for Q2/Q3 routes.

## Files Modified

- `smartagent/server/conversation_store.py` — +89 lines: git-HEAD cache, suggestion repeat detection, greeting tracker
- `smartagent/server/api.py` — `_send_workspace_analysis()` rewritten; `_idle_inspector_loop()` updated; fast path expanded
- `smartagent/identity/mark_identity.py` — CHAT/OPENING/IDLE surface notes updated

## Key Constraints

**Why:** "Maintain existing architecture wherever possible" — all changes are additive patches, not rewrites. The full engineering pipeline is untouched; only the routing heuristic and opening/idle behaviors changed.

**How to apply:**
- The git-HEAD cache is in-memory only (per-process); survives tab refreshes but resets on server restart (intentional — restart = fresh scan).
- The reported-suggestions and greeting-time data is in persistent storage (survives restarts).
- Reconnect window is `RECONNECT_WINDOW_SECS = 1800` in conversation_store.py — adjustable.
