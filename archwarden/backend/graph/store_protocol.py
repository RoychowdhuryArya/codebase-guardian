"""
Archwarden — GraphStore Protocol (ABC)
Both FalkorGraphStore and MemoryGraphStore implement this interface.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class GraphStore(ABC):
    """Common interface for Archwarden graph backends."""

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    @abstractmethod
    def bootstrap_indexes(self) -> None:
        """Create all required indexes (idempotent)."""

    # ── Write ops ─────────────────────────────────────────────────────────────

    @abstractmethod
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Run a read-write Cypher query."""

    # ── Read ops ──────────────────────────────────────────────────────────────

    @abstractmethod
    def ro_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """Run a read-only Cypher query. Returns rows as list-of-lists."""

    # ── Graph branching ────────────────────────────────────────────────────────

    @abstractmethod
    def copy_graph(self, src: str, dst: str) -> "GraphStore":
        """Clone src → dst (GRAPH.COPY). Returns a new GraphStore pointed at dst."""

    @abstractmethod
    def delete_graph(self, name: str) -> None:
        """Delete a named graph (best-effort, ignores if missing)."""

    # ── Introspection ─────────────────────────────────────────────────────────

    @abstractmethod
    def node_count(self) -> int:
        """Return total node count."""

    @abstractmethod
    def edge_count(self) -> int:
        """Return total edge count."""

    @property
    @abstractmethod
    def graph_name(self) -> str:
        """The name of the current graph."""
