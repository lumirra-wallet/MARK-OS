"""
KnowledgeStats — live statistics about the knowledge graph.

Tracks all metrics required by the Milestone 7 spec:
  Total Concepts, Relationships, Average Confidence, Conflicts,
  Pending Inbox Items, Verified Concepts, Unverified Concepts,
  Categories, Sources, Evidence Count, Growth Over Time.

Growth is tracked by appending a snapshot entry to `knowledge/stats_history.json`
each time `snapshot()` is called. This gives MARK a simple time-series view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from smartagent.knowledge.concepts.concept import VerificationStatus
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.knowledge.inbox.knowledge_inbox import KnowledgeInbox
    from smartagent.knowledge.ontology.ontology_engine import OntologyEngine
    from smartagent.knowledge.storage.knowledge_storage import KnowledgeStorage

logger = get_logger(__name__)


@dataclass
class KnowledgeStatsReport:
    """A point-in-time snapshot of knowledge graph statistics."""

    timestamp: str = ""
    total_concepts: int = 0
    total_relationships: int = 0
    average_confidence: float = 0.0
    total_conflicts: int = 0
    pending_inbox_items: int = 0
    verified_concepts: int = 0
    unverified_concepts: int = 0
    total_categories: int = 0
    total_sources: int = 0
    total_evidence: int = 0
    contradicted_concepts: int = 0
    low_confidence_concepts: int = 0     # confidence < 0.5
    high_confidence_concepts: int = 0    # confidence >= 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_concepts": self.total_concepts,
            "total_relationships": self.total_relationships,
            "average_confidence": round(self.average_confidence, 4),
            "total_conflicts": self.total_conflicts,
            "pending_inbox_items": self.pending_inbox_items,
            "verified_concepts": self.verified_concepts,
            "unverified_concepts": self.unverified_concepts,
            "total_categories": self.total_categories,
            "total_sources": self.total_sources,
            "total_evidence": self.total_evidence,
            "contradicted_concepts": self.contradicted_concepts,
            "low_confidence_concepts": self.low_confidence_concepts,
            "high_confidence_concepts": self.high_confidence_concepts,
        }

    def summary(self) -> str:
        """Return a human-readable one-paragraph summary."""
        return (
            f"Knowledge Graph ({self.timestamp}): "
            f"{self.total_concepts} concepts, "
            f"{self.total_relationships} relationships, "
            f"avg confidence {self.average_confidence:.2f}. "
            f"Verified: {self.verified_concepts}, "
            f"Unverified: {self.unverified_concepts}, "
            f"Contradicted: {self.contradicted_concepts}. "
            f"Inbox: {self.pending_inbox_items} pending. "
            f"Sources: {self.total_sources}, Evidence: {self.total_evidence}, "
            f"Categories: {self.total_categories}."
        )


class KnowledgeStats:
    """
    Computes and stores time-series statistics for the knowledge graph.

    Args:
        storage: The `KnowledgeStorage` instance.
        inbox: The `KnowledgeInbox` instance for pending item counts.
        ontology: The `OntologyEngine` for category counts.
        root: Knowledge root dir where the history file is written.
    """

    _HISTORY_FILENAME = "stats_history.json"

    def __init__(
        self,
        storage: "KnowledgeStorage",
        inbox: "KnowledgeInbox",
        ontology: "OntologyEngine",
        root: str | Path = "knowledge",
    ) -> None:
        self._storage = storage
        self._inbox = inbox
        self._ontology = ontology
        self._history_path = Path(root) / self._HISTORY_FILENAME
        self._history: list[dict[str, Any]] = self._load_history()

    def _load_history(self) -> list[dict[str, Any]]:
        """Load existing snapshot history from disk."""
        if not self._history_path.exists():
            return []
        try:
            return json.loads(self._history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load stats history: %s", exc)
            return []

    def _save_history(self) -> None:
        """Persist the history list to disk."""
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(
            json.dumps(self._history, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def current(self) -> KnowledgeStatsReport:
        """
        Compute and return a fresh statistics report without persisting it.
        """
        concepts = self._storage.read_all_concepts()
        relationships = self._storage.read_all_relationships()
        sources = self._storage.read_all_sources()
        evidence = self._storage.read_all_evidence()

        total = len(concepts)
        verified = sum(1 for c in concepts if c.verification_status == VerificationStatus.VERIFIED)
        unverified = sum(1 for c in concepts if c.verification_status == VerificationStatus.UNVERIFIED)
        contradicted = sum(1 for c in concepts if c.contradiction_ids)
        conflicts = sum(1 for c in concepts if c.verification_status.value == "contradicted")
        low_conf = sum(1 for c in concepts if c.confidence < 0.5)
        high_conf = sum(1 for c in concepts if c.confidence >= 0.8)
        avg_conf = (
            sum(c.confidence for c in concepts) / total if total else 0.0
        )

        return KnowledgeStatsReport(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            total_concepts=total,
            total_relationships=len(relationships),
            average_confidence=avg_conf,
            total_conflicts=conflicts,
            pending_inbox_items=self._inbox.count_pending(),
            verified_concepts=verified,
            unverified_concepts=unverified,
            total_categories=len(self._ontology.list_all()),
            total_sources=len(sources),
            total_evidence=len(evidence),
            contradicted_concepts=contradicted,
            low_confidence_concepts=low_conf,
            high_confidence_concepts=high_conf,
        )

    def snapshot(self) -> KnowledgeStatsReport:
        """
        Compute a statistics report and append it to the growth history file.

        Returns:
            The computed `KnowledgeStatsReport`.
        """
        report = self.current()
        self._history.append(report.to_dict())
        self._save_history()
        logger.info("Knowledge stats snapshot: %s", report.summary())
        return report

    def growth_history(self) -> list[dict[str, Any]]:
        """Return the full list of historical snapshots."""
        return list(self._history)
