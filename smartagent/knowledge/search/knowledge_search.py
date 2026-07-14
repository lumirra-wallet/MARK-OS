"""
KnowledgeSearch — deterministic, full-text knowledge search.

Implements simple, auditable substring matching across concept fields.
No vector databases, no embeddings, no AI models — per the Milestone 7
requirement: "Implement deterministic search. Do NOT use embeddings."

Fields searched (in order of priority):
  title, aliases, tags, category, description, summary, source IDs

Results are ranked by a simple relevance score:
  - Title/alias exact match: +3
  - Title/alias partial match: +2
  - Tag match: +1.5
  - Category match: +1
  - Description/summary match: +0.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept


@dataclass
class SearchResult:
    """A single concept result from a knowledge search."""

    concept: "Concept"
    relevance_score: float = 0.0
    matched_fields: list[str] = field(default_factory=list)


class KnowledgeSearch:
    """
    Performs deterministic, keyword-based search over concepts.

    Args:
        concepts_provider: A callable that returns the current list of
            approved concepts from the graph. Called fresh on each search
            so it always sees the latest state.
    """

    def __init__(self, concepts_provider: Any = None) -> None:
        self._concepts_provider = concepts_provider

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """
        Search across all approved concepts.

        Args:
            query: Keyword string to search. Case-insensitive. May be empty
                to list all concepts (filtered by category/tags if supplied).
            category: If set, only return concepts whose category starts with
                this string (supports hierarchical prefix matching).
            tags: If set, only return concepts that have ALL of these tags.
            limit: Maximum number of results.

        Returns:
            Ranked list of `SearchResult`, most relevant first.
        """
        concepts = self._get_concepts()
        q = query.lower().strip()

        results: list[SearchResult] = []
        for concept in concepts:
            # Category filter (prefix match for hierarchy support)
            if category and not concept.category.lower().startswith(category.lower()):
                continue
            # Tag filter (all required tags must be present)
            if tags:
                concept_tags_lower = {t.lower() for t in concept.tags}
                if not all(t.lower() in concept_tags_lower for t in tags):
                    continue

            score, matched = self._score(concept, q)
            if q == "" or score > 0:
                results.append(SearchResult(concept=concept, relevance_score=score, matched_fields=matched))

        results.sort(key=lambda r: (-r.relevance_score, r.concept.title.lower()))
        return results[:limit]

    def _get_concepts(self) -> list["Concept"]:
        """Safely retrieve concepts from the provider."""
        if self._concepts_provider is None:
            return []
        try:
            return self._concepts_provider()
        except Exception:  # noqa: BLE001
            return []

    def _score(self, concept: "Concept", query: str) -> tuple[float, list[str]]:
        """
        Compute a relevance score and list of matched fields for one concept.

        Returns (score, matched_fields). Score > 0 means at least one match.
        """
        if not query:
            return 0.0, []

        score = 0.0
        matched: list[str] = []

        title_lower = concept.title.lower()
        aliases_lower = [a.lower() for a in concept.aliases]

        # Title exact match
        if query == title_lower:
            score += 3.0
            matched.append("title (exact)")
        elif query in title_lower:
            score += 2.0
            matched.append("title")

        # Alias exact / partial
        for alias in aliases_lower:
            if query == alias:
                score += 3.0
                matched.append("alias (exact)")
                break
            elif query in alias:
                score += 2.0
                matched.append("alias")
                break

        # Tags
        for tag in concept.tags:
            if query in tag.lower():
                score += 1.5
                matched.append("tag")
                break

        # Category
        if query in concept.category.lower():
            score += 1.0
            matched.append("category")

        # Description
        if query in concept.description.lower():
            score += 0.5
            matched.append("description")

        # Summary
        if query in concept.summary.lower():
            score += 0.5
            matched.append("summary")

        return score, matched


# Allow `Any` import without TYPE_CHECKING since it's used in __init__
from typing import Any  # noqa: E402
