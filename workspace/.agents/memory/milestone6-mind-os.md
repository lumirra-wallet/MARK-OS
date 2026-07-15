---
name: Milestone 6 — MARK Mind OS v1
description: Architecture and key decisions for smartagent/mind/ — the persistent internal mind layered on Brain/Memory/Skills/Tools/Models.
---

## Core constraint: observe, never drive

The Mind (`ExecutiveController` + 9 supporting engines under
`smartagent/mind/`) represents MARK's own state (self-model, identity,
attention, confidence, internal state, reflections, health) but must
never change what `BrainRouter` decides or how any other subsystem
behaves. `SmartAgent.handle_message()`'s returned message must stay
byte-for-byte identical with or without the Mind.

**Why:** the milestone explicitly forbids the Mind from becoming a
second decision-maker (no forked routing logic, no behavior changes to
Memory/Brain/Skills/Tools/Model Framework) — it's meant to be
introspectable state, not a new intelligence layer.

**How to apply:** any new Mind hook into `agent.py` must be additive and
wrapped in `try/except` so a Mind bug degrades to "self-awareness didn't
update" rather than breaking the response. Verify with a test that
`handle_message()`'s return value doesn't change when the Mind observation
raises.

## Read-only providers avoid a circular import

`ExecutiveController` never imports `smartagent.brain.agent.SmartAgent`.
Instead `SmartAgent` builds a `MindProviders` dataclass of zero-argument
callables (`active_goal`, `goals`, `skills`, `tools`, `active_model`,
`running_processes`) closing over its own live subsystems, and passes it
to `ExecutiveController` at construction time.

**Why:** `SmartAgent` constructs the Mind, so the Mind importing
`SmartAgent` back would invert the dependency and create a cycle. Every
provider defaults to a no-op (empty/`None`), so `ExecutiveController` is
fully constructible and testable with zero providers bound.

**How to apply:** any future Mind engine that needs live data from
elsewhere in the app should get it via a new `MindProviders` field, not a
direct import.

## Homeostasis is a synchronous tick(), not a background thread

`DigitalHomeostasisLoop.tick()` and `HomeostasisEngine.check()` are
explicit, caller-invoked methods — there's no timer or thread anywhere in
`smartagent/mind/homeostasis/`.

**Why:** matches the rest of the codebase's fully synchronous, directly
testable design. Real periodic scheduling is left to
`smartagent.automation`, which isn't wired up to call `tick()` yet
(tracked as a TODO in `ROADMAP.md`).

**How to apply:** don't add threading/asyncio to the Mind package. If
periodic execution is needed later, wire `smartagent.automation`'s
scheduler to call `tick()` — don't build a second scheduling mechanism
inside `mind/`.

## IdentityEngine really parses SMARTAGENT.md

`smartagent/mind/identity/identity_engine.py`'s `IdentityEngine` does a
narrow Markdown parse of `SMARTAGENT.md`'s existing headings (`##
Identity`, `## Core Principles`, `## Personality`, `## Long-Term Goals`,
`## Architecture Philosophy`, `## Safety`) into a structured `Identity`
dataclass, and can round-trip it back out via `to_markdown()`/`save()`.
Falls back to a hardcoded `default_identity()` (matching current
`SMARTAGENT.md` content) if the file is missing or a section can't be
found.

**Why:** avoids maintaining two divergent copies of MARK's identity (one
in prose, one in code) that could silently drift apart.

**How to apply:** if `SMARTAGENT.md`'s heading structure changes, update
`IdentityEngine._parse()`/`_split_sections()` to match, and re-verify the
round-trip test (`tests/test_mind.py::TestIdentityEngine`) still passes
against the real file.

## Event bus reuse, not a separate Mind bus

All Mind engines take an optional `EventBus` (same convention as
`ToolEngine`/`ModelManager`) and publish onto the *same* shared bus
`SmartAgent.events` uses — `smartagent/mind/events/mind_events.py` is just
a re-export of `Events` plus a null-safe `publish_mind_event()` helper,
not a new bus.

**Why:** keeps every subsystem's activity on one auditable event stream
rather than fragmenting observability across multiple buses.
