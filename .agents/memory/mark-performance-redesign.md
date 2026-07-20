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
