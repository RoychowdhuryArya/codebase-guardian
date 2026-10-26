"""
Archwarden — FalkorDB Graph Store
Primary graph engine. Falls back to MemoryGraphStore when unreachable.
"""
from __future__ import annotations
import os
import sys
from typing import Any

from .store_protocol import GraphStore


class FalkorGraphStore(GraphStore):
    """
    Wraps the falkordb Python client.
    - Uses ro_query for all rule checks (no accidental writes).
    - GRAPH.COPY is exposed as copy_graph() for PR branching.
    """

    def __init__(self, graph_name: str = "archwarden_base", host: str = "localhost", port: int = 6379, password: str = ""):
        try:
            from falkordb import FalkorDB
        except ImportError as e:
            raise ImportError("Install falkordb: pip install falkordb") from e

        kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "socket_connect_timeout": 3.0,
            "socket_timeout": 5.0,
        }
        if password:
            kwargs["password"] = password

        self._db = FalkorDB(**kwargs)
        self._graph_name = graph_name
        self._graph = self._db.select_graph(graph_name)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def bootstrap_indexes(self) -> None:
        """Create all required FalkorDB range indexes (idempotent)."""
        indexes = [
            "CREATE INDEX FOR (s:Service) ON (s.name)",
            "CREATE INDEX FOR (f:File) ON (f.path)",
            "CREATE INDEX FOR (sym:Symbol) ON (sym.qname)",
            "CREATE INDEX FOR (sym:Symbol) ON (sym.service)",
            "CREATE INDEX FOR (r:Route) ON (r.path_template)",
            "CREATE INDEX FOR (r:Route) ON (r.service)",
            "CREATE INDEX FOR (c:ClientCall) ON (c.target_hint)",
            "CREATE INDEX FOR (c:ClientCall) ON (c.service)",
            "CREATE INDEX FOR (t:Table) ON (t.name)",
            "CREATE INDEX FOR (top:Topic) ON (top.name)",
            "CREATE INDEX FOR (ck:ConfigKey) ON (ck.name)",
        ]
        for idx in indexes:
            try:
                self._graph.query(idx)
            except Exception:
                pass  # Index already exists or unsupported

    def ping(self) -> bool:
        return bool(self._db.connection.ping())

    # ── Write ops ─────────────────────────────────────────────────────────────

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        return self._graph.query(cypher, params or {})

    # ── Read ops ─────────────────────────────────────────────────────────────

    def ro_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        try:
            result = self._graph.ro_query(cypher, params or {})
            if result and hasattr(result, "result_set") and result.result_set:
                return result.result_set
            return []
        except Exception as e:
            if "empty key" in str(e).lower() or "key doesn't exist" in str(e).lower():
                return []
            raise

    # ── Graph branching ───────────────────────────────────────────────────────

    def copy_graph(self, src: str, dst: str) -> "FalkorGraphStore":
        """
        Clone src → dst via GRAPH.COPY.
        Deletes dst first if it already exists (GRAPH.COPY errors on collision).
        Returns a new FalkorGraphStore pointed at dst.
        """
        self.delete_graph(dst)
        src_graph = self._db.select_graph(src)
        src_graph.copy(dst)
        new_store = FalkorGraphStore.__new__(FalkorGraphStore)
        new_store._db = self._db
        new_store._graph_name = dst
        new_store._graph = self._db.select_graph(dst)
        return new_store

    def delete_graph(self, name: str) -> None:
        try:
            g = self._db.select_graph(name)
            g.delete()
        except Exception:
            pass  # Graph doesn't exist or already deleted

    # ── Introspection ─────────────────────────────────────────────────────────

    def node_count(self) -> int:
        rows = self.ro_query("MATCH (n) RETURN count(n) AS cnt")
        return int(rows[0][0]) if rows else 0

    def edge_count(self) -> int:
        rows = self.ro_query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        return int(rows[0][0]) if rows else 0

    @property
    def graph_name(self) -> str:
        return self._graph_name

    def list_graphs(self) -> list[str]:
        return self._db.list_graphs()

    # ── Convenience: get graph pointed at a different name ─────────────────────

    def select(self, name: str) -> "FalkorGraphStore":
        """Return a new store pointing at 'name' on the same DB connection."""
        new = FalkorGraphStore.__new__(FalkorGraphStore)
        new._db = self._db
        new._graph_name = name
        new._graph = self._db.select_graph(name)
        return new
