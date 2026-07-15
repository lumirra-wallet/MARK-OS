"""
KnowledgeManager — the single entry point for all Knowledge Engine operations.

Every part of SmartAgent that needs to read or write knowledge goes through
`KnowledgeManager`. The Brain communicates only through this class
(never by directly importing graph/storage/inbox internals), satisfying
the Milestone 7 Brain Integration requirement:

    "Brain must not directly modify knowledge.
     Brain communicates only through KnowledgeManager."

Lifecycle of a new concept:
  1. Caller calls `propose_concept()` — goes into the Inbox.
  2. Mr. Smart calls `approve_concept(item_id)` or `reject_concept(item_id)`.
  3. On approval, `_commit_concept()` writes to storage and updates the graph.

Existing concepts can be updated via `update_concept()` (records a revision),
connected via `connect_concepts()`, or removed via `remove_concept()`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from smartagent.knowledge.concepts.concept import (
    Concept,
    ConceptDifficulty,
    ConceptStatus,
    RevisionEntry,
    VerificationStatus,
)
from smartagent.knowledge.confidence.confidence_engine import ConfidenceEngine, ConfidenceFactors
from smartagent.knowledge.graph.knowledge_graph import KnowledgeGraph
from smartagent.knowledge.inbox.knowledge_inbox import InboxItem, InboxItemStatus, KnowledgeInbox
from smartagent.knowledge.ontology.ontology_engine import OntologyEngine
from smartagent.knowledge.queries.query_engine import QueryEngine
from smartagent.knowledge.relationships.relationship import Relationship, RelationshipType
from smartagent.knowledge.search.knowledge_search import KnowledgeSearch, SearchResult
from smartagent.knowledge.sources.source import Source, SourceType
from smartagent.knowledge.evidence.evidence import Evidence, EvidenceType
from smartagent.knowledge.statistics.knowledge_stats import KnowledgeStats, KnowledgeStatsReport
from smartagent.knowledge.storage.knowledge_storage import KnowledgeStorage
from smartagent.knowledge.validation.validator import ConceptValidator, ValidationResult
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    """UTC timestamp in ISO 8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_id(prefix: str = "concept") -> str:
    """
    Build a sortable, filesystem-safe, unique ID.

    Format: `{prefix}-{YYYYMMDD-HHMMSS}-{uuid8}`
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


class KnowledgeManager:
    """
    High-level API for MARK's Knowledge Engine.

    Coordinates storage, graph, inbox, ontology, search, queries, confidence,
    and statistics into a single, coherent interface. Callers never import
    sub-engines directly.

    Args:
        knowledge_path: Root directory for the knowledge store.
            Defaults to "knowledge/", separate from the memory vault.
    """

    def __init__(self, knowledge_path: str = "knowledge") -> None:
        self._storage = KnowledgeStorage(root=knowledge_path)
        self._graph = KnowledgeGraph()
        self._ontology = OntologyEngine(root=knowledge_path)
        self._confidence_engine = ConfidenceEngine()
        self._validator = ConceptValidator()

        # Inbox needs a provider to see current approved concepts for conflict detection.
        self._inbox = KnowledgeInbox(
            storage=self._storage,
            existing_concepts_provider=self._storage.read_all_concepts,
        )

        # Search and query engines use providers so they always see live data.
        self._search = KnowledgeSearch(
            concepts_provider=self._storage.read_all_concepts
        )
        self._query = QueryEngine(storage=self._storage, graph=self._graph)

        # Stats engine wired to all live components.
        self._stats = KnowledgeStats(
            storage=self._storage,
            inbox=self._inbox,
            ontology=self._ontology,
            root=knowledge_path,
        )

        # Rebuild the in-memory graph from persisted data on startup.
        self._rebuild_graph()

        logger.info("KnowledgeManager ready (root=%s)", knowledge_path)

    def _rebuild_graph(self) -> None:
        """
        Populate the in-memory graph from persisted concepts and relationships.

        Called once at startup. This is the only place that bulk-loads
        storage into the graph; incremental updates go through the specific
        add/remove methods.
        """
        concepts = self._storage.read_all_concepts()
        relationships = self._storage.read_all_relationships()

        for concept in concepts:
            self._graph.add_node(concept.id)

        for rel in relationships:
            bidirectional = rel.direction == "bidirectional"
            self._graph.add_edge(
                rel.from_concept_id,
                rel.to_concept_id,
                rel.id,
                bidirectional=bidirectional,
            )

        logger.info(
            "Graph rebuilt: %d nodes, %d edges",
            len(concepts),
            len(relationships),
        )

    # ------------------------------------------------------------------ #
    # Concept proposal / approval workflow                                  #
    # ------------------------------------------------------------------ #

    def propose_concept(
        self,
        title: str,
        description: str = "",
        summary: str = "",
        category: str = "Uncategorized",
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        examples: list[str] | None = None,
        difficulty: ConceptDifficulty = ConceptDifficulty.INTERMEDIATE,
        importance: float = 0.5,
        author: str = "MARK",
        owner: str = "Mr. Smart",
    ) -> InboxItem:
        """
        Propose a new concept for Mr. Smart's review.

        The concept goes through validation → conflict detection →
        confidence scoring → inbox storage. It does NOT enter the
        permanent knowledge graph until `approve_concept()` is called.

        Args:
            title: Short name for the concept.
            description: Full explanation.
            summary: 1-3 sentence overview.
            category: Ontology path (will be ensured to exist).
            tags: Searchable labels.
            aliases: Alternative names.
            examples: Usage examples.
            difficulty: How hard the concept is.
            importance: Owner-supplied importance score [0.0, 1.0].
            author: Who produced this concept entry.
            owner: Who is responsible for it.

        Returns:
            The `InboxItem` created for this proposal.
        """
        # Ensure the category path exists in the ontology.
        if category != "Uncategorized":
            try:
                self._ontology.ensure_path(category)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not ensure ontology path %r: %s", category, exc)

        now = _now_iso()
        concept = Concept(
            id=_make_id("concept"),
            title=title,
            description=description,
            summary=summary,
            category=category,
            tags=list(tags) if tags else [],
            aliases=list(aliases) if aliases else [],
            examples=list(examples) if examples else [],
            difficulty=difficulty,
            importance=importance,
            confidence=0.5,
            created_at=now,
            updated_at=now,
            author=author,
            owner=owner,
            verification_status=VerificationStatus.PENDING,
        )
        item = self._inbox.submit(concept)
        logger.info(
            "Proposed concept %r (inbox=%s, status=%s)",
            title, item.id, item.status.value
        )
        return item

    def approve_concept(self, item_id: str, notes: str = "") -> Concept | None:
        """
        Approve an inbox item and commit the concept to the permanent graph.

        Args:
            item_id: The inbox item ID returned by `propose_concept`.
            notes: Optional reviewer notes.

        Returns:
            The committed `Concept`, or None if the item was not found.
        """
        item = self._inbox.approve(item_id, notes=notes)
        if item is None:
            return None
        return self._commit_concept(item)

    def reject_concept(self, item_id: str, notes: str = "") -> InboxItem | None:
        """
        Reject an inbox item. The concept never enters the graph.

        Args:
            item_id: The inbox item ID to reject.
            notes: Reason for rejection.

        Returns:
            The updated `InboxItem`, or None if not found.
        """
        return self._inbox.reject(item_id, notes=notes)

    def _commit_concept(self, item: InboxItem) -> Concept:
        """
        Write an approved concept to persistent storage and add it to the graph.
        """
        concept = item.concept
        # Recalculate confidence with any evidence/sources already linked.
        evidence_list = self._storage.read_evidence_for_concept(concept.id)
        source_list = [
            s for sid in concept.source_ids
            if (s := self._storage.read_source(sid)) is not None
        ]
        factors = self._confidence_engine.score(concept, evidence_list, source_list)
        concept.confidence = factors.final_score
        concept.verification_status = VerificationStatus.UNVERIFIED
        concept.updated_at = _now_iso()

        self._storage.write_concept(concept)
        self._graph.add_node(concept.id)
        logger.info("Committed concept %r (%s) to knowledge graph", concept.title, concept.id)
        return concept

    # ------------------------------------------------------------------ #
    # Direct concept management (approved concepts)                        #
    # ------------------------------------------------------------------ #

    def get_concept(self, concept_id: str) -> Concept | None:
        """Retrieve an approved concept by ID."""
        return self._storage.read_concept(concept_id)

    def update_concept(
        self,
        concept_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        summary: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        examples: list[str] | None = None,
        difficulty: ConceptDifficulty | None = None,
        status: ConceptStatus | None = None,
        importance: float | None = None,
        verification_status: VerificationStatus | None = None,
        change_summary: str = "",
        author: str = "MARK",
    ) -> Concept | None:
        """
        Update fields of an existing approved concept, recording a revision.

        Only fields explicitly passed (non-None) are changed. A revision
        entry is always appended to `concept.revision_history`.

        Args:
            concept_id: ID of the concept to update.
            change_summary: Short description of what changed and why.
            author: Who made this change.

        Returns:
            The updated `Concept`, or None if not found.
        """
        concept = self._storage.read_concept(concept_id)
        if concept is None:
            logger.warning("Update failed: concept %r not found", concept_id)
            return None

        # Snapshot previous values for the revision log.
        previous: dict[str, Any] = {}
        if title is not None and title != concept.title:
            previous["title"] = concept.title
            concept.title = title
        if description is not None and description != concept.description:
            previous["description"] = concept.description
            concept.description = description
        if summary is not None and summary != concept.summary:
            previous["summary"] = concept.summary
            concept.summary = summary
        if category is not None and category != concept.category:
            previous["category"] = concept.category
            concept.category = category
        if tags is not None:
            previous["tags"] = concept.tags
            concept.tags = list(tags)
        if aliases is not None:
            previous["aliases"] = concept.aliases
            concept.aliases = list(aliases)
        if examples is not None:
            previous["examples"] = concept.examples
            concept.examples = list(examples)
        if difficulty is not None and difficulty != concept.difficulty:
            previous["difficulty"] = concept.difficulty.value
            concept.difficulty = difficulty
        if status is not None and status != concept.status:
            previous["status"] = concept.status.value
            concept.status = status
        if importance is not None and importance != concept.importance:
            previous["importance"] = concept.importance
            concept.importance = importance
        if verification_status is not None and verification_status != concept.verification_status:
            previous["verification_status"] = concept.verification_status.value
            concept.verification_status = verification_status

        concept.updated_at = _now_iso()
        if previous:
            concept.revision_history.append(RevisionEntry(
                timestamp=concept.updated_at,
                author=author,
                summary=change_summary or "Fields updated",
                previous_values=previous,
            ))

        self._storage.write_concept(concept)
        logger.info("Updated concept %s (%r)", concept_id, concept.title)
        return concept

    def remove_concept(self, concept_id: str) -> bool:
        """
        Permanently remove a concept from both storage and the graph.

        Also removes any relationships that referenced this concept.

        Returns:
            True if the concept was found and removed.
        """
        # Remove all relationships involving this concept.
        for rel_id in self._graph.relationships_for(concept_id):
            self._storage.delete_relationship(rel_id)
        self._graph.remove_node(concept_id)
        deleted = self._storage.delete_concept(concept_id)
        if deleted:
            logger.info("Removed concept %s", concept_id)
        return deleted

    def recalculate_confidence(self, concept_id: str) -> Concept | None:
        """
        Recompute and persist the confidence score for a concept based
        on its current evidence and sources.

        Returns:
            The updated concept with the new confidence score, or None if not found.
        """
        concept = self._storage.read_concept(concept_id)
        if concept is None:
            return None
        evidence_list = self._storage.read_evidence_for_concept(concept_id)
        source_list = [
            s for sid in concept.source_ids
            if (s := self._storage.read_source(sid)) is not None
        ]
        factors = self._confidence_engine.score(concept, evidence_list, source_list)
        concept.confidence = factors.final_score
        concept.updated_at = _now_iso()
        self._storage.write_concept(concept)
        logger.info(
            "Recalculated confidence for %s: %.3f", concept_id, concept.confidence
        )
        return concept

    def explain_confidence(
        self, concept_id: str
    ) -> ConfidenceFactors | None:
        """
        Return the full confidence breakdown for a concept (auditable score).

        Returns:
            A `ConfidenceFactors` instance explaining every component, or
            None if the concept is not found.
        """
        concept = self._storage.read_concept(concept_id)
        if concept is None:
            return None
        evidence_list = self._storage.read_evidence_for_concept(concept_id)
        source_list = [
            s for sid in concept.source_ids
            if (s := self._storage.read_source(sid)) is not None
        ]
        return self._confidence_engine.score(concept, evidence_list, source_list)

    def list_concepts(self) -> list[Concept]:
        """Return all approved concepts sorted by title."""
        return sorted(self._storage.read_all_concepts(), key=lambda c: c.title.lower())

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    def connect_concepts(
        self,
        from_concept_id: str,
        to_concept_id: str,
        relation_type: RelationshipType,
        *,
        strength: float = 0.8,
        confidence: float = 0.8,
        direction: str = "forward",
        source: str = "manual",
        notes: str = "",
    ) -> Relationship | None:
        """
        Create a typed, weighted relationship between two existing concepts.

        Both concepts must already be approved and in the graph. If
        `relation_type` is CONTRADICTS, both concepts' `contradiction_ids`
        are updated automatically.

        Returns:
            The created `Relationship`, or None if either concept is missing.
        """
        if not self._graph.has_node(from_concept_id):
            logger.warning(
                "connect_concepts: from_concept %r not in graph", from_concept_id
            )
            return None
        if not self._graph.has_node(to_concept_id):
            logger.warning(
                "connect_concepts: to_concept %r not in graph", to_concept_id
            )
            return None

        rel = Relationship(
            id=_make_id("rel"),
            from_concept_id=from_concept_id,
            to_concept_id=to_concept_id,
            relation_type=relation_type,
            direction=direction,
            strength=strength,
            confidence=confidence,
            source=source,
            created_at=_now_iso(),
            notes=notes,
        )
        self._storage.write_relationship(rel)
        self._graph.add_edge(
            from_concept_id,
            to_concept_id,
            rel.id,
            bidirectional=(direction == "bidirectional"),
        )

        # Update both concepts' relationship_ids.
        for concept_id in (from_concept_id, to_concept_id):
            concept = self._storage.read_concept(concept_id)
            if concept and rel.id not in concept.relationship_ids:
                concept.relationship_ids.append(rel.id)
                concept.updated_at = _now_iso()
                self._storage.write_concept(concept)

        # If this is a contradiction, update both concepts' contradiction_ids.
        if relation_type == RelationshipType.CONTRADICTS:
            self._mark_contradiction(from_concept_id, to_concept_id)

        logger.info(
            "Connected %s → %s (%s)", from_concept_id, to_concept_id, relation_type.value
        )
        return rel

    def _mark_contradiction(self, concept_a_id: str, concept_b_id: str) -> None:
        """Update both concepts to reference each other as contradictions."""
        for this_id, other_id in (
            (concept_a_id, concept_b_id),
            (concept_b_id, concept_a_id),
        ):
            concept = self._storage.read_concept(this_id)
            if concept and other_id not in concept.contradiction_ids:
                concept.contradiction_ids.append(other_id)
                concept.verification_status = VerificationStatus.CONTRADICTED
                concept.updated_at = _now_iso()
                self._storage.write_concept(concept)

    def disconnect_concepts(self, from_concept_id: str, to_concept_id: str) -> bool:
        """
        Remove the relationship between two concepts.

        Returns True if a relationship was found and removed.
        """
        rel_id = self._graph.get_relationship_id(from_concept_id, to_concept_id)
        if rel_id is None:
            return False
        self._storage.delete_relationship(rel_id)
        self._graph.remove_edge(from_concept_id, to_concept_id)
        # Clean up relationship_ids on both concepts.
        for concept_id in (from_concept_id, to_concept_id):
            concept = self._storage.read_concept(concept_id)
            if concept and rel_id in concept.relationship_ids:
                concept.relationship_ids.remove(rel_id)
                concept.updated_at = _now_iso()
                self._storage.write_concept(concept)
        logger.info("Disconnected %s → %s", from_concept_id, to_concept_id)
        return True

    def get_relationship(self, rel_id: str) -> Relationship | None:
        """Look up a relationship by ID."""
        return self._storage.read_relationship(rel_id)

    def list_relationships(self) -> list[Relationship]:
        """Return all persisted relationships."""
        return self._storage.read_all_relationships()

    # ------------------------------------------------------------------ #
    # Sources                                                              #
    # ------------------------------------------------------------------ #

    def add_source(
        self,
        source_type: SourceType = SourceType.MANUAL_ENTRY,
        author: str = "",
        url: str = "",
        publication: str = "",
        date: str = "",
        reliability_score: float = 0.7,
        citation: str = "",
        notes: str = "",
    ) -> Source:
        """Create and persist a new source record."""
        source = Source(
            id=_make_id("source"),
            source_type=source_type,
            author=author,
            url=url,
            publication=publication,
            date=date or _now_iso()[:10],
            reliability_score=reliability_score,
            citation=citation,
            notes=notes,
        )
        self._storage.write_source(source)
        logger.info("Added source %s (%s)", source.id, source_type.value)
        return source

    def link_source_to_concept(self, source_id: str, concept_id: str) -> bool:
        """
        Link an existing source to an approved concept.

        Returns True on success, False if either record is not found.
        """
        source = self._storage.read_source(source_id)
        concept = self._storage.read_concept(concept_id)
        if source is None or concept is None:
            return False
        if source_id not in concept.source_ids:
            concept.source_ids.append(source_id)
            concept.updated_at = _now_iso()
            self._storage.write_concept(concept)
        return True

    def get_source(self, source_id: str) -> Source | None:
        """Look up a source by ID."""
        return self._storage.read_source(source_id)

    def list_sources(self) -> list[Source]:
        """Return all persisted sources."""
        return self._storage.read_all_sources()

    # ------------------------------------------------------------------ #
    # Evidence                                                             #
    # ------------------------------------------------------------------ #

    def add_evidence(
        self,
        concept_id: str,
        description: str,
        source_id: str = "",
        evidence_type: EvidenceType = EvidenceType.DIRECT,
        strength: float = 0.8,
        confidence: float = 0.7,
        notes: str = "",
    ) -> Evidence | None:
        """
        Add an evidence item to an approved concept and persist it.

        Returns None if the concept is not found.
        """
        concept = self._storage.read_concept(concept_id)
        if concept is None:
            logger.warning("add_evidence: concept %r not found", concept_id)
            return None
        evidence = Evidence(
            id=_make_id("evidence"),
            concept_id=concept_id,
            description=description,
            source_id=source_id,
            evidence_type=evidence_type,
            strength=strength,
            confidence=confidence,
            timestamp=_now_iso(),
            notes=notes,
        )
        self._storage.write_evidence(evidence)
        if evidence.id not in concept.evidence_ids:
            concept.evidence_ids.append(evidence.id)
            concept.updated_at = _now_iso()
            self._storage.write_concept(concept)
        logger.info("Added evidence %s to concept %s", evidence.id, concept_id)
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Look up an evidence item by ID."""
        return self._storage.read_evidence(evidence_id)

    def list_evidence_for_concept(self, concept_id: str) -> list[Evidence]:
        """Return all evidence items linked to a concept."""
        return self._storage.read_evidence_for_concept(concept_id)

    # ------------------------------------------------------------------ #
    # Merge / split (graph-level operations)                              #
    # ------------------------------------------------------------------ #

    def merge_concepts(
        self, primary_id: str, secondary_id: str, change_summary: str = ""
    ) -> Concept | None:
        """
        Merge `secondary_id` into `primary_id`.

        All graph edges are redirected to `primary_id`. The secondary
        concept's source_ids, evidence_ids, tags, and aliases are merged
        into the primary. The secondary is then deleted.

        Returns:
            The updated primary `Concept`, or None if either is not found.
        """
        primary = self._storage.read_concept(primary_id)
        secondary = self._storage.read_concept(secondary_id)
        if primary is None or secondary is None:
            logger.warning("merge_concepts: one or both concepts not found")
            return None

        # Merge secondary's lists into primary.
        for source_id in secondary.source_ids:
            if source_id not in primary.source_ids:
                primary.source_ids.append(source_id)
        for evidence_id in secondary.evidence_ids:
            if evidence_id not in primary.evidence_ids:
                primary.evidence_ids.append(evidence_id)
        for tag in secondary.tags:
            if tag not in primary.tags:
                primary.tags.append(tag)
        for alias in secondary.aliases:
            if alias not in primary.aliases:
                primary.aliases.append(alias)
        if secondary.title not in primary.aliases:
            primary.aliases.append(secondary.title)

        primary.revision_history.append(RevisionEntry(
            timestamp=_now_iso(),
            author="MARK",
            summary=change_summary or f"Merged concept {secondary_id!r} ({secondary.title!r}) into this concept",
        ))
        primary.updated_at = _now_iso()

        self._storage.write_concept(primary)
        self._graph.merge_nodes(primary_id, secondary_id)
        self._storage.delete_concept(secondary_id)

        logger.info("Merged concept %s into %s", secondary_id, primary_id)
        return primary

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """
        Deterministic keyword search over the approved knowledge graph.

        See `KnowledgeSearch.search` for full parameter documentation.
        """
        return self._search.search(query, category=category, tags=tags, limit=limit)

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    @property
    def query(self) -> QueryEngine:
        """
        Direct access to structured query operations.

        Example::

            results = knowledge.query.find_low_confidence()
            deps = knowledge.query.find_dependencies(concept_id)
        """
        return self._query

    # ------------------------------------------------------------------ #
    # Ontology                                                             #
    # ------------------------------------------------------------------ #

    @property
    def ontology(self) -> OntologyEngine:
        """Direct access to category hierarchy operations."""
        return self._ontology

    # ------------------------------------------------------------------ #
    # Inbox                                                                #
    # ------------------------------------------------------------------ #

    def list_pending_inbox(self) -> list[InboxItem]:
        """Return all concepts waiting for Mr. Smart's review."""
        return self._inbox.list_pending()

    def list_conflict_inbox(self) -> list[InboxItem]:
        """Return all concepts flagged for contradiction conflicts."""
        return self._inbox.list_conflicts()

    def get_inbox_item(self, item_id: str) -> InboxItem | None:
        """Retrieve an inbox item by ID."""
        return self._inbox.get(item_id)

    # ------------------------------------------------------------------ #
    # Graph helpers                                                        #
    # ------------------------------------------------------------------ #

    def graph_adjacency(self) -> dict[str, list[str]]:
        """Export the full adjacency dict for visualization tools."""
        return self._graph.to_adjacency_dict()

    def shortest_path(self, from_id: str, to_id: str) -> list[str] | None:
        """
        Find the shortest directed path between two concepts in the graph.

        Returns the ordered list of concept IDs, or None if no path exists.
        """
        return self._graph.shortest_path(from_id, to_id)

    def bfs(self, start_id: str) -> list[str]:
        """BFS traversal from a concept. Returns ordered concept IDs."""
        return list(self._graph.bfs(start_id))

    def dfs(self, start_id: str) -> list[str]:
        """DFS traversal from a concept. Returns ordered concept IDs."""
        return list(self._graph.dfs(start_id))

    # ------------------------------------------------------------------ #
    # Statistics                                                           #
    # ------------------------------------------------------------------ #

    def stats(self) -> KnowledgeStatsReport:
        """Return a live statistics report without saving to history."""
        return self._stats.current()

    def snapshot_stats(self) -> KnowledgeStatsReport:
        """Compute and persist a statistics snapshot to growth history."""
        return self._stats.snapshot()

    def growth_history(self) -> list[dict[str, Any]]:
        """Return the historical list of all stats snapshots."""
        return self._stats.growth_history()

    # ------------------------------------------------------------------ #
    # Describe (for Brain module handler)                                  #
    # ------------------------------------------------------------------ #

    def describe(self) -> str:
        """
        Return a brief human-readable summary of the current knowledge state.
        Used by the Brain's knowledge module handler.
        """
        report = self._stats.current()
        return report.summary()
