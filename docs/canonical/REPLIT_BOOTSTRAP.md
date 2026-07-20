# Replit Agent Bootstrap

Read this before touching anything in this repository. It is the Replit-Agent
counterpart to `docs/canonical/CLAUDE_ENGINEER_BOOTSTRAP.md` (Claude's own
entry point) — the two exist so that whichever AI is working on this project
at a given moment starts from the same shared understanding, per the
division of labor `docs/canonical/PROJECT_CONTEXT.md` §42 describes.

## What MARK is

MARK is not a chatbot, a coding assistant, or a wrapper around an LLM. MARK
is a persistent AI Operating System — one permanent intelligence that
reasons, remembers, and delegates to specialist workers, with AI providers
(Ollama, Claude, GPT, etc.) as replaceable reasoning engines underneath it,
never MARK himself. Full detail: `docs/canonical/MARK_CONSTITUTION.md`,
`docs/canonical/PROJECT_CONTEXT.md`.

**`docs/canonical/` is the source of truth for this project.** If anything
you build conflicts with it, the canonical docs win, not the other way
around — including anything in this file or in older prompts you may have
been given previously.

## Division of labor

- **Claude** owns: backend, runtime, memory, workers, voice pipeline (STT/TTS),
  APIs, infrastructure, long-term architecture.
- **Replit Agent** owns: landing page, responsive UI, dashboard visual
  design, UX polish, frontend implementation details, animations.
- **Neither AI should overwrite the other's work without understanding it
  first.** Git is the shared communication layer — read recent commits and
  `docs/SESSION_HANDOFF.md` before making structural changes.
- Leave a clear commit message or note when you hand work back — the next
  session (Claude or Replit Agent) should be able to pick up context from
  git history and `docs/SESSION_HANDOFF.md` alone, without the owner having
  to re-explain anything.

## Where things actually stand right now

See **[`docs/SESSION_HANDOFF.md`](../SESSION_HANDOFF.md)** for a full,
current account of what's been built, what's real and verified, and what's
still broken or pending. Read it before starting frontend work — it
describes the real backend contracts (WebSocket event shapes, the audio
streaming protocol, self-state shape) your UI work needs to stay compatible
with.

Also see **[`docs/BRAIN_RECONSTRUCTION_AUDIT.md`](../BRAIN_RECONSTRUCTION_AUDIT.md)**
— a full audit comparing MARK's intended architecture (as described across
every canonical document) against what the code actually does today. It is
currently awaiting the owner's review and approval; **no structural
implementation work should begin against its findings until the owner signs
off**, though normal frontend/UX work (Replit Agent's lane) is not blocked
by that gate unless it touches the specific systems the audit flags (the
conversation/mission routing gate, memory architecture, or the voice
pipeline's ownership boundary).

## Ground rules that apply to any AI working on this repo

- Never fake progress. If something isn't built, say so — don't simulate
  success or return a plausible-looking placeholder.
- Never duplicate a system that already exists — check `docs/SESSION_HANDOFF.md`
  and the codebase first.
- Design before code for anything non-trivial.
- Protect working surfaces (the WebSocket event contract, the dashboard,
  the worker pipeline, the approval system) — extend additively, don't
  rewrite wholesale.
