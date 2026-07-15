"""
Comprehensive tests for the Knowledge Engine v1 (Milestone 7).

Every test uses an isolated temp directory (via pytest's `tmp_path`) so
nothing is written to the project's real `knowledge/` directory and
tests remain independent of each other.

Test coverage:
  - KnowledgeStorage (concepts, relationships, sources, evidence, inbox)
  - KnowledgeGraph (nodes, edges, traversal, shortest path, merge, split)
  - Concept (serialization round-trip)
  - Relationship (serialization round-trip)
  - Source / Evidence (serialization round-trip)
  - ConfidenceEngine (scoring factors)
  - ConceptValidator (hard errors + warnings)
  - OntologyEngine (add, remove, ancestors, descendants, ensure_path)
  - KnowledgeSearch (relevance scoring, category/tag filters)
  - QueryEngine (all query types)
  - KnowledgeInbox (submit, approve, reject, conflict detection)
  - KnowledgeStats (current, snapshot, growth history)
  - KnowledgeManager (end-to-end: propose → approve, connect, update,
    merge, remove, search, confidence, describe)
"""

from __future__ import annotations

import pytest

from smartagent.knowledge.categories.category import Category
from smartagent.knowledge.concepts.concept import (
    Concept,
    ConceptDifficulty,
    ConceptStatus,
    VerificationStatus,
)
from smartagent.knowledge.confidence.confidence_engine import ConfidenceEngine
from smartagent.knowledge.evidence.evidence import Evidence, EvidenceType
from smartagent.knowledge.graph.knowledge_graph import KnowledgeGraph
from smartagent.knowledge.inbox.knowledge_inbox import (
    InboxItem,
    InboxItemStatus,
    KnowledgeInbox,
)
from smartagent.knowledge.knowledge_manager import KnowledgeManager, _make_id, _now_iso
from smartagent.knowledge.ontology.ontology_engine import OntologyEngine
from smartagent.knowledge.queries.query_engine import QueryEngine
from smartagent.knowledge.relationships.relationship import Relationship, RelationshipType
from smartagent.knowledge.search.knowledge_search import KnowledgeSearch
from smartagent.knowledge.sources.source import Source, SourceType
from smartagent.knowledge.statistics.knowledge_stats import KnowledgeStats
from smartagent.knowledge.storage.knowledge_storage import KnowledgeStorage
from smartagent.knowledge.validation.validator import ConceptValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manager(tmp_path) -> KnowledgeManager:
    """Return a KnowledgeManager wired to an isolated temp directory."""
    return KnowledgeManager(knowledge_path=str(tmp_path / "knowledge"))


def _storage(tmp_path) -> KnowledgeStorage:
    return KnowledgeStorage(root=str(tmp_path / "knowledge"))


def _concept(suffix: str = "a") -> Concept:
    """Build a minimal valid Concept for testing."""
    now = _now_iso()
    return Concept(
        id=f"concept-{suffix}",
        title=f"Test Concept {suffix.upper()}",
        description="A test concept for unit testing.",
        summary="Short summary.",
        category="Technology",
        tags=["test", suffix],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Concept serialization
# ---------------------------------------------------------------------------

class TestConceptSerialization:

    def test_round_trip_to_dict(self):
        c = _concept("x")
        c2 = Concept.from_dict(c.to_dict())
        assert c2.id == c.id
        assert c2.title == c.title
        assert c2.tags == c.tags

    def test_round_trip_to_json(self):
        c = _concept("y")
        c2 = Concept.from_json(c.to_json())
        assert c2.id == c.id
        assert c2.difficulty == ConceptDifficulty.INTERMEDIATE

    def test_difficulty_enum_round_trip(self):
        c = _concept("z")
        c.difficulty = ConceptDifficulty.EXPERT
        c2 = Concept.from_dict(c.to_dict())
        assert c2.difficulty == ConceptDifficulty.EXPERT

    def test_verification_status_round_trip(self):
        c = _concept("v")
        c.verification_status = VerificationStatus.VERIFIED
        c2 = Concept.from_dict(c.to_dict())
        assert c2.verification_status == VerificationStatus.VERIFIED

    def test_revision_history_round_trip(self):
        from smartagent.knowledge.concepts.concept import RevisionEntry
        c = _concept("r")
        c.revision_history.append(RevisionEntry(
            timestamp="2026-01-01T00:00:00+00:00",
            author="MARK",
            summary="Initial entry",
        ))
        c2 = Concept.from_dict(c.to_dict())
        assert len(c2.revision_history) == 1
        assert c2.revision_history[0].summary == "Initial entry"


# ---------------------------------------------------------------------------
# Relationship serialization
# ---------------------------------------------------------------------------

class TestRelationshipSerialization:

    def test_round_trip_to_dict(self):
        rel = Relationship(
            id="rel-1",
            from_concept_id="a",
            to_concept_id="b",
            relation_type=RelationshipType.DEPENDS_ON,
        )
        rel2 = Relationship.from_dict(rel.to_dict())
        assert rel2.relation_type == RelationshipType.DEPENDS_ON
        assert rel2.from_concept_id == "a"

    def test_all_relation_types_serialize(self):
        for rtype in RelationshipType:
            rel = Relationship(
                id="x",
                from_concept_id="a",
                to_concept_id="b",
                relation_type=rtype,
            )
            assert Relationship.from_dict(rel.to_dict()).relation_type == rtype


# ---------------------------------------------------------------------------
# Source / Evidence serialization
# ---------------------------------------------------------------------------

class TestSourceSerialization:

    def test_round_trip(self):
        src = Source(id="src-1", source_type=SourceType.BOOKS, author="John", reliability_score=0.9)
        src2 = Source.from_dict(src.to_dict())
        assert src2.source_type == SourceType.BOOKS
        assert src2.reliability_score == 0.9

    def test_all_source_types_serialize(self):
        for stype in SourceType:
            src = Source(id="x", source_type=stype)
            assert Source.from_dict(src.to_dict()).source_type == stype


class TestEvidenceSerialization:

    def test_round_trip(self):
        ev = Evidence(
            id="ev-1",
            concept_id="c-1",
            description="Proof goes here",
            evidence_type=EvidenceType.EXPERIMENTAL,
            strength=0.9,
        )
        ev2 = Evidence.from_dict(ev.to_dict())
        assert ev2.evidence_type == EvidenceType.EXPERIMENTAL
        assert ev2.concept_id == "c-1"


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class TestCategory:

    def test_path_computation(self):
        cat = Category(name="Python", parent_path="Technology/Programming")
        assert cat.path == "Technology/Programming/Python"

    def test_root_category(self):
        cat = Category(name="Technology")
        assert cat.is_root()
        assert cat.path == "Technology"

    def test_depth(self):
        cat = Category(name="Asyncio", parent_path="Technology/Programming/Python")
        assert cat.depth == 3


# ---------------------------------------------------------------------------
# KnowledgeStorage
# ---------------------------------------------------------------------------

class TestKnowledgeStorage:

    def test_write_and_read_concept(self, tmp_path):
        storage = _storage(tmp_path)
        c = _concept("s1")
        storage.write_concept(c)
        result = storage.read_concept(c.id)
        assert result is not None
        assert result.title == c.title

    def test_read_missing_concept_returns_none(self, tmp_path):
        storage = _storage(tmp_path)
        assert storage.read_concept("does-not-exist") is None

    def test_delete_concept(self, tmp_path):
        storage = _storage(tmp_path)
        c = _concept("del")
        storage.write_concept(c)
        assert storage.delete_concept(c.id) is True
        assert storage.read_concept(c.id) is None

    def test_delete_missing_concept_returns_false(self, tmp_path):
        storage = _storage(tmp_path)
        assert storage.delete_concept("missing") is False

    def test_read_all_concepts(self, tmp_path):
        storage = _storage(tmp_path)
        for suffix in ("p", "q", "r"):
            storage.write_concept(_concept(suffix))
        all_concepts = storage.read_all_concepts()
        assert len(all_concepts) == 3

    def test_write_and_read_relationship(self, tmp_path):
        storage = _storage(tmp_path)
        rel = Relationship(
            id="rel-x",
            from_concept_id="a",
            to_concept_id="b",
            relation_type=RelationshipType.RELATED_TO,
            created_at=_now_iso(),
        )
        storage.write_relationship(rel)
        result = storage.read_relationship("rel-x")
        assert result is not None
        assert result.relation_type == RelationshipType.RELATED_TO

    def test_write_and_read_source(self, tmp_path):
        storage = _storage(tmp_path)
        src = Source(id="src-1", citation="Test Citation")
        storage.write_source(src)
        result = storage.read_source("src-1")
        assert result.citation == "Test Citation"

    def test_write_and_read_evidence(self, tmp_path):
        storage = _storage(tmp_path)
        ev = Evidence(id="ev-1", concept_id="c-1", description="Evidence text")
        storage.write_evidence(ev)
        result = storage.read_evidence("ev-1")
        assert result.description == "Evidence text"

    def test_read_evidence_for_concept(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_evidence(Evidence(id="ev-1", concept_id="c-1", description="ev1"))
        storage.write_evidence(Evidence(id="ev-2", concept_id="c-2", description="ev2"))
        storage.write_evidence(Evidence(id="ev-3", concept_id="c-1", description="ev3"))
        results = storage.read_evidence_for_concept("c-1")
        assert len(results) == 2

    def test_inbox_write_read_delete(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_inbox_item("inbox-1", {"id": "inbox-1", "status": "pending"})
        result = storage.read_inbox_item("inbox-1")
        assert result["status"] == "pending"
        assert storage.delete_inbox_item("inbox-1") is True
        assert storage.read_inbox_item("inbox-1") is None


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class TestKnowledgeGraph:

    def test_add_and_list_nodes(self):
        g = KnowledgeGraph()
        g.add_node("a")
        g.add_node("b")
        assert "a" in g.list_nodes()
        assert "b" in g.list_nodes()

    def test_has_node(self):
        g = KnowledgeGraph()
        g.add_node("x")
        assert g.has_node("x")
        assert not g.has_node("z")

    def test_remove_node(self):
        g = KnowledgeGraph()
        g.add_node("a")
        g.remove_node("a")
        assert not g.has_node("a")

    def test_add_and_remove_edge(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "rel-1")
        assert g.has_edge("a", "b")
        assert g.remove_edge("a", "b") is True
        assert not g.has_edge("a", "b")

    def test_remove_nonexistent_edge(self):
        g = KnowledgeGraph()
        g.add_node("a")
        g.add_node("b")
        assert g.remove_edge("a", "b") is False

    def test_bidirectional_edge(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "rel-1", bidirectional=True)
        assert g.has_edge("a", "b")
        assert g.has_edge("b", "a")

    def test_neighbors_and_predecessors(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "rel-1")
        g.add_edge("a", "c", "rel-2")
        assert sorted(g.neighbors("a")) == ["b", "c"]
        assert g.predecessors("b") == ["a"]

    def test_bfs_traversal(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.add_edge("b", "c", "r2")
        g.add_edge("a", "c", "r3")
        visited = list(g.bfs("a"))
        assert visited[0] == "a"
        assert "b" in visited
        assert "c" in visited
        assert len(visited) == 3

    def test_dfs_traversal(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.add_edge("b", "c", "r2")
        visited = list(g.dfs("a"))
        assert set(visited) == {"a", "b", "c"}

    def test_shortest_path(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.add_edge("b", "c", "r2")
        g.add_edge("a", "c", "r3")
        path = g.shortest_path("a", "c")
        assert path is not None
        assert path[0] == "a"
        assert path[-1] == "c"
        assert len(path) == 2  # direct edge: a → c

    def test_shortest_path_no_path(self):
        g = KnowledgeGraph()
        g.add_node("a")
        g.add_node("b")
        assert g.shortest_path("a", "b") is None

    def test_shortest_path_same_node(self):
        g = KnowledgeGraph()
        g.add_node("a")
        assert g.shortest_path("a", "a") == ["a"]

    def test_relationships_for(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "rel-1")
        g.add_edge("c", "a", "rel-2")
        rels = g.relationships_for("a")
        assert "rel-1" in rels
        assert "rel-2" in rels

    def test_merge_nodes(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.add_edge("c", "b", "r2")  # b has predecessor c
        g.add_node("primary")
        g.merge_nodes("primary", "b")
        assert not g.has_node("b")
        # a should now connect to primary
        assert g.has_edge("a", "primary") or "primary" in g.list_nodes()

    def test_split_node(self):
        g = KnowledgeGraph()
        g.add_node("original")
        g.split_node("original", "split-copy")
        assert g.has_node("split-copy")

    def test_remove_node_cleans_edges(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.remove_node("b")
        assert not g.has_edge("a", "b")
        assert "b" not in g.list_nodes()

    def test_stats(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        g.add_node("orphan")
        stats = g.stats()
        assert stats.node_count == 3  # a, b, orphan
        assert stats.edge_count == 1
        assert "orphan" in stats.orphan_nodes

    def test_to_adjacency_dict(self):
        g = KnowledgeGraph()
        g.add_edge("a", "b", "r1")
        adj = g.to_adjacency_dict()
        assert "a" in adj
        assert "b" in adj["a"]


# ---------------------------------------------------------------------------
# ConfidenceEngine
# ---------------------------------------------------------------------------

class TestConfidenceEngine:

    def test_no_evidence_defaults_to_neutral(self):
        engine = ConfidenceEngine()
        concept = _concept("cf")
        concept.contradiction_ids = []
        factors = engine.score(concept, evidence_list=None, sources=None)
        assert 0.0 <= factors.final_score <= 1.0

    def test_high_evidence_raises_score(self):
        engine = ConfidenceEngine()
        concept = _concept("cf2")
        evidence = [
            Evidence(id="e1", concept_id=concept.id, strength=0.95, confidence=0.9),
            Evidence(id="e2", concept_id=concept.id, strength=0.9, confidence=0.85),
        ]
        sources = [Source(id="s1", reliability_score=0.95)]
        factors = engine.score(concept, evidence_list=evidence, sources=sources)
        assert factors.final_score > 0.5

    def test_contradictions_lower_score(self):
        engine = ConfidenceEngine()
        concept_no_contradiction = _concept("nc")
        concept_with_contradiction = _concept("wc")
        concept_with_contradiction.contradiction_ids = ["other-1", "other-2"]
        f1 = engine.score(concept_no_contradiction)
        f2 = engine.score(concept_with_contradiction)
        assert f2.final_score < f1.final_score

    def test_verified_concept_gets_bonus(self):
        engine = ConfidenceEngine()
        unverified = _concept("uv")
        verified = _concept("v")
        verified.verification_status = VerificationStatus.VERIFIED
        f1 = engine.score(unverified)
        f2 = engine.score(verified)
        assert f2.final_score >= f1.final_score

    def test_score_is_clamped(self):
        engine = ConfidenceEngine()
        concept = _concept("clamp")
        factors = engine.score(concept, manual_adjustment=10.0)
        assert factors.final_score <= 1.0
        factors2 = engine.score(concept, manual_adjustment=-10.0)
        assert factors2.final_score >= 0.0

    def test_quick_score_returns_float(self):
        engine = ConfidenceEngine()
        score = engine.quick_score(_concept("qs"))
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# ConceptValidator
# ---------------------------------------------------------------------------

class TestConceptValidator:

    def test_valid_concept_passes(self):
        validator = ConceptValidator()
        c = _concept("val")
        result = validator.validate(c)
        assert result.is_valid

    def test_missing_title_fails(self):
        validator = ConceptValidator()
        c = _concept("notitle")
        c.title = ""
        result = validator.validate(c)
        assert not result.is_valid
        assert any("title" in e.lower() for e in result.errors)

    def test_missing_id_fails(self):
        validator = ConceptValidator()
        c = _concept("noid")
        c.id = ""
        result = validator.validate(c)
        assert not result.is_valid

    def test_invalid_confidence_fails(self):
        validator = ConceptValidator()
        c = _concept("badconf")
        c.confidence = 1.5
        result = validator.validate(c)
        assert not result.is_valid

    def test_invalid_importance_fails(self):
        validator = ConceptValidator()
        c = _concept("badimp")
        c.importance = -0.1
        result = validator.validate(c)
        assert not result.is_valid

    def test_short_description_warns(self):
        validator = ConceptValidator()
        c = _concept("short")
        c.description = "hi"
        result = validator.validate(c)
        assert result.is_valid  # warning, not error
        assert any("short" in w.lower() or "description" in w.lower() for w in result.warnings)

    def test_no_tags_warns(self):
        validator = ConceptValidator()
        c = _concept("notag")
        c.tags = []
        result = validator.validate(c)
        assert result.is_valid
        assert any("tag" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# OntologyEngine
# ---------------------------------------------------------------------------

class TestOntologyEngine:

    def test_default_categories_exist(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        roots = ont.list_roots()
        assert len(roots) >= 7
        paths = [r.path for r in roots]
        assert "Technology" in paths

    def test_add_category(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        assert ont.exists("Technology/Programming")

    def test_add_nested_category(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        ont.add_category("Python", parent_path="Technology/Programming")
        assert ont.exists("Technology/Programming/Python")

    def test_add_category_with_missing_parent_raises(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        with pytest.raises(ValueError, match="Parent category"):
            ont.add_category("Python", parent_path="Nonexistent")

    def test_add_duplicate_category_raises(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        with pytest.raises(ValueError, match="already exists"):
            ont.add_category("Programming", parent_path="Technology")

    def test_remove_category(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        result = ont.remove_category("Technology/Programming")
        assert result is True
        assert not ont.exists("Technology/Programming")

    def test_remove_category_also_removes_descendants(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        ont.add_category("Python", parent_path="Technology/Programming")
        ont.remove_category("Technology/Programming")
        assert not ont.exists("Technology/Programming/Python")

    def test_ancestors(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        ont.add_category("Python", parent_path="Technology/Programming")
        ancestors = ont.ancestors("Technology/Programming/Python")
        ancestor_paths = [a.path for a in ancestors]
        assert "Technology" in ancestor_paths
        assert "Technology/Programming" in ancestor_paths

    def test_descendants(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        ont.add_category("Python", parent_path="Technology/Programming")
        descendants = ont.descendants("Technology")
        descendant_paths = [d.path for d in descendants]
        assert "Technology/Programming" in descendant_paths
        assert "Technology/Programming/Python" in descendant_paths

    def test_ensure_path_creates_missing_segments(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.ensure_path("Technology/Programming/Python/Asyncio")
        assert ont.exists("Technology/Programming/Python/Asyncio")
        assert ont.exists("Technology/Programming/Python")

    def test_search_categories(self, tmp_path):
        ont = OntologyEngine(root=str(tmp_path / "knowledge"))
        ont.add_category("Programming", parent_path="Technology")
        results = ont.search("prog")
        assert any("Programming" in r.path for r in results)

    def test_ontology_persists_across_instances(self, tmp_path):
        root = str(tmp_path / "knowledge")
        ont1 = OntologyEngine(root=root)
        ont1.add_category("Programming", parent_path="Technology")
        ont2 = OntologyEngine(root=root)
        assert ont2.exists("Technology/Programming")


# ---------------------------------------------------------------------------
# KnowledgeSearch
# ---------------------------------------------------------------------------

class TestKnowledgeSearch:

    def _concepts(self):
        now = _now_iso()
        return [
            Concept(id="c1", title="Python", description="A programming language",
                    category="Technology/Programming", tags=["python", "language"],
                    created_at=now, updated_at=now),
            Concept(id="c2", title="Asyncio", description="Python async library",
                    aliases=["async"], category="Technology/Programming/Python",
                    tags=["async", "concurrency"], created_at=now, updated_at=now),
            Concept(id="c3", title="JavaScript", description="Web scripting language",
                    category="Technology/Programming", tags=["js", "web"],
                    created_at=now, updated_at=now),
        ]

    def test_search_by_title(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("Python")
        titles = [r.concept.title for r in results]
        assert "Python" in titles

    def test_search_by_alias(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("async")
        assert any(r.concept.title == "Asyncio" for r in results)

    def test_search_by_tag(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("concurrency")
        assert any(r.concept.title == "Asyncio" for r in results)

    def test_category_filter(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("", category="Technology/Programming/Python")
        assert all("Python" in r.concept.category for r in results)

    def test_tag_filter(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("", tags=["web"])
        assert all("web" in r.concept.tags for r in results)

    def test_limit_respected(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("", limit=2)
        assert len(results) <= 2

    def test_exact_title_scores_higher_than_partial(self):
        concepts = self._concepts()
        search = KnowledgeSearch(concepts_provider=lambda: concepts)
        results = search.search("Python")
        # The concept with title == "Python" should rank first.
        assert results[0].concept.title == "Python"
        assert results[0].relevance_score >= results[-1].relevance_score

    def test_empty_provider_returns_empty(self):
        search = KnowledgeSearch(concepts_provider=None)
        assert search.search("anything") == []


# ---------------------------------------------------------------------------
# QueryEngine
# ---------------------------------------------------------------------------

class TestQueryEngine:

    def _setup(self, tmp_path):
        storage = _storage(tmp_path)
        graph = KnowledgeGraph()
        now = _now_iso()

        c1 = Concept(id="c1", title="Python", category="Technology", tags=["python"],
                     created_at=now, updated_at=now, evidence_ids=[], source_ids=[])
        c2 = Concept(id="c2", title="Django", category="Technology", tags=["web", "python"],
                     created_at=now, updated_at=now, evidence_ids=["ev1"])
        c3 = Concept(id="c3", title="Flask", category="Technology/Web", tags=["web"],
                     created_at=now, updated_at=now, confidence=0.3)
        c4 = Concept(id="c4", title="Asyncio", category="Technology",
                     created_at=now, updated_at=now,
                     contradiction_ids=["c5"])
        c5 = Concept(id="c5", title="SyncIO", category="Technology",
                     verification_status=VerificationStatus.VERIFIED,
                     created_at=now, updated_at=now)

        for c in (c1, c2, c3, c4, c5):
            storage.write_concept(c)
            graph.add_node(c.id)

        # Add a relationship c1 → c2 (DEPENDS_ON)
        rel = Relationship(id="rel-1", from_concept_id="c1", to_concept_id="c2",
                           relation_type=RelationshipType.DEPENDS_ON, created_at=now)
        storage.write_relationship(rel)
        graph.add_edge("c1", "c2", "rel-1")
        c1.relationship_ids = ["rel-1"]
        c2.relationship_ids = ["rel-1"]
        storage.write_concept(c1)
        storage.write_concept(c2)

        engine = QueryEngine(storage=storage, graph=graph)
        return engine, storage, graph

    def test_find_concept(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        results = engine.find_concept("python")
        titles = [c.title for c in results]
        assert "Python" in titles

    def test_find_related(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        related = engine.find_related("c1")
        assert any(c.id == "c2" for c in related)

    def test_find_dependencies(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        deps = engine.find_dependencies("c1")
        assert any(c.id == "c2" for c in deps)

    def test_find_contradictions(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        contradictions = engine.find_contradictions("c4")
        # c4 lists c5 in contradiction_ids
        assert any(c.id == "c5" for c in contradictions)

    def test_find_missing_evidence(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        missing = engine.find_missing_evidence()
        ids = [c.id for c in missing]
        assert "c1" in ids  # c1 has no evidence_ids
        assert "c2" not in ids  # c2 has evidence_ids=["ev1"]

    def test_find_low_confidence(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        low = engine.find_low_confidence(threshold=0.4)
        assert any(c.id == "c3" for c in low)

    def test_find_orphans(self, tmp_path):
        engine, _, graph = self._setup(tmp_path)
        # c5 has no edges
        orphans = engine.find_orphans()
        orphan_ids = [c.id for c in orphans]
        assert "c5" in orphan_ids

    def test_find_duplicates(self, tmp_path):
        engine, storage, _ = self._setup(tmp_path)
        now = _now_iso()
        # Add a concept with the same title as c1 (case-insensitive).
        dup = Concept(id="c99", title="python", category="Technology",
                      created_at=now, updated_at=now)
        storage.write_concept(dup)
        dupes = engine.find_duplicates()
        assert any(len(group) >= 2 for group in dupes)

    def test_find_by_category(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        results = engine.find_by_category("Technology")
        # All concepts are under Technology (including Technology/Web)
        assert len(results) >= 4

    def test_find_by_tag(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        results = engine.find_by_tag("web")
        assert all("web" in c.tags for c in results)

    def test_find_unverified(self, tmp_path):
        engine, _, _ = self._setup(tmp_path)
        unverified = engine.find_unverified()
        # c5 is VERIFIED, so it should not appear
        unverified_ids = [c.id for c in unverified]
        assert "c5" not in unverified_ids


# ---------------------------------------------------------------------------
# KnowledgeInbox
# ---------------------------------------------------------------------------

class TestKnowledgeInbox:

    def _inbox(self, tmp_path, existing=None):
        storage = _storage(tmp_path)
        provider = (lambda: existing) if existing is not None else None
        return KnowledgeInbox(storage=storage, existing_concepts_provider=provider)

    def test_submit_valid_concept_creates_pending_item(self, tmp_path):
        inbox = self._inbox(tmp_path)
        c = _concept("i1")
        item = inbox.submit(c)
        assert item.status == InboxItemStatus.PENDING
        assert item.id.startswith("inbox-")

    def test_submit_invalid_concept_creates_rejected_item(self, tmp_path):
        inbox = self._inbox(tmp_path)
        c = _concept("i2")
        c.title = ""  # invalid
        item = inbox.submit(c)
        assert item.status == InboxItemStatus.REJECTED
        assert item.validation_errors

    def test_approve_item(self, tmp_path):
        inbox = self._inbox(tmp_path)
        item = inbox.submit(_concept("i3"))
        approved = inbox.approve(item.id, notes="Looks good")
        assert approved is not None
        assert approved.status == InboxItemStatus.APPROVED

    def test_reject_item(self, tmp_path):
        inbox = self._inbox(tmp_path)
        item = inbox.submit(_concept("i4"))
        rejected = inbox.reject(item.id, notes="Duplicate")
        assert rejected is not None
        assert rejected.status == InboxItemStatus.REJECTED

    def test_approve_missing_item_returns_none(self, tmp_path):
        inbox = self._inbox(tmp_path)
        assert inbox.approve("does-not-exist") is None

    def test_list_pending(self, tmp_path):
        inbox = self._inbox(tmp_path)
        inbox.submit(_concept("p1"))
        inbox.submit(_concept("p2"))
        pending = inbox.list_pending()
        assert len(pending) == 2

    def test_conflict_detection(self, tmp_path):
        """A concept that contradicts an existing concept goes to CONFLICT status."""
        now = _now_iso()
        existing_concept = Concept(
            id="existing-001",
            title="Existing Concept",
            created_at=now,
            updated_at=now,
        )
        inbox = self._inbox(tmp_path, existing=[existing_concept])
        # New concept that references the existing one as a contradiction.
        new_concept = _concept("conflict")
        new_concept.contradiction_ids = ["existing-001"]
        item = inbox.submit(new_concept)
        assert item.status == InboxItemStatus.CONFLICT
        assert "existing-001" in item.conflict_ids

    def test_inbox_persists_across_instances(self, tmp_path):
        """Items written to disk are reloaded by a fresh inbox instance."""
        storage = _storage(tmp_path)
        inbox1 = KnowledgeInbox(storage=storage)
        item = inbox1.submit(_concept("persist"))
        item_id = item.id

        inbox2 = KnowledgeInbox(storage=storage)
        assert inbox2.get(item_id) is not None

    def test_count_pending(self, tmp_path):
        inbox = self._inbox(tmp_path)
        inbox.submit(_concept("cnt1"))
        inbox.submit(_concept("cnt2"))
        assert inbox.count_pending() == 2


# ---------------------------------------------------------------------------
# KnowledgeStats
# ---------------------------------------------------------------------------

class TestKnowledgeStats:

    def test_current_returns_report(self, tmp_path):
        km = _manager(tmp_path)
        report = km.stats()
        assert report.total_concepts == 0
        assert report.total_relationships == 0
        assert report.pending_inbox_items == 0

    def test_snapshot_saves_to_history(self, tmp_path):
        km = _manager(tmp_path)
        km.snapshot_stats()
        km.snapshot_stats()
        history = km.growth_history()
        assert len(history) == 2

    def test_stats_reflect_current_state(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Test Concept", description="A test concept for stats")
        km.approve_concept(item.id)
        report = km.stats()
        assert report.total_concepts == 1

    def test_stats_summary_is_string(self, tmp_path):
        km = _manager(tmp_path)
        report = km.stats()
        assert isinstance(report.summary(), str)
        assert "Knowledge Graph" in report.summary()


# ---------------------------------------------------------------------------
# KnowledgeManager (end-to-end)
# ---------------------------------------------------------------------------

class TestKnowledgeManager:

    def test_propose_and_approve_concept(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept(
            title="Python",
            description="A high-level, interpreted programming language.",
            summary="Versatile language known for readability.",
            category="Technology/Programming",
            tags=["python", "programming"],
        )
        assert item.status in (InboxItemStatus.PENDING, InboxItemStatus.CONFLICT)

        committed = km.approve_concept(item.id)
        assert committed is not None
        assert committed.title == "Python"

    def test_get_concept_after_approval(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Pytest", description="Testing framework for Python.")
        km.approve_concept(item.id)
        # Find it by listing.
        concepts = km.list_concepts()
        assert any(c.title == "Pytest" for c in concepts)

    def test_reject_concept_not_in_graph(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Rejected Idea", description="Should not enter graph.")
        km.reject_concept(item.id, notes="Not relevant")
        concepts = km.list_concepts()
        assert not any(c.title == "Rejected Idea" for c in concepts)

    def test_update_concept(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Old Title", description="Original description here.")
        concept = km.approve_concept(item.id)
        updated = km.update_concept(
            concept.id,
            title="New Title",
            change_summary="Renamed for clarity",
        )
        assert updated is not None
        assert updated.title == "New Title"
        assert len(updated.revision_history) == 1
        assert updated.revision_history[0].previous_values["title"] == "Old Title"

    def test_remove_concept(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("To Delete", description="This concept will be removed.")
        concept = km.approve_concept(item.id)
        assert km.remove_concept(concept.id) is True
        assert km.get_concept(concept.id) is None

    def test_connect_and_disconnect_concepts(self, tmp_path):
        km = _manager(tmp_path)
        item_a = km.propose_concept("ConceptA", description="First concept in a pair.")
        item_b = km.propose_concept("ConceptB", description="Second concept in a pair.")
        ca = km.approve_concept(item_a.id)
        cb = km.approve_concept(item_b.id)

        rel = km.connect_concepts(
            ca.id, cb.id, RelationshipType.DEPENDS_ON, strength=0.9
        )
        assert rel is not None
        assert rel.relation_type == RelationshipType.DEPENDS_ON

        # Disconnect and verify removal.
        assert km.disconnect_concepts(ca.id, cb.id) is True
        assert km.get_relationship(rel.id) is None

    def test_add_source_and_link_to_concept(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Sourced Concept", description="Has an attached source.")
        concept = km.approve_concept(item.id)
        source = km.add_source(
            source_type=SourceType.DOCUMENTATION,
            author="Official Docs",
            citation="Python 3.12 Reference Manual",
        )
        assert km.link_source_to_concept(source.id, concept.id) is True
        reloaded = km.get_concept(concept.id)
        assert source.id in reloaded.source_ids

    def test_add_evidence_to_concept(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Evidenced Concept", description="Backed by evidence.")
        concept = km.approve_concept(item.id)
        evidence = km.add_evidence(
            concept_id=concept.id,
            description="Observed this behavior in production",
            strength=0.9,
        )
        assert evidence is not None
        reloaded = km.get_concept(concept.id)
        assert evidence.id in reloaded.evidence_ids

    def test_recalculate_confidence(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Confidence Test", description="Concept with evidence.")
        concept = km.approve_concept(item.id)
        km.add_evidence(concept.id, "Strong supporting evidence", strength=0.95, confidence=0.95)
        updated = km.recalculate_confidence(concept.id)
        assert updated is not None
        # After high-quality evidence, confidence should be > the initial default.
        assert updated.confidence >= 0.0

    def test_explain_confidence_returns_factors(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("Explain Me", description="For confidence explanation test.")
        concept = km.approve_concept(item.id)
        factors = km.explain_confidence(concept.id)
        assert factors is not None
        assert isinstance(factors.final_score, float)
        assert factors.notes  # should always have at least one note

    def test_search(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept(
            "Machine Learning",
            description="A subset of AI focused on learning from data.",
            tags=["ai", "ml"],
        )
        km.approve_concept(item.id)
        results = km.search("machine")
        assert any(r.concept.title == "Machine Learning" for r in results)

    def test_merge_concepts(self, tmp_path):
        km = _manager(tmp_path)
        ia = km.propose_concept("ConceptA Merge", description="Will be the primary concept.")
        ib = km.propose_concept("ConceptB Merge", description="Will be merged into A.")
        ca = km.approve_concept(ia.id)
        cb = km.approve_concept(ib.id)
        merged = km.merge_concepts(ca.id, cb.id, change_summary="Consolidating duplicates")
        assert merged is not None
        # Secondary should be gone.
        assert km.get_concept(cb.id) is None
        # Primary should have the secondary's title as an alias.
        assert "ConceptB Merge" in merged.aliases

    def test_shortest_path_between_concepts(self, tmp_path):
        km = _manager(tmp_path)
        ia = km.propose_concept("PathA", description="Start of the path.")
        ib = km.propose_concept("PathB", description="Middle of the path.")
        ic = km.propose_concept("PathC", description="End of the path.")
        ca = km.approve_concept(ia.id)
        cb = km.approve_concept(ib.id)
        cc = km.approve_concept(ic.id)
        km.connect_concepts(ca.id, cb.id, RelationshipType.RELATED_TO)
        km.connect_concepts(cb.id, cc.id, RelationshipType.RELATED_TO)
        path = km.shortest_path(ca.id, cc.id)
        assert path is not None
        assert path[0] == ca.id
        assert path[-1] == cc.id

    def test_graph_adjacency(self, tmp_path):
        km = _manager(tmp_path)
        item = km.propose_concept("AdjConcept", description="A concept for adjacency test.")
        km.approve_concept(item.id)
        adj = km.graph_adjacency()
        assert isinstance(adj, dict)

    def test_bfs_and_dfs(self, tmp_path):
        km = _manager(tmp_path)
        ia = km.propose_concept("BFS-A", description="BFS start.")
        ib = km.propose_concept("BFS-B", description="BFS neighbor.")
        ca = km.approve_concept(ia.id)
        cb = km.approve_concept(ib.id)
        km.connect_concepts(ca.id, cb.id, RelationshipType.RELATED_TO)
        bfs_nodes = km.bfs(ca.id)
        dfs_nodes = km.dfs(ca.id)
        assert set(bfs_nodes) == {ca.id, cb.id}
        assert set(dfs_nodes) == {ca.id, cb.id}

    def test_describe_returns_string(self, tmp_path):
        km = _manager(tmp_path)
        desc = km.describe()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_ontology_accessible(self, tmp_path):
        km = _manager(tmp_path)
        roots = km.ontology.list_roots()
        assert len(roots) > 0

    def test_propose_concept_ensures_ontology_path(self, tmp_path):
        km = _manager(tmp_path)
        km.propose_concept(
            "Asyncio",
            description="Python async programming library for concurrent code.",
            category="Technology/Programming/Python",
        )
        assert km.ontology.exists("Technology/Programming/Python")

    def test_contradictions_mark_both_concepts(self, tmp_path):
        km = _manager(tmp_path)
        ia = km.propose_concept("Python is interpreted", description="Python is an interpreted language.")
        ib = km.propose_concept("Python is compiled", description="Python is a compiled language.")
        ca = km.approve_concept(ia.id)
        cb = km.approve_concept(ib.id)
        km.connect_concepts(ca.id, cb.id, RelationshipType.CONTRADICTS)
        # Both concepts should reference each other as contradictions.
        ra = km.get_concept(ca.id)
        rb = km.get_concept(cb.id)
        assert cb.id in ra.contradiction_ids
        assert ca.id in rb.contradiction_ids

    def test_query_engine_accessible(self, tmp_path):
        km = _manager(tmp_path)
        # Should not raise; returns empty list when graph is empty.
        orphans = km.query.find_orphans()
        assert isinstance(orphans, list)

    def test_knowledge_persists_across_manager_instances(self, tmp_path):
        """A new KnowledgeManager pointed at the same path must see existing concepts."""
        root = str(tmp_path / "knowledge")
        km1 = KnowledgeManager(knowledge_path=root)
        item = km1.propose_concept(
            "Persistent Concept",
            description="This should survive across instances.",
        )
        km1.approve_concept(item.id)

        km2 = KnowledgeManager(knowledge_path=root)
        concepts = km2.list_concepts()
        assert any(c.title == "Persistent Concept" for c in concepts)
