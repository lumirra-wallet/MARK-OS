# docs/canonical/ — The MARK AIOS System Specification

Everything in this directory is **the canonical source of truth for MARK AIOS**,
per the project owner's explicit direction (2026-07-19). These are not optional
documentation — treat them as the system specification. On any conflict with
another document elsewhere in this repository, **these files win**.

Read [`CLAUDE_ENGINEER_BOOTSTRAP.md`](CLAUDE_ENGINEER_BOOTSTRAP.md) first — it
defines how every AI engineer (Claude, Replit Agent, future contributors, or
MARK itself) should use the rest of this set.

## Files present

| File | Governs |
|---|---|
| [`CLAUDE_ENGINEER_BOOTSTRAP.md`](CLAUDE_ENGINEER_BOOTSTRAP.md) | How to use this document set; engineering role and priorities |
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Master project context — vision, architecture, lessons learned, current priorities |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Technical system architecture — subsystems, directory structure, event bus |
| [`MASTER_BLUEPRINT.md`](MASTER_BLUEPRINT.md) | Continuation blueprint — local + cloud intelligence layers, worker departments, development timeline |
| [`MARK_CONSTITUTION.md`](MARK_CONSTITUTION.md) | Permanent laws — what MARK is and will never become |
| [`MARK_WORLDVIEW.md`](MARK_WORLDVIEW.md) | The philosophy through which MARK interprets reality |
| [`MARK_OPERATING_PRINCIPLES.md`](MARK_OPERATING_PRINCIPLES.md) | How MARK makes decisions, independent of provider or implementation |
| [`MARK_MIND.md`](MARK_MIND.md) | MARK's internal mental model — the five layers of thought |
| [`MARK_DNA.md`](MARK_DNA.md) | What makes each MARK installation unique over time |
| [`MARK_EVOLUTION.md`](MARK_EVOLUTION.md) | How MARK grows across generations without losing identity |
| [`MARK_LIFE_CYCLE.md`](MARK_LIFE_CYCLE.md) | How MARK exists as a persistent process — boot, idle, mission, shutdown |
| [`MARK_PERSONALITY.json`](MARK_PERSONALITY.json) | Structured personality/communication/decision-making configuration |

## Referenced but not present

`CLAUDE_ENGINEER_BOOTSTRAP.md`'s required reading order also lists
`MARK_MANIFESTO.md` and `PROJECT_MEMORY.json`. Neither exists in this
directory yet — they were not included when this set was established. If they
surface later, they belong here.

## Relationship to other docs in this repo

This set **supersedes**, in order of how directly they conflict:

- `docs/mark-operating-system.md` — was previously self-declared authoritative
  ("if anything conflicts with this one, this one wins"). It now explicitly
  defers to this directory instead. Its value — an honest, code-verified
  account of current implementation status — is preserved; its claim to be
  the source of *vision* is not.
- `ARCHITECTURE.md` (repo root), `docs/architecture.md`, `SMARTAGENT.md`,
  `README.md`, `replit.md` — these describe an earlier, narrower framing
  (MARK as "a full-stack AI engineering assistant" / CLI tool) that predates
  this specification and in places no longer matches what's actually running.
  Each has been marked with a banner pointing back here rather than silently
  left to contradict it.

None of the above were deleted. This repository has real implementation
history worth keeping; this directory establishes which document governs
*intent* when they disagree.
