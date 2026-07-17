---
name: Live Engineer Panel
description: Architecture and key decisions for the Live Engineer upgrade (voice, activity feed, workspace analysis, idle inspector, engineering memory)
---

## What was built

**Backend (Python)**
- `smartagent/server/workspace_analyzer.py` — pure-subprocess workspace analysis; emits `WorkspaceAnalyzed` event on WS connect via background task in `api.py`
- `smartagent/server/engineering_memory.py` — session-level `EngineeringMemory` singleton; tracks goal, milestones, blockers; module-level `engineering_memory` instance
- `smartagent/server/events.py` — added `WORKSPACE_ANALYZED`, `REASONING_STAGE`, `ACTIVITY_FEED_ENTRY`, `IDLE_SUGGESTION`, `MEMORY_UPDATED`, `NARRATION`
- `smartagent/server/api.py` — `_send_workspace_analysis()` background task on each WS connect; `_idle_inspector_loop()` coroutine fires every 30s, emits suggestions when idle > 120s
- `smartagent/engineer/agent_loop.py` — emits `REASONING_STAGE` per tool type (analyzing/writing/running/committing), initial `analyzing` at loop start, `done` at end; emits `ACTIVITY_FEED_ENTRY` after each tool call via `_activity_text()`

**Frontend (React/TypeScript)**
- `artifacts/mark-dashboard/src/components/LiveEngineerPanel.tsx` — NEW panel with five sections: VoiceBar, WorkspaceCard, ReasoningStepper, NarrationTranscript, ActivityFeed, MemorySection, IdleSuggestions; approvals embedded when pending
- `markStore.ts` — new types: `ActivityEntry`, `ReasoningStage`, `NarrationEntry`, `WorkspaceContext`, `IdleSuggestion`, `EngineeringMemoryState`; new state fields; `_addNarration()` helper; browser TTS auto-starts on WS connect; handles 6 new events
- `Dashboard.tsx` — right panel replaced from `<ApprovalsSidebar />` to `<LiveEngineerPanel />`; ApprovalsSidebar is now embedded inside LiveEngineerPanel when there are pending permissions

## Key decisions

**Why:** Browser TTS (`speechSynthesis`) auto-starts on connect — zero config, zero latency, no backend hardware needed. `isBrowserTTSFallback: true` is now the default state.

**Why:** `EngineeringMemoryState.completedMilestones` (not `milestones`) is the field name — `MemorySection` must destructure as `completedMilestones: milestones` or use the full name to avoid undefined crash.

**Why:** `_addNarration()` is defined *before* `_narrate()` in the store closure because `_narrate()` calls `_addNarration()`.

**Why:** Workspace analysis is sent only to the connecting client (`send_to` not `broadcast`) since each client triggers its own analysis on connect.

**Why:** Idle inspector runs every 30s but only emits suggestions when idle > 120s and at least one client is connected; resets `_last_notified` after emitting to prevent spam.
