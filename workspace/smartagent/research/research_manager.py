"""
Research manager.

Defines `ResearchFinding` and `ResearchManager`, the placeholder
abstractions for MARK's research workflow:

    1. Search trusted sources for information on a topic.
    2. Summarize what was found.
    3. Present the summary to the owner for approval.
    4. Only store approved summaries into long-term memory.

No internet browsing or summarization backend is implemented yet — this
module defines the contract and a working (in-memory) approval queue so
the rest of the system can be wired up incrementally without ever letting
unreviewed information become permanent knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from smartagent.memory.memory_manager import MemoryManager


@dataclass
class ResearchFinding:
    """A single piece of information discovered during research, pending review."""

    topic: str
    source: str
    summary: str


class ResearchManager:
    """
    Coordinates MARK's "research, summarize, ask, store" workflow.

    Args:
        memory: The `MemoryManager` approved findings are eventually stored
            into. Optional so this class can be instantiated before memory
            is configured.
        trusted_sources: Domains/sources research is allowed to draw from.
            Placeholder only — not yet enforced since no search backend
            exists.
    """

    def __init__(self, memory: MemoryManager | None = None, trusted_sources: list[str] | None = None) -> None:
        self.memory = memory
        self.trusted_sources = trusted_sources or []
        # Findings that have been summarized but not yet approved by the owner.
        self._pending: list[ResearchFinding] = []

    def search(self, topic: str) -> list[ResearchFinding]:
        """
        Search trusted sources for information about `topic`.

        Placeholder implementation: raises `NotImplementedError` since no
        internet browsing backend has been wired up yet. Real
        implementations must only consult `self.trusted_sources`.
        """
        # TODO: query trusted sources (docs, APIs, curated feeds) and
        # return raw findings — do not browse arbitrary/untrusted sites.
        raise NotImplementedError("Internet research is not implemented yet.")

    def summarize(self, findings: list[ResearchFinding]) -> str:
        """
        Summarize a batch of findings into a single owner-readable report.

        Placeholder implementation: raises `NotImplementedError` since no
        summarization backend (e.g. a language model call) is wired up yet.
        """
        # TODO: call a model (see smartagent.models) to condense findings
        # into a concise, readable summary.
        raise NotImplementedError("Research summarization is not implemented yet.")

    def queue_for_approval(self, finding: ResearchFinding) -> None:
        """Add a finding to the pending queue awaiting the owner's review."""
        self._pending.append(finding)

    def list_pending(self) -> list[ResearchFinding]:
        """Return all findings currently awaiting owner approval."""
        return list(self._pending)

    def approve(self, finding: ResearchFinding) -> None:
        """
        Approve a pending finding and commit it to long-term memory.

        This is the only path by which research becomes permanent
        knowledge — nothing is stored automatically.
        """
        if finding in self._pending:
            self._pending.remove(finding)
        if self.memory is not None:
            # NOTE: `MemoryManager.remember()`'s real (Memory v1) signature
            # takes `category`/`tags`, not the old placeholder's `metadata`
            # dict — this call previously referenced a parameter that no
            # longer exists (and would have raised `TypeError` the first
            # time a finding was approved). Fixed here to keep "approve a
            # finding" actually working, per Milestone 2's "DO NOT break
            # Memory v1" rule.
            self.memory.remember(finding.summary, category="Research", tags=[finding.topic, finding.source])

    def reject(self, finding: ResearchFinding) -> None:
        """Discard a pending finding without storing it."""
        if finding in self._pending:
            self._pending.remove(finding)
