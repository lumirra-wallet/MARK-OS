"""
smartagent.mind — Milestone 6, MARK Mind OS v1.

Transforms MARK from a tool-based assistant into a computational digital
organism with a persistent internal mind. This is explicitly **not**
consciousness — it is a continuously maintained set of internal
representations (who am I, what am I doing, how healthy am I, what should
I do next) that sit *alongside* the Brain, Memory, Skills, Tools, and
Model Framework without changing how any of them behave.

Package layout (mirrors the Tool Engine / Model Framework pattern —
registry/engine-shaped subpackages, each documenting one responsibility):

    mind/
        identity/       Executable identity derived from SMARTAGENT.md (Part 3).
        self_model/      Continuously updated self-representation (Part 2).
        working_memory/ Temporary, auto-expiring cognitive memory (Part 4).
        attention/      Focus ranking, interruption, concurrency limits (Part 5).
        context/        Multi-source context assembly (Part 6).
        confidence/     Per-decision confidence scoring (Part 7).
        homeostasis/    Health monitoring, sensory signals, homeostasis loop (Parts 8, 12, 13).
        state/          Internal state machine with transition history (Part 9).
        reflection/     Post-task reflection, stored separately from memory (Part 11).
        events/         Mind-specific event name constants (Part 10), layered onto
                        the existing `smartagent.brain.events.EventBus`.
        executive/      `ExecutiveController` — the single coordinator of all of
                        the above (Part 1). This is the Mind's composition root.

Design decisions:
    - The Mind observes and represents; it does not drive Brain routing
      decisions. `SmartAgent.handle_message()`'s return value is unchanged
      by the Mind's presence — see `smartagent/brain/agent.py`.
    - Every engine here is synchronous and side-effect-free beyond its own
      in-memory state (no threads, no sleeping, no background loops) so
      behavior stays deterministic and directly testable. "Continuous"
      monitoring (Part 13) is modeled as an explicit `tick()` a caller
      invokes, not an implicit timer — real periodic scheduling is left to
      `smartagent.automation` (out of scope here, per the milestone brief).
    - No new AI provider, network access, learning, knowledge graph,
      browser automation, voice, vision, or cybersecurity behavior is
      introduced. Those remain design-only future modules the
      `ExecutiveController` is shaped to coordinate later (Part 14).
"""

from smartagent.mind.executive.executive_controller import ExecutiveController, MindProviders

__all__ = ["ExecutiveController", "MindProviders"]
