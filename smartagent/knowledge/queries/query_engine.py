"""
QueryEngine — structured queries over the knowledge graph.

Supports the full query set from the Milestone 7 spec:
  find_concept, find_related, find_dependencies, find_contradictions,
  find_missing_evidence, find_low_confidence, find_orphans,
  find_duplicates, find_by_category, find_by_tag.

All queries are deterministic and return plain Python lists — no lazy
generators, no async, no AI. The engine reads from the current state of
storage and graph on each call to stay consistent with live updates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from smartagent.knowledge.concepts.concept import VerificationStatus
from smartagent.knowledge.relationships.relationship import RelationshipType
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept
    from smartagent.knowledge.graph.knowledge_graph import KnowledgeGraph
    from smartagent.knowledge.relationships.relationship import Relationship
    from smartagent.knowledge.storage.knowledge_storage import KnowledgeStorage

logger = get_logger(__name__)


class QueryEngine:
    """
    Provides structured query operations over the knowledge graph.

    Args:
        storage: The `KnowledgeStorage` instance for reading concepts/rels.
        graph: The in-memory `KnowledgeGraph` for relationship traversal.
    """

    def __init__(
        self,
        storage: "KnowledgeStorage",
        graph: "KnowledgeGraph",
    ) -> None:
        self._storage = storage
        self._graph = graph

    # ------------------------------------------------------------------ #
    # Core queries                                                         #
    # ------------------------------------------------------------------ #

    def find_concept(self, query: str) -> list["Concept"]:
        """
        Find concepts whose title, alias, or tags contain `query`
        (case-insensitive). Ordered by title.
        """
        q = query.lower().strip()
        results: list["Concept"] = []
        for concept in self._storage.read_all_concepts():
            if (
                q in concept.title.lower()
                or any(q in a.lower() for a in concept.aliases)
                or any(q in t.lower() for t in concept.tags)
            ):
                results.append(concept)
        results.sort(key=lambda c: c.title.lower())
        return results

    def find_related(self, concept_id: str) -> list["Concept"]:
        """
        Return all concepts directly related to `concept_id` via any
        relationship (both forward and reverse edges).
        """
        neighbor_ids = set(self._graph.neighbors(concept_id))
        neighbor_ids.update(self._graph.predecessors(concept_id))
        related: list["Concept"] = []
        for neighbor_id in neighbor_ids:
            concept = self._storage.read_concept(neighbor_id)
            if concept:
                related.append(concept)
        related.sort(key=lambda c: c.title.lower())
        return related

    def find_dependencies(self, concept_id: str) -> list["Concept"]:
        """
        Return concepts that `concept_id` directly depends on.

        Filters relationships to DEPENDS_ON and REQUIRES types only.
        """
        rel_ids = self._graph.relationships_for(concept_id)
        dep_concept_ids: list[str] = []
        for rel_id in rel_ids:
            rel = self._storage.read_relationship(rel_id)
            if rel and rel.from_concept_id == concept_id and rel.relation_type in (
                RelationshipType.DEPENDS_ON, RelationshipType.REQUIRES
            ):
                dep_concept_ids.append(rel.to_concept_id)
        deps: list["Concept"] = []
        for cid in dep_concept_ids:
            concept = self._storage.read_concept(cid)
            if concept:
                deps.append(concept)
        deps.sort(key=lambda c: c.title.lower())
        return deps

    def find_contradictions(self, concept_id: str) -> list["Concept"]:
        """
        Return concepts that are recorded as contradictions of `concept_id`.
        """
        concept = self._storage.read_concept(concept_id)
        if concept is None:
            return []
        contradictions: list["Concept"] = []
        for cid in concept.contradiction_ids:
            c = self._storage.read_concept(cid)
            if c:
                contradictions.append(c)
        return sorted(contradictions, key=lambda c: c.title.lower())

    def find_missing_evidence(self) -> list["Concept"]:
        """
        Return concepts that have no linked evidence records (evidence_ids empty).
        """
        return sorted(
            [c for c in self._storage.read_all_concepts() if not c.evidence_ids],
            key=lambda c: c.title.lower(),
        )

    def find_low_confidence(self, threshold: float = 0.5) -> list["Concept"]:
        """
        Return concepts with confidence strictly below `threshold`,
        ordered from lowest to highest confidence.
        """
        low = [c for c in self._storage.read_all_concepts() if c.confidence < threshold]
        return sorted(low, key=lambda c: c.confidence)

    def find_orphans(self) -> list["Concept"]:
        """
        Return concepts that have no relationships at all (isolated nodes).
        """
        orphan_ids = set(self._graph.stats().orphan_nodes)
        orphans: list["Concept"] = []
        for cid in orphan_ids:
            concept = self._storage.read_concept(cid)
            if concept:
                orphans.append(concept)
        return sorted(orphans, key=lambda c: c.title.lower())

    def find_duplicates(self) -> list[list["Concept"]]:
        """
        Find groups of concepts that likely represent the same knowledge
        (based on identical or very similar titles, case-insensitive).

        Returns a list of groups; each group contains 2+ concepts that
        are potential duplicates.
        """
        concepts = self._storage.read_all_concepts()
        title_map: dict[str, list["Concept"]] = {}
        for concept in concepts:
            key = concept.title.lower().strip()
            title_map.setdefault(key, []).append(concept)
        return [group for group in title_map.values() if len(group) > 1]

    def find_by_category(self, category_path: str) -> list["Concept"]:
        """
        Return all concepts in `category_path` or any of its sub-categories.

        Uses prefix matching so "Technology" returns concepts in
        "Technology", "Technology/Programming", etc.
        """
        results = [
            c
            for c in self._storage.read_all_concepts()
            if c.category == category_path
            or c.category.startswith(f"{category_path}/")
        ]
        return sorted(results, key=lambda c: c.title.lower())

    def find_by_tag(self, tag: str) -> list["Concept"]:
        """
        Return all concepts that have `tag` in their tags list
        (case-insensitive).
        """
        tag_lower = tag.lower()
        results = [
            c
            for c in self._storage.read_all_concepts()
            if any(t.lower() == tag_lower for t in c.tags)
        ]
        return sorted(results, key=lambda c: c.title.lower())

    def find_unverified(self) -> list["Concept"]:
        """Return all concepts not yet verified by Mr. Smart."""
        return sorted(
            [
                c
                for c in self._storage.read_all_concepts()
                if c.verification_status == VerificationStatus.UNVERIFIED
            ],
            key=lambda c: c.confidence,
        )

    def count_relationships_for(self, concept_id: str) -> int:
        """Count the number of relationships involving `concept_id`."""
        return len(self._graph.relationships_for(concept_id))
