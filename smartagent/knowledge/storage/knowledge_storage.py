"""
KnowledgeStorage — filesystem-based persistence for knowledge artefacts.

Knowledge is stored separately from Memory (SMARTAGENT.md and Milestone 7
spec: Memory remains `vault/`; Knowledge becomes `knowledge/`). Each
artefact type gets its own subdirectory:

    knowledge/
    ├── concepts/          one JSON file per concept
    ├── relationships/     one JSON file per relationship
    ├── sources/           one JSON file per source
    ├── evidence/          one JSON file per evidence item
    └── inbox/             one JSON file per inbox item (pending approval)

JSON is chosen over Markdown for concepts because they have deeply
structured, nested data (revision history, lists of IDs, nested enums)
that would be awkward and error-prone to hand-roll as Markdown frontmatter.
The files remain human-readable and editable in any text editor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smartagent.knowledge.concepts.concept import Concept
from smartagent.knowledge.evidence.evidence import Evidence
from smartagent.knowledge.relationships.relationship import Relationship
from smartagent.knowledge.sources.source import Source
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# Subdirectory names inside the knowledge root.
_DIR_CONCEPTS = "concepts"
_DIR_RELATIONSHIPS = "relationships"
_DIR_SOURCES = "sources"
_DIR_EVIDENCE = "evidence"
_DIR_INBOX = "inbox"


class KnowledgeStorage:
    """
    Manages the on-disk knowledge store.

    Args:
        root: Root directory for all knowledge data. Configurable so tests
            can use isolated temp directories without touching the real store.
    """

    def __init__(self, root: str | Path = "knowledge") -> None:
        self.root = Path(root)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Create the knowledge root and all required subdirectories."""
        for subdir in (
            _DIR_CONCEPTS,
            _DIR_RELATIONSHIPS,
            _DIR_SOURCES,
            _DIR_EVIDENCE,
            _DIR_INBOX,
        ):
            (self.root / subdir).mkdir(parents=True, exist_ok=True)
        logger.info("KnowledgeStorage ready at %s", self.root)

    # ------------------------------------------------------------------ #
    # Generic helpers                                                      #
    # ------------------------------------------------------------------ #

    def _path(self, subdir: str, item_id: str) -> Path:
        return self.root / subdir / f"{item_id}.json"

    def _write(self, subdir: str, item_id: str, data: dict[str, Any]) -> Path:
        path = self._path(subdir, item_id)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def _read(self, subdir: str, item_id: str) -> dict[str, Any] | None:
        path = self._path(subdir, item_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _delete(self, subdir: str, item_id: str) -> bool:
        path = self._path(subdir, item_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _read_all(self, subdir: str) -> list[dict[str, Any]]:
        directory = self.root / subdir
        result: list[dict[str, Any]] = []
        if not directory.exists():
            return result
        for path in sorted(directory.glob("*.json")):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read %s: %s", path, exc)
        return result

    # ------------------------------------------------------------------ #
    # Concepts                                                             #
    # ------------------------------------------------------------------ #

    def write_concept(self, concept: Concept) -> Path:
        """Persist `concept` to disk."""
        path = self._write(_DIR_CONCEPTS, concept.id, concept.to_dict())
        logger.info("Wrote concept %s (%r)", concept.id, concept.title)
        return path

    def read_concept(self, concept_id: str) -> Concept | None:
        """Load and return a concept by ID, or None if not found."""
        data = self._read(_DIR_CONCEPTS, concept_id)
        if data is None:
            return None
        return Concept.from_dict(data)

    def delete_concept(self, concept_id: str) -> bool:
        """Delete a concept file. Returns True if deleted, False if not found."""
        deleted = self._delete(_DIR_CONCEPTS, concept_id)
        if deleted:
            logger.info("Deleted concept %s", concept_id)
        return deleted

    def read_all_concepts(self) -> list[Concept]:
        """Load every persisted concept."""
        return [Concept.from_dict(d) for d in self._read_all(_DIR_CONCEPTS)]

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    def write_relationship(self, rel: Relationship) -> Path:
        """Persist `rel` to disk."""
        path = self._write(_DIR_RELATIONSHIPS, rel.id, rel.to_dict())
        logger.info("Wrote relationship %s (%s → %s)", rel.id, rel.from_concept_id, rel.to_concept_id)
        return path

    def read_relationship(self, rel_id: str) -> Relationship | None:
        """Load and return a relationship by ID, or None if not found."""
        data = self._read(_DIR_RELATIONSHIPS, rel_id)
        if data is None:
            return None
        return Relationship.from_dict(data)

    def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship file."""
        deleted = self._delete(_DIR_RELATIONSHIPS, rel_id)
        if deleted:
            logger.info("Deleted relationship %s", rel_id)
        return deleted

    def read_all_relationships(self) -> list[Relationship]:
        """Load every persisted relationship."""
        return [Relationship.from_dict(d) for d in self._read_all(_DIR_RELATIONSHIPS)]

    # ------------------------------------------------------------------ #
    # Sources                                                              #
    # ------------------------------------------------------------------ #

    def write_source(self, source: Source) -> Path:
        """Persist `source` to disk."""
        path = self._write(_DIR_SOURCES, source.id, source.to_dict())
        logger.info("Wrote source %s", source.id)
        return path

    def read_source(self, source_id: str) -> Source | None:
        """Load and return a source by ID, or None if not found."""
        data = self._read(_DIR_SOURCES, source_id)
        if data is None:
            return None
        return Source.from_dict(data)

    def delete_source(self, source_id: str) -> bool:
        """Delete a source file."""
        deleted = self._delete(_DIR_SOURCES, source_id)
        if deleted:
            logger.info("Deleted source %s", source_id)
        return deleted

    def read_all_sources(self) -> list[Source]:
        """Load every persisted source."""
        return [Source.from_dict(d) for d in self._read_all(_DIR_SOURCES)]

    # ------------------------------------------------------------------ #
    # Evidence                                                             #
    # ------------------------------------------------------------------ #

    def write_evidence(self, evidence: Evidence) -> Path:
        """Persist `evidence` to disk."""
        path = self._write(_DIR_EVIDENCE, evidence.id, evidence.to_dict())
        logger.info("Wrote evidence %s for concept %s", evidence.id, evidence.concept_id)
        return path

    def read_evidence(self, evidence_id: str) -> Evidence | None:
        """Load and return an evidence item by ID, or None if not found."""
        data = self._read(_DIR_EVIDENCE, evidence_id)
        if data is None:
            return None
        return Evidence.from_dict(data)

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete an evidence file."""
        deleted = self._delete(_DIR_EVIDENCE, evidence_id)
        if deleted:
            logger.info("Deleted evidence %s", evidence_id)
        return deleted

    def read_all_evidence(self) -> list[Evidence]:
        """Load every persisted evidence item."""
        return [Evidence.from_dict(d) for d in self._read_all(_DIR_EVIDENCE)]

    def read_evidence_for_concept(self, concept_id: str) -> list[Evidence]:
        """Load all evidence items linked to a specific concept."""
        return [e for e in self.read_all_evidence() if e.concept_id == concept_id]

    # ------------------------------------------------------------------ #
    # Inbox items                                                          #
    # ------------------------------------------------------------------ #

    def write_inbox_item(self, item_id: str, data: dict[str, Any]) -> Path:
        """Persist a raw inbox item dictionary to disk."""
        path = self._write(_DIR_INBOX, item_id, data)
        logger.info("Wrote inbox item %s", item_id)
        return path

    def read_inbox_item(self, item_id: str) -> dict[str, Any] | None:
        """Load and return an inbox item dictionary by ID."""
        return self._read(_DIR_INBOX, item_id)

    def delete_inbox_item(self, item_id: str) -> bool:
        """Remove an inbox item file (after approval or rejection)."""
        deleted = self._delete(_DIR_INBOX, item_id)
        if deleted:
            logger.info("Deleted inbox item %s", item_id)
        return deleted

    def read_all_inbox_items(self) -> list[dict[str, Any]]:
        """Load all pending inbox items."""
        return self._read_all(_DIR_INBOX)
