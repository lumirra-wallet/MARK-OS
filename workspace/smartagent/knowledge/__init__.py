"""
smartagent.knowledge — MARK's Knowledge Engine v1 (Milestone 7)
===============================================================

Transforms MARK from a system that only *remembers* information into a
system that *understands* knowledge.

The Knowledge Engine represents structured knowledge as a directed graph
of concepts (nodes) connected by typed relationships (edges). Every piece
of knowledge is backed by evidence, attributed to sources, scored for
confidence, and must pass through Mr. Smart's approval inbox before it
enters the permanent graph.

Key components
--------------
KnowledgeManager
    The single entry point for all knowledge operations. The Brain
    communicates only through this class — never by importing sub-engines
    directly. See `smartagent.knowledge.knowledge_manager`.

Concepts
    Rich knowledge nodes with metadata (title, description, category, tags,
    aliases, examples, difficulty, confidence, importance, verification
    status, revision history). See `smartagent.knowledge.concepts`.

Knowledge Graph
    In-memory directed graph supporting BFS/DFS traversal, shortest-path
    queries, merge/split, dependency and relationship lookup, and an
    adjacency export hook for future visualization. See
    `smartagent.knowledge.graph`.

Relationships
    Typed, weighted, confidence-scored directed edges between concepts.
    15 relationship types: depends_on, part_of, related_to, contradicts,
    extends, implements, inherits, causes, uses, creates, requires,
    improves, replaces, supports, references. See
    `smartagent.knowledge.relationships`.

Sources
    Provenance tracking. Every concept traces back to at least one source
    (manual entry, memory, research, books, documentation, etc.). See
    `smartagent.knowledge.sources`.

Evidence
    Supporting facts for each concept, each scored by type, strength, and
    confidence. See `smartagent.knowledge.evidence`.

Confidence Engine
    Transparent, evidence-based scoring. Score = weighted function of
    evidence quality, source reliability, contradiction penalty,
    verification bonus, age decay, and corroboration bonus. No black-box
    AI judgements. See `smartagent.knowledge.confidence`.

Knowledge Inbox
    Approval gate. All new concepts enter via `KnowledgeManager.propose_concept()`,
    pass validation and conflict detection, and wait for `approve_concept()`
    before joining the permanent graph. Nothing enters automatically. See
    `smartagent.knowledge.inbox`.

Ontology Engine
    Hierarchical category tree (e.g. Technology → Programming → Python →
    Asyncio). Categories support inheritance: a concept in a child category
    also belongs to all ancestors. See `smartagent.knowledge.ontology`.

Query Engine
    Structured queries: find_concept, find_related, find_dependencies,
    find_contradictions, find_missing_evidence, find_low_confidence,
    find_orphans, find_duplicates, find_by_category, find_by_tag. See
    `smartagent.knowledge.queries`.

Knowledge Search
    Deterministic full-text search across title, aliases, tags, category,
    description, and summary. No embeddings, no vector databases. See
    `smartagent.knowledge.search`.

Storage
    Human-readable JSON files stored in `knowledge/` (separate from the
    memory `vault/`). One JSON file per concept, relationship, source, and
    evidence item. Inbox items persisted in `knowledge/inbox/`. See
    `smartagent.knowledge.storage`.

Statistics
    Live and historical metrics: total concepts, relationships, avg
    confidence, conflicts, pending inbox items, verified/unverified counts,
    sources, evidence, categories, and growth over time. See
    `smartagent.knowledge.statistics`.

What this module does NOT do (per the Milestone 7 spec)
--------------------------------------------------------
- No AI reasoning
- No vector databases or embeddings
- No Ollama integration
- No browser access or internet research
- No voice or vision
- No modification of Memory, Mind, Brain, Skills, Tools, or Models
"""

from smartagent.knowledge.knowledge_manager import KnowledgeManager

__all__ = ["KnowledgeManager"]
