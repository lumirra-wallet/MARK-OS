"""
DecisionEngine — Milestone 2 Brain v2, Part 3.

Given a classified `Intent` and the modules currently registered with the
`ModuleRegistry`, decides an ordered list of candidate module names for
`BrainRouter` to try, most-preferred first.

Design decision: ordering follows the fixed priority declared by the
Milestone 2 spec — Memory > Skills > Tools > Planning > Research > Model >
Unknown — rather than branching on `intent`. Two reasons:

  1. None of skills/tools/planning/research have real free-text-handling
     behavior yet, so intent-based *selection* would be indistinguishable
     from priority-based selection in practice, while introducing a real
     failure mode: if an ambiguous/UNKNOWN classification were used to
     pick a single module directly, it would route straight to `unknown`
     (which always succeeds), so memory would never even be consulted —
     regressing Milestone 1's "always check memory before the model" rule.
  2. A fixed, registry-filtered chain still satisfies "the Brain must
     never hardcode module names" (Part 4): only registered modules are
     ever offered as candidates, and the *category* ordering — not
     specific subsystems — is the only thing fixed here.

`intent` is still accepted and threaded through to the caller for logging
(Part 7 requires it in every decision log) and is the natural extension
point once a category like `skills` or `tools` has enough concrete
members that *which one* to try needs intent-aware disambiguation.
"""

from __future__ import annotations

from smartagent.brain.intent_analyzer import Intent
from smartagent.brain.module_registry import ModuleRegistry

# Fixed fallback priority order per Milestone 2 spec Part 3.
DECISION_PRIORITY: tuple[str, ...] = ("memory", "skills", "tools", "planning", "research", "model", "unknown")


class DecisionEngine:
    """Decides which registered module(s) should receive a request, in priority order."""

    def decide(self, intent: Intent, registry: ModuleRegistry) -> list[str]:
        """
        Return the ordered list of registered module names to try for this request.

        Only names actually present in `registry` are returned, in
        `DECISION_PRIORITY` order. `intent` does not currently affect the
        ordering (see module docstring) but is accepted so the signature
        won't need to change once it does.
        """
        return [name for name in DECISION_PRIORITY if registry.is_registered(name)]
