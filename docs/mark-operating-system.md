# MARK — AI Operating System Architecture

This document is the authoritative statement of what MARK *is*, written because
the prior architecture docs (`ARCHITECTURE.md`, `docs/architecture.md`)
describe MARK as "a full-stack AI engineering assistant" — framing that leads
every implementation decision back toward "another coding agent." That framing
is wrong. This document replaces it as the primary mental model. If anything
in this repo's other docs conflicts with this one, this one wins.

## Mission

**MARK is not an AI coding agent. MARK is an AI Operating System.**

Coding agents — the Engineer, the Debugger, the QA worker — are applications
that run *inside* MARK, the same way Word and Excel run inside Windows.
Windows doesn't edit documents; it schedules processes, manages permissions,
and supervises applications. MARK does the same thing for a software
engineering organization of one: it plans, delegates, supervises, reviews, and
reports — it does not write the code itself except in the narrow case where
there's no meaningful specialist to delegate to.

The user only ever talks to MARK — the Executive. Never to a worker.

## The hierarchy

```
                        YOU
                         │
                         ▼
              MARK — Operating System
                         │
        ┌────────────────┼────────────────┐
        │                │                │
  Executive Brain   Worker Manager    Memory / Knowledge
  (plan, review,    (scheduler,       (persistent context,
   synthesize)        permissions)     project history)
        │                │
        └────────┬───────┘
                 ▼
           Worker Pool
   ┌──────────┬──────────┬──────────┐
   │ Engineer │ Research │ Debugger │
   ├──────────┼──────────┼──────────┤
   │    QA    │ Security │   Docs   │
   ├──────────┼──────────┼──────────┤
   │   Git    │ Reviewer │ Preview  │
   └──────────┴──────────┴──────────┘
```

MARK never becomes one of those workers. MARK manages them — the same
distinction as a CEO vs. an engineering manager vs. individual developers, or
an OS kernel vs. the applications it schedules.

## Core principles

**1. MARK is the only voice.** Workers produce structured internal results —
task complete, tests passed, found bug, need permission, need more context —
never free-text chat directed at the user. MARK reads those results and
composes what the user actually sees and hears. The user should never
directly witness `Engineer: ...` / `QA: ...` / `Reviewer: ...` — only MARK
talking about what they did.

**2. Workers never own the workspace.** Every worker gets exactly the
permission scope its current task needs — specific files, specific tools —
and nothing more. When the task ends, the scope is revoked. The next worker
gets a scope computed fresh for its own task. No worker holds standing access
to the whole repository.

**3. One message, every surface.** Whatever MARK composes to say to the user
is the *only* source of truth — the same string appears in chat, in the
timeline, and gets spoken aloud. There is no separate "narration" that
paraphrases the chat text, and no raw log dump that contradicts what was
spoken. One source, multiple renderings, never regenerated per surface.

**4. The interface reflects supervision, not conversation.** The dashboard
should feel like watching an engineering organization work — a persistent
operations view of who's doing what, what's been decided, what's running —
not a chat window with some panels bolted on the side.

## Current implementation — what's already true

This isn't purely aspirational; a real, working Executive layer already
exists and should be extended, not rebuilt:

| Principle | Where it lives today |
|---|---|
| MARK is the only voice | `smartagent/engineer/dev_pipeline.py`'s `_synthesize_milestone_summary()` / `_synthesize_final_summary()` — one LLM call per milestone composes the *only* text that reaches chat (`_emit()`). Internal phase detail (planning, testing, reviewing, committing) goes through `_activity()` → `ActivityFeedEntry`, Timeline-only, never chat. |
| Workers report structured results | `WorkersView.tsx`/`WorkerState` render a status chip (`idle/running/success/failed`) + task label — never a free-text bubble. Confirmed: no code path today builds an "Engineer: ..." chat message. |
| Scoped, revocable permissions | `smartagent/engineer/agent_tools.py`'s `execute_tool(..., allowed_paths=...)` — `DevPipeline` computes `allowed_paths` per milestone from that milestone's own declared file targets (`extract_file_targets()`) before dispatching; write/rename/delete calls outside that scope are rejected. Scope is recomputed fresh per milestone. |
| One message, every surface | `DevPipeline._speak()` publishes `ServerEvents.NARRATION` with the *exact same string* `_emit()` just sent to chat — not a re-generated paraphrase. The frontend's existing `Narration` WS handler (`markStore.ts`) pipes that string to the narration transcript *and* to the active TTS provider (Kokoro by default). |
| Supervision-style status view | `ProjectInspector.tsx` — running apps, branch, commits, files changed, test results, worker status, performance, active model, all in one composite view rather than scattered across chat. |

## Where the current build still doesn't match the vision

Being direct about the gaps, because papering over them defeats the point of
writing this down:

**1. The Worker Manager isn't real yet — it's narrative, not dispatch.**
`DevPipeline` calls `run_agent_loop()` once per milestone as a single generic
executor; there's no `Engineer`/`QA`/`Reviewer`/`Security`/`Docs` worker with
its own system prompt, tool scope, and identity being *dispatched* by a
scheduler. The org chart in this doc is currently true in the chat text MARK
composes ("I've assigned the Engineer...") but not in the code path
underneath it. A separate, well-shaped `smartagent/executive/` framework
(Orchestrator → Scheduler → named Worker classes) already exists in this repo
and already has the right shape — it's just disconnected from the live
dashboard path (`api.py` → `dev_pipeline.py`). Closing this gap means wiring
real dispatch to named workers, not adding more narrative flavor text.

**2. The UI still fundamentally works like Cursor/VS Code/ChatGPT.**
`Dashboard.tsx` is a 23-icon tab rail where one view shows at a time. The M4
pass grouped those tabs into labeled sections (Active Run, Active Workers,
Timeline, Checkpoints, Git, Live Preview, Project Inspector, ...), which
improved organization but did **not** remove the tab-switching model itself —
that's the actual thing that needs to go. The target is a persistent
Engineering Workspace: MARK's conversation is always the primary, central
view; Active Workers / Engineering Timeline / Live Preview / Project
Inspector are simultaneously visible (mission-control style, closer to
Replit/Linear than Cursor); secondary/advanced views (raw Git detail, Files,
Logs, Terminal, Models, Tools, Codebase Index, Evaluation, Diagnostics, Jobs,
Task Graph, Pipeline Graph, Settings) move to a secondary access pattern
instead of living in the same permanent rail as the primary panels.

**3. Narration cadence is coarser than "continuous."** Today MARK speaks
once per milestone (a deliberate choice made earlier this project — batched
executive summaries, not a live token-by-token stream). The vision in this
doc describes something busier than that: "I'm inspecting your repository" →
five seconds later "I found a React frontend and a FastAPI backend" → later
"I'm assigning the Engineer..." — several short MARK-authored updates across
one milestone, not one paragraph at the end of it. This is a middle ground to
design deliberately: more frequent checkpoints (on analysis, on assignment,
on each worker's completion) than today, but still MARK's own composed
sentences — never a return to raw per-tool-call narration.

**4. No Security or Docs worker exists as a concept.** The current roster
(`DEFAULT_WORKERS` in `markStore.ts`: Research, Planning, Coding, Testing,
Quality, Review) doesn't include Security or Docs, and "Debugger" is folded
into Testing/Quality rather than being its own specialist. Formalizing the
Worker Manager (gap #1) is the right place to fix this, since it means
deciding each worker's actual scope and system prompt, not just adding two
more labels to a UI list.

## Recommended sequencing

Architecture first, per the instruction that prompted this document — the
UI should be built to reflect a real dispatch model, not the other way
around:

1. **Formalize the Worker Manager.** Give `DevPipeline` real named-worker
   dispatch (distinct prompt + tool scope per role: Engineer, QA, Reviewer,
   Git, Security, Docs, Research, Preview) instead of one generic executor
   loop wearing different narrative labels. This is what makes principles
   1–2 above literally true in the code, not just in what MARK says about
   itself.
2. **Redesign the dashboard around a persistent Engineering Workspace.**
   Remove the primary tab/sidebar navigation model; build the mission-control
   layout (MARK conversation + Active Workers + Timeline + Live Preview +
   Project Inspector, simultaneously visible); relocate secondary/advanced
   views out of the primary rail.
3. **Increase narration cadence** to the "continuous conversation" feel,
   sourced from the now-real worker dispatch events in step 1 (assignment,
   per-worker completion, review outcome), still composed by MARK — never
   raw internal events.

Each of these is a substantial change in its own right and deserves its own
planning pass before implementation, per the same reasoning that produced
this document: get the model right before building on top of it.
