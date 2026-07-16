---
name: Milestone 17 Multi-Agent Collaboration
description: Architecture, design decisions, and test patterns for the multi-agent CEO→Teams→Workers layer.
---

# Milestone 17: Multi-Agent Collaboration

## Architecture

```
CEOAgent
  └─ TeamPlanner → MultiAgentPlan (one TeamAssignment per team)
  └─ TeamRunner × N (each wraps its own scoped Orchestrator)
       └─ Planner → TaskGraph → Scheduler → Workers
  └─ MultiAgentResult (team results aggregated)
```

## Key Files

- `smartagent/multi_agent/` — all 7 modules + `__init__.py`
- `smartagent/ui/commands/multi_agent.py` — `teams`, `team`, `ceo-plan`, `ceo` commands
- `tests/test_multi_agent.py` — 97 tests

## Decisions

- **Context chaining**: after each team finishes, its summary is appended to `prior_context` passed to the next team via `TeamRunner.run(assignment, prior_context=...)`.
- **Scoped worker registry**: each `TeamRunner` builds a `WorkerRegistry` filtered to its team's `TaskType` values; `GENERIC` is always included as fallback.
- **`_extra_metadata` hook**: `TeamRunner` sets `orchestrator._extra_metadata = {"team": ..., "prior_context": ...}` before calling `execute_goal()`; `Orchestrator._inject_services()` picks it up and merges into `context.metadata`.
- **Rule-based default**: `TeamPlanner` scores teams by keyword count; falls back to full pipeline `[research, engineering, qa, documentation]` when fewer than `min_teams` score above threshold.
- **Team→TaskType mapping**: research=[RESEARCH, ANALYSIS, REPORT], engineering=[PLANNING, DESIGN, ARCHITECTURE, CODING, IMPLEMENTATION, REVIEW], qa=[TESTING, REVIEW], documentation=[DOCUMENTATION, REPORT].

## Gotcha

`TeamResult.one_line()` must NOT uppercase the team name — tests assert lowercase team name appears in the line. The `.upper()` format would break those assertions.

**Why:** tests like `assert "engineering" in r.one_line()` rely on lowercase; uppercasing hides the name inside `[ENGINEERING  ]`.

## Agent wiring

`SmartAgent.__init__` constructs `self.ceo = CEOAgent.with_agent(self)` which extracts all services via `getattr`. No new required args.
