"""
Knowledge Inbox — the approval gate for all new knowledge.

Nothing enters MARK's permanent knowledge graph automatically. Every
proposed concept must pass through the inbox pipeline:

    New Knowledge
    ↓ Validation      (ConceptValidator — schema/structural checks)
    ↓ Conflict Detection (check existing graph for contradictions)
    ↓ Confidence Scoring (ConfidenceEngine — initial score)
    ↓ Mr. Smart Approval (pending → approved / rejected by owner)
    ↓ Knowledge Graph   (KnowledgeManager.approve_concept)

This satisfies the Milestone 7 requirement:
    "Nothing enters permanent knowledge automatically."
    "Before storing knowledge: Detect conflicts. Flag conflict.
     Do not overwrite automatically. Instead send to Knowledge Inbox."
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from smartagent.knowledge.confidence.confidence_engine import ConfidenceEngine
from smartagent.knowledge.validation.validator import ConceptValidator
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept
    from smartagent.knowledge.storage.knowledge_storage import KnowledgeStorage

logger = get_logger(__name__)


class InboxItemStatus(str, Enum):
    """Lifecycle state of an inbox item."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFLICT = "conflict"       # Blocked by a detected contradiction


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class InboxItem:
    """
    A proposed concept waiting for Mr. Smart's review.

    Args:
        id: Unique inbox item ID.
        concept: The proposed concept data.
        submitted_at: ISO 8601 timestamp of submission.
        status: Current state in the approval workflow.
        validation_errors: Hard errors from ConceptValidator.
        validation_warnings: Soft warnings from ConceptValidator.
        conflict_ids: Concept IDs in the existing graph that contradict
            this proposal (triggers CONFLICT status).
        initial_confidence: Score from ConfidenceEngine at submission time.
        notes: Human-readable review notes.
    """

    id: str
    concept: "Concept"
    submitted_at: str = ""
    status: InboxItemStatus = InboxItemStatus.PENDING
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    initial_confidence: float = 0.5
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for storage."""
        return {
            "id": self.id,
            "concept": self.concept.to_dict(),
            "submitted_at": self.submitted_at,
            "status": self.status.value,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "conflict_ids": self.conflict_ids,
            "initial_confidence": self.initial_confidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InboxItem":
        from smartagent.knowledge.concepts.concept import Concept
        return cls(
            id=d["id"],
            concept=Concept.from_dict(d["concept"]),
            submitted_at=d.get("submitted_at", ""),
            status=InboxItemStatus(d.get("status", "pending")),
            validation_errors=d.get("validation_errors", []),
            validation_warnings=d.get("validation_warnings", []),
            conflict_ids=d.get("conflict_ids", []),
            initial_confidence=float(d.get("initial_confidence", 0.5)),
            notes=d.get("notes", ""),
        )


class KnowledgeInbox:
    """
    Manages the approval queue for proposed knowledge.

    The inbox is persistent — each item is saved to `knowledge/inbox/`
    immediately on submission so it survives restarts. Items are removed
    from disk when approved or rejected.

    Args:
        storage: The `KnowledgeStorage` instance for persisting inbox items.
        existing_concepts_provider: A callable that returns the current list
            of approved concepts from the graph. Used for conflict detection.
    """

    def __init__(
        self,
        storage: "KnowledgeStorage",
        existing_concepts_provider: Any = None,
    ) -> None:
        self._storage = storage
        self._existing_concepts_provider = existing_concepts_provider
        self._validator = ConceptValidator()
        self._confidence_engine = ConfidenceEngine()
        # In-memory index; rebuilt from storage on init.
        self._items: dict[str, InboxItem] = {}
        self._load_from_storage()

    def _load_from_storage(self) -> None:
        """Rebuild the in-memory index from persisted inbox files."""
        for data in self._storage.read_all_inbox_items():
            try:
                item = InboxItem.from_dict(data)
                self._items[item.id] = item
            except (KeyError, ValueError) as exc:
                logger.warning("Skipped corrupt inbox item: %s", exc)
        logger.info("Inbox loaded %d item(s) from storage", len(self._items))

    def submit(self, concept: "Concept") -> InboxItem:
        """
        Submit a proposed concept for review.

        Runs validation and conflict detection immediately, scores initial
        confidence, and persists the item to storage.

        Args:
            concept: The proposed concept to review.

        Returns:
            The created `InboxItem` with its initial status.
        """
        item_id = f"inbox-{uuid.uuid4().hex[:12]}"
        item = InboxItem(
            id=item_id,
            concept=concept,
            submitted_at=_now_iso(),
        )

        # Step 1: Validation
        validation = self._validator.validate(concept)
        item.validation_errors = validation.errors
        item.validation_warnings = validation.warnings

        if not validation.is_valid:
            item.status = InboxItemStatus.REJECTED
            logger.info(
                "Inbox item %s rejected at validation: %s",
                item_id, validation.errors
            )
        else:
            # Step 2: Conflict detection
            conflicts = self._detect_conflicts(concept)
            if conflicts:
                item.conflict_ids = conflicts
                item.status = InboxItemStatus.CONFLICT
                logger.info(
                    "Inbox item %s flagged for conflicts with: %s", item_id, conflicts
                )
            else:
                item.status = InboxItemStatus.PENDING

            # Step 3: Initial confidence score (even for conflict items)
            item.initial_confidence = self._confidence_engine.quick_score(concept)

        # Persist
        self._storage.write_inbox_item(item_id, item.to_dict())
        self._items[item_id] = item
        logger.info(
            "Submitted concept %r to inbox as %s (status=%s)",
            concept.title, item_id, item.status.value
        )
        return item

    def _detect_conflicts(self, proposed: "Concept") -> list[str]:
        """
        Return IDs of existing concepts that contradict `proposed`.

        Contradiction detection strategy:
        1. Any existing concept whose contradiction_ids list includes
           the proposed concept's id.
        2. Any existing concept that is marked `contradicts` in a relationship
           to the proposed concept (handled by the KnowledgeManager layer).
        3. Basic title/alias overlap with a contradicts-type relationship
           (detected here via `contradiction_ids` cross-reference).

        This is intentionally conservative — false positives require a
        human review step, which is preferable to silently overwriting.
        """
        conflicts: list[str] = []
        if self._existing_concepts_provider is None:
            return conflicts
        try:
            existing: list["Concept"] = self._existing_concepts_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not retrieve existing concepts for conflict check: %s", exc)
            return conflicts

        proposed_id = proposed.id
        for existing_concept in existing:
            # If the existing concept already lists this proposed concept
            # as a contradiction.
            if proposed_id in existing_concept.contradiction_ids:
                conflicts.append(existing_concept.id)
            # If the proposed concept already lists the existing one as a
            # contradiction (e.g. re-submission after manual flagging).
            elif existing_concept.id in proposed.contradiction_ids:
                conflicts.append(existing_concept.id)
        return conflicts

    def approve(self, item_id: str, notes: str = "") -> InboxItem | None:
        """
        Mark an inbox item as approved.

        The caller (KnowledgeManager) is responsible for actually
        adding the concept to the graph after receiving the approved item.

        Args:
            item_id: The inbox item ID to approve.
            notes: Optional reviewer notes.

        Returns:
            The updated `InboxItem`, or None if not found.
        """
        item = self._items.get(item_id)
        if item is None:
            logger.warning("Approve failed: inbox item %r not found", item_id)
            return None
        item.status = InboxItemStatus.APPROVED
        item.notes = notes or item.notes
        self._storage.write_inbox_item(item_id, item.to_dict())
        logger.info("Approved inbox item %s (%r)", item_id, item.concept.title)
        return item

    def reject(self, item_id: str, notes: str = "") -> InboxItem | None:
        """
        Mark an inbox item as rejected (and remove it from storage).

        Args:
            item_id: The inbox item ID to reject.
            notes: Optional rejection reason.

        Returns:
            The rejected `InboxItem`, or None if not found.
        """
        item = self._items.get(item_id)
        if item is None:
            logger.warning("Reject failed: inbox item %r not found", item_id)
            return None
        item.status = InboxItemStatus.REJECTED
        item.notes = notes or item.notes
        # Keep the file on disk for auditing; just update the status.
        self._storage.write_inbox_item(item_id, item.to_dict())
        logger.info("Rejected inbox item %s (%r)", item_id, item.concept.title)
        return item

    def remove(self, item_id: str) -> bool:
        """Remove an inbox item from both memory and storage (post-processing)."""
        self._items.pop(item_id, None)
        return self._storage.delete_inbox_item(item_id)

    def get(self, item_id: str) -> InboxItem | None:
        """Retrieve an inbox item by ID."""
        return self._items.get(item_id)

    def list_pending(self) -> list[InboxItem]:
        """Return all items waiting for Mr. Smart's review."""
        return [i for i in self._items.values() if i.status == InboxItemStatus.PENDING]

    def list_conflicts(self) -> list[InboxItem]:
        """Return all items that were flagged for contradiction conflicts."""
        return [i for i in self._items.values() if i.status == InboxItemStatus.CONFLICT]

    def list_all(self) -> list[InboxItem]:
        """Return every inbox item regardless of status."""
        return list(self._items.values())

    def count_pending(self) -> int:
        """Number of items currently awaiting approval."""
        return sum(1 for i in self._items.values() if i.status == InboxItemStatus.PENDING)
