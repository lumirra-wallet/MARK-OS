"""
KnowledgeGraph — the in-memory directed graph of concepts and relationships.

Nodes are concepts (keyed by concept ID). Edges are relationships. The
graph is rebuilt from persisted storage on startup and updated in-place as
concepts and relationships are added, changed, or removed.

Operations supported (per the Milestone 7 spec):
  create node, update node, delete node
  connect nodes, disconnect nodes
  merge nodes, split nodes
  version history (tracked on Concept.revision_history)
  graph traversal (BFS, DFS)
  shortest path (BFS)
  dependency lookup, relationship lookup
  future graph visualization hook (to_adjacency_dict)
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept
    from smartagent.knowledge.relationships.relationship import Relationship


@dataclass
class GraphStats:
    """Snapshot statistics about the current graph state."""

    node_count: int = 0
    edge_count: int = 0
    root_nodes: list[str] = field(default_factory=list)   # concept IDs with no dependencies
    orphan_nodes: list[str] = field(default_factory=list)  # concept IDs with no relationships


class KnowledgeGraph:
    """
    In-memory directed graph where each node is a concept ID and each
    edge is a relationship.

    The graph stores only IDs — actual `Concept` and `Relationship`
    objects are owned by `KnowledgeStorage`. This keeps the graph lean
    and avoids duplicating the canonical state.

    Args:
        None — the graph starts empty. Populate it by calling
        `add_node` / `add_edge` during startup or on ingestion.
    """

    def __init__(self) -> None:
        # Adjacency list: node_id -> set of neighbor node IDs (forward edges)
        self._adj: dict[str, set[str]] = defaultdict(set)
        # Reverse adjacency: node_id -> set of predecessor node IDs
        self._radj: dict[str, set[str]] = defaultdict(set)
        # All registered node IDs
        self._nodes: set[str] = set()
        # Edge index: (from_id, to_id) -> relationship_id
        self._edges: dict[tuple[str, str], str] = {}
        # Relationship lookup: relationship_id -> (from_id, to_id)
        self._rel_positions: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------ #
    # Node management                                                      #
    # ------------------------------------------------------------------ #

    def add_node(self, concept_id: str) -> None:
        """Register a concept ID as a node in the graph."""
        self._nodes.add(concept_id)
        # Ensure adjacency entries exist even for isolated nodes.
        if concept_id not in self._adj:
            self._adj[concept_id] = set()
        if concept_id not in self._radj:
            self._radj[concept_id] = set()

    def remove_node(self, concept_id: str) -> None:
        """
        Remove a concept node and all edges incident to it.

        This is a hard delete from the in-memory graph only — the
        caller is responsible for removing the persisted concept file.
        """
        if concept_id not in self._nodes:
            return
        # Remove all outgoing edges.
        for neighbor in list(self._adj.get(concept_id, set())):
            self._edges.pop((concept_id, neighbor), None)
            self._radj[neighbor].discard(concept_id)
        # Remove all incoming edges.
        for predecessor in list(self._radj.get(concept_id, set())):
            self._edges.pop((predecessor, concept_id), None)
            self._adj[predecessor].discard(concept_id)
        # Clean up reverse-lookup entries.
        rel_ids_to_remove = [
            rid
            for rid, (f, t) in self._rel_positions.items()
            if f == concept_id or t == concept_id
        ]
        for rid in rel_ids_to_remove:
            del self._rel_positions[rid]

        self._nodes.discard(concept_id)
        self._adj.pop(concept_id, None)
        self._radj.pop(concept_id, None)

    def has_node(self, concept_id: str) -> bool:
        """Whether a concept ID is currently registered in the graph."""
        return concept_id in self._nodes

    def list_nodes(self) -> list[str]:
        """Return all registered concept IDs."""
        return sorted(self._nodes)

    # ------------------------------------------------------------------ #
    # Edge management                                                      #
    # ------------------------------------------------------------------ #

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        relationship_id: str,
        bidirectional: bool = False,
    ) -> None:
        """
        Add a directed edge from `from_id` to `to_id`.

        Automatically ensures both nodes exist in the graph first.
        If `bidirectional`, also adds the reverse edge.
        """
        self.add_node(from_id)
        self.add_node(to_id)
        self._adj[from_id].add(to_id)
        self._radj[to_id].add(from_id)
        self._edges[(from_id, to_id)] = relationship_id
        self._rel_positions[relationship_id] = (from_id, to_id)
        if bidirectional:
            self._adj[to_id].add(from_id)
            self._radj[from_id].add(to_id)
            self._edges[(to_id, from_id)] = relationship_id

    def remove_edge(self, from_id: str, to_id: str) -> bool:
        """
        Remove the edge from `from_id` to `to_id`. Returns True if removed.
        """
        if (from_id, to_id) not in self._edges:
            return False
        rel_id = self._edges.pop((from_id, to_id))
        self._rel_positions.pop(rel_id, None)
        self._adj[from_id].discard(to_id)
        self._radj[to_id].discard(from_id)
        return True

    def remove_edge_by_relationship(self, relationship_id: str) -> bool:
        """Remove the edge associated with `relationship_id`."""
        pos = self._rel_positions.get(relationship_id)
        if pos is None:
            return False
        return self.remove_edge(pos[0], pos[1])

    def has_edge(self, from_id: str, to_id: str) -> bool:
        """Whether a directed edge from `from_id` to `to_id` exists."""
        return (from_id, to_id) in self._edges

    def get_relationship_id(self, from_id: str, to_id: str) -> str | None:
        """Look up the relationship ID for a specific edge, or None."""
        return self._edges.get((from_id, to_id))

    def neighbors(self, concept_id: str) -> list[str]:
        """Return direct successors of `concept_id` (forward neighbors)."""
        return sorted(self._adj.get(concept_id, set()))

    def predecessors(self, concept_id: str) -> list[str]:
        """Return direct predecessors of `concept_id` (reverse neighbors)."""
        return sorted(self._radj.get(concept_id, set()))

    # ------------------------------------------------------------------ #
    # Traversal                                                            #
    # ------------------------------------------------------------------ #

    def bfs(self, start_id: str) -> Iterator[str]:
        """
        Breadth-first traversal from `start_id` through forward edges.

        Yields each visited concept ID exactly once (including `start_id`).
        Silently skips `start_id` if it is not in the graph.
        """
        if start_id not in self._nodes:
            return
        visited: set[str] = set()
        queue: deque[str] = deque([start_id])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            yield node
            for neighbor in sorted(self._adj.get(node, set())):
                if neighbor not in visited:
                    queue.append(neighbor)

    def dfs(self, start_id: str) -> Iterator[str]:
        """
        Depth-first traversal from `start_id` through forward edges.

        Yields each visited concept ID exactly once.
        """
        if start_id not in self._nodes:
            return
        visited: set[str] = set()
        stack: list[str] = [start_id]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            yield node
            for neighbor in sorted(self._adj.get(node, set()), reverse=True):
                if neighbor not in visited:
                    stack.append(neighbor)

    def shortest_path(self, from_id: str, to_id: str) -> list[str] | None:
        """
        Find the shortest directed path from `from_id` to `to_id` via BFS.

        Returns the ordered list of concept IDs (inclusive of both
        endpoints), or None if no path exists.
        """
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        if from_id == to_id:
            return [from_id]

        visited: set[str] = set()
        queue: deque[list[str]] = deque([[from_id]])
        while queue:
            path = queue.popleft()
            node = path[-1]
            if node in visited:
                continue
            visited.add(node)
            for neighbor in sorted(self._adj.get(node, set())):
                new_path = path + [neighbor]
                if neighbor == to_id:
                    return new_path
                if neighbor not in visited:
                    queue.append(new_path)
        return None

    # ------------------------------------------------------------------ #
    # Lookup helpers                                                        #
    # ------------------------------------------------------------------ #

    def dependencies_of(self, concept_id: str) -> list[str]:
        """
        Return concept IDs that `concept_id` directly depends on
        (i.e. follows 'depends_on' and 'requires' edges).

        This uses the forward adjacency list — all direct neighbors —
        since the graph does not currently distinguish edge types at the
        adjacency level (that filtering is done at the query layer).
        For a type-filtered dependency view, use `QueryEngine.find_dependencies`.
        """
        return self.neighbors(concept_id)

    def dependents_of(self, concept_id: str) -> list[str]:
        """Return concept IDs that directly depend on `concept_id`."""
        return self.predecessors(concept_id)

    def relationships_for(self, concept_id: str) -> list[str]:
        """
        Return all relationship IDs involving `concept_id` (as either
        source or destination).
        """
        rel_ids: list[str] = []
        for (f, t), rid in self._edges.items():
            if f == concept_id or t == concept_id:
                rel_ids.append(rid)
        return sorted(set(rel_ids))

    # ------------------------------------------------------------------ #
    # Merge / split                                                         #
    # ------------------------------------------------------------------ #

    def merge_nodes(self, primary_id: str, secondary_id: str) -> None:
        """
        Merge `secondary_id` into `primary_id` at the graph level.

        All edges that pointed to or from `secondary_id` are redirected
        to `primary_id`. Self-loops are silently dropped.
        `secondary_id` is then removed from the graph.

        The caller is responsible for merging the `Concept` data objects
        and updating storage.
        """
        if secondary_id not in self._nodes or primary_id not in self._nodes:
            return
        # Redirect outgoing edges.
        for neighbor in list(self._adj.get(secondary_id, set())):
            if neighbor != primary_id:  # avoid self-loop
                rel_id = self._edges.pop((secondary_id, neighbor), "")
                self._adj[primary_id].add(neighbor)
                self._radj[neighbor].discard(secondary_id)
                self._radj[neighbor].add(primary_id)
                if rel_id:
                    self._edges[(primary_id, neighbor)] = rel_id
                    self._rel_positions[rel_id] = (primary_id, neighbor)
        # Redirect incoming edges.
        for predecessor in list(self._radj.get(secondary_id, set())):
            if predecessor != primary_id:
                rel_id = self._edges.pop((predecessor, secondary_id), "")
                self._radj[primary_id].add(predecessor)
                self._adj[predecessor].discard(secondary_id)
                self._adj[predecessor].add(primary_id)
                if rel_id:
                    self._edges[(predecessor, primary_id)] = rel_id
                    self._rel_positions[rel_id] = (predecessor, primary_id)
        self.remove_node(secondary_id)

    def split_node(self, original_id: str, new_id: str) -> None:
        """
        Register `new_id` as a sibling of `original_id` at the graph level.

        This creates `new_id` as an isolated node; the caller is responsible
        for deciding which relationships to move to `new_id` (using
        `remove_edge` / `add_edge`) and for creating the new concept in storage.
        """
        self.add_node(new_id)

    # ------------------------------------------------------------------ #
    # Stats and export                                                     #
    # ------------------------------------------------------------------ #

    def stats(self) -> GraphStats:
        """Return a snapshot of basic graph statistics."""
        root_nodes = [
            node_id
            for node_id in self._nodes
            if not self._radj.get(node_id)
        ]
        orphan_nodes = [
            node_id
            for node_id in self._nodes
            if not self._adj.get(node_id) and not self._radj.get(node_id)
        ]
        return GraphStats(
            node_count=len(self._nodes),
            edge_count=len(self._edges),
            root_nodes=sorted(root_nodes),
            orphan_nodes=sorted(orphan_nodes),
        )

    def to_adjacency_dict(self) -> dict[str, list[str]]:
        """
        Export the graph as a plain adjacency dictionary for visualization.

        Format: {concept_id: [neighbor_concept_id, ...], ...}
        """
        return {
            node: sorted(self._adj.get(node, set()))
            for node in sorted(self._nodes)
        }
