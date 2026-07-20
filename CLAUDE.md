# MARK AIOS

Before doing anything else in this repository, read
[`docs/canonical/CLAUDE_ENGINEER_BOOTSTRAP.md`](docs/canonical/CLAUDE_ENGINEER_BOOTSTRAP.md).

**`docs/canonical/`** is the system specification for this project — the
canonical source of truth, not optional background reading. It defines what
MARK is, what it will never become, how it makes decisions, and the current
engineering priorities. On any conflict between that directory and anything
else in this repo (including this file), `docs/canonical/` wins.

## The one-line version

MARK is not a chatbot, not a coding assistant, and not a wrapper around an
LLM. MARK is a persistent AI Operating System — one permanent intelligence
that reasons, remembers, and delegates to specialist workers, with AI
providers as replaceable reasoning engines underneath it. Before adding a
feature, ask what *ability* it gives MARK, not what button it adds.

## Where things actually stand

`docs/mark-operating-system.md` tracks current implementation status against
the canonical vision — what's real today, what's stale, what's not started.
Treat it as a status report, not a competing spec.

**[`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md)** is the current,
frequently-updated record of what's actually been built and verified —
read it before starting work, it changes more often than this file.
**[`docs/BRAIN_RECONSTRUCTION_AUDIT.md`](docs/BRAIN_RECONSTRUCTION_AUDIT.md)**
is the latest full comparison of MARK's intended architecture against the
live implementation. If Replit Agent is also working on this project, see
[`docs/canonical/REPLIT_BOOTSTRAP.md`](docs/canonical/REPLIT_BOOTSTRAP.md)
for the division of labor between the two.
