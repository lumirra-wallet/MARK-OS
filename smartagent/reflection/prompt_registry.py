"""
PromptRegistry — Milestone 14: versioned worker prompt storage.

Stores the evolution history of each worker's system prompt as a list of
``PromptVersion`` objects.  Workers can query the registry for an improved
prompt to override their class-level ``_system_prompt`` at runtime.

The registry is injected into ``ExecutionContext.metadata["system_prompts"]``
before each run so workers can opt in to improved prompts without modifying
their own source code.

Storage::

    context.metadata["system_prompts"] = {
        "Research Worker": "<improved prompt text>",
        "Coding Worker":   "<improved prompt text>",
    }

Workers in OllamaWorkerMixin check this dict first (see
``_resolve_system_prompt()``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PromptVersion:
    """One version of a worker's system prompt."""

    version: int
    content: str
    reason: str                 # why this version was created
    timestamp: str
    score_improvement: float    # estimated confidence improvement over v(n-1)


class PromptRegistry:
    """
    Stores versioned system prompts for all workers.

    Thread-safe for read access (multiple workers reading concurrently is safe
    in CPython due to the GIL).  Writes happen only during post-execution
    reflection, serialised by the ``ReflectionEngine``.
    """

    def __init__(self) -> None:
        self._registry: dict[str, list[PromptVersion]] = {}

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_version(
        self,
        worker_name: str,
        content: str,
        reason: str,
        score_improvement: float = 0.0,
    ) -> PromptVersion:
        """
        Record a new prompt version for *worker_name*.

        Returns the new ``PromptVersion`` (version numbers start at 1).
        """
        history = self._registry.setdefault(worker_name, [])
        version = PromptVersion(
            version=len(history) + 1,
            content=content,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            score_improvement=round(score_improvement, 3),
        )
        history.append(version)
        return version

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def current_prompt(self, worker_name: str) -> str | None:
        """Return the latest prompt for *worker_name*, or ``None``."""
        history = self._registry.get(worker_name, [])
        return history[-1].content if history else None

    def version_count(self, worker_name: str) -> int:
        """Number of stored versions for *worker_name*."""
        return len(self._registry.get(worker_name, []))

    def history(self, worker_name: str) -> list[PromptVersion]:
        """All versions for *worker_name* in chronological order."""
        return list(self._registry.get(worker_name, []))

    def all_workers(self) -> list[str]:
        """Worker names that have at least one stored prompt version."""
        return list(self._registry.keys())

    def as_metadata_dict(self) -> dict[str, str]:
        """
        Return a flat dict suitable for injection into
        ``ExecutionContext.metadata["system_prompts"]``.

        Maps ``worker_name → latest prompt text`` for every worker that has
        an improvement on record.
        """
        return {
            name: versions[-1].content
            for name, versions in self._registry.items()
            if versions
        }

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def format_history(self, worker_name: str) -> str:
        """Human-readable version history for *worker_name*."""
        history = self.history(worker_name)
        if not history:
            return f"No prompt versions recorded for '{worker_name}'."
        lines = [f"Prompt history — {worker_name}  ({len(history)} version(s))"]
        for v in history:
            lines.append(
                f"  v{v.version}  [{v.timestamp}]  +{v.score_improvement:.0%}  — {v.reason}"
            )
        return "\n".join(lines)

    def format_all_histories(self) -> str:
        """Format version histories for every worker."""
        if not self._registry:
            return "No prompt evolution recorded yet."
        return "\n\n".join(
            self.format_history(name) for name in sorted(self._registry)
        )
