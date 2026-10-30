"""
Archwarden — NetworkX MemoryGraphStore
Offline fallback. Implements the GraphStore protocol using in-memory dicts.
Tests pass offline without Docker.
"""
from __future__ import annotations
from typing import Any

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

from .store_protocol import GraphStore


class MemoryGraphStore(GraphStore):
    """
    Pure-Python fallback using NetworkX.
    Supports only the rule kinds needed for P-001..P-004:
      - forbid cross-unit access
      - no cycles (P-002)
      - max call depth (P-003)
      - dual-write detection (P-004) — partial, structural only
    """

    def __init__(self, graph_name: str = "archwarden_memory"):
        if not _NX_AVAILABLE:
            raise ImportError("Install networkx: pip install networkx")
        self._graph_name = graph_name
        self._G: nx.MultiDiGraph = nx.MultiDiGraph()
        # Stores: {label: [{props}]}
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        # Named graphs (for copy_graph simulation)
        self._snapshots: dict[str, "MemoryGraphStore"] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def bootstrap_indexes(self) -> None:
        pass  # No indexes needed for NetworkX

    # ── Node/Edge helpers ─────────────────────────────────────────────────────

    def add_node(self, label: str, props: dict) -> None:
        node_id = props.get("name") or props.get("qname") or props.get("path") or str(len(self._G.nodes))
        self._G.add_node(node_id, label=label, **props)

    def add_edge(self, from_id: str, to_id: str, rel: str, props: dict | None = None) -> None:
        self._G.add_edge(from_id, to_id, rel=rel, **(props or {}))

    # ── Write ops ─────────────────────────────────────────────────────────────

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        # No-op for memory store — callers should use add_node/add_edge directly
        return None

    # ── Read ops (Python evaluators for core rules) ────────────────────────────

    def ro_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """
        Cypher emulation for frontend visualization, stats, and blast radius.
        """
        c = cypher.strip()
        params = params or {}

        # 1. MATCH (n) RETURN count(n)
        if "RETURN count(n)" in c:
            return [[self._G.number_of_nodes()]]

        # 2. MATCH ()-[r]->() RETURN count(r)
        if "RETURN count(r)" in c:
            return [[self._G.number_of_edges()]]

        # 3. Graph data: Nodes query
        if "MATCH (n) RETURN id(n)" in c or ("MATCH (n)" in c and "display" in c):
            rows = []
            for node_id, data in self._G.nodes(data=True):
                label = data.get("label", "Node")
                display = (
                    data.get("name")
                    or data.get("qname")
                    or data.get("path")
                    or data.get("path_template")
                    or str(node_id)
                )
                rows.append([node_id, label, display])
            return rows[:200]

        # 4. Graph data: Edges query
        if "MATCH (a)-[r]->(b)" in c:
            rows = []
            for u, v, data in self._G.edges(data=True):
                rel = data.get("rel", "RELATED")
                rows.append([u, v, rel])
            return rows[:500]

        # 5. Label breakdown: MATCH (n) RETURN labels(n)[0] ... count(n)
        if "labels(n)" in c:
            counts: dict[str, int] = {}
            for _, data in self._G.nodes(data=True):
                lbl = data.get("label", "Unknown")
                counts[lbl] = counts.get(lbl, 0) + 1
            sorted_labels = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            return [[lbl, cnt] for lbl, cnt in sorted_labels]

        # 6. Service list: MATCH (s:Service) RETURN s.name ...
        if "s:Service" in c and "s.name" in c:
            svcs = []
            for _, data in self._G.nodes(data=True):
                if data.get("label") == "Service":
                    svcs.append([data.get("name", "unknown"), data.get("language", "python")])
            return sorted(svcs, key=lambda x: x[0])

        # 7. Blast radius: CALLS reachability
        if "CALLS" in c and ":Service" in c and "svc" in params:
            svc_name = params["svc"]
            visited = set()
            queue = [(svc_name, 0)]
            k_hops = 2
            # Extract k_hops if present in cypher e.g. CALLS*1..2
            import re
            m = re.search(r"CALLS\*1\.\.(\d+)", c)
            if m:
                k_hops = int(m.group(1))

            results = []
            while queue:
                curr, dist = queue.pop(0)
                if dist >= k_hops:
                    continue
                for u, v, data in self._G.edges(data=True):
                    if data.get("rel") == "CALLS":
                        neighbor = None
                        if u == curr and v not in visited and v != svc_name:
                            neighbor = v
                        elif v == curr and u not in visited and u != svc_name:
                            neighbor = u
                        if neighbor and neighbor not in visited:
                            visited.add(neighbor)
                            queue.append((neighbor, dist + 1))
                            lang = self._G.nodes.get(neighbor, {}).get("language", "python")
                            results.append([neighbor, lang])
            return results

        return []

    # ── Rule evaluators (Python-native, no Cypher) ─────────────────────────────

    def p001_cross_db_violations(self) -> list[dict]:
        """P-001: service A accesses table owned by service B."""
        violations: list[dict] = []
        for u, v, data in self._G.edges(data=True):
            if data.get("rel") == "ACCESSES":
                accessing_service = self._G.nodes[u].get("service")
                table_name = self._G.nodes[v].get("name")
                # Find owner
                for a, b, d2 in self._G.edges(data=True):
                    if d2.get("rel") == "OWNS_TABLE" and self._G.nodes[b].get("name") == table_name:
                        owner = self._G.nodes[a].get("name")
                        if owner and owner != accessing_service:
                            violations.append({
                                "from_service": accessing_service,
                                "owner_service": owner,
                                "table": table_name,
                                "mode": data.get("mode", "unknown"),
                                "evidence": data.get("evidence", ""),
                            })
        return violations

    def p002_cycles(self) -> list[list[str]]:
        """P-002: detect CALLS cycles among Service nodes."""
        service_graph = nx.DiGraph()
        for u, v, data in self._G.edges(data=True):
            if data.get("rel") == "CALLS":
                lu = self._G.nodes[u].get("label")
                lv = self._G.nodes[v].get("label")
                if lu == "Service" and lv == "Service":
                    service_graph.add_edge(u, v)
        cycles = list(nx.simple_cycles(service_graph))
        return [list(c) for c in cycles if len(c) >= 2]

    def p003_deep_chains(self, max_depth: int = 3) -> list[dict]:
        """P-003: synchronous call chains deeper than max_depth hops."""
        service_graph = nx.DiGraph()
        for u, v, data in self._G.edges(data=True):
            if data.get("rel") == "CALLS" and data.get("via") in ("http", "grpc"):
                service_graph.add_edge(u, v)
        results = []
        for src in service_graph.nodes:
            for dst in service_graph.nodes:
                if src == dst:
                    continue
                paths = list(nx.all_simple_paths(service_graph, src, dst, cutoff=max_depth + 5))
                for path in paths:
                    if len(path) - 1 > max_depth:
                        results.append({"chain": path, "depth": len(path) - 1})
        return results

    # ── Graph branching ───────────────────────────────────────────────────────

    def copy_graph(self, src: str, dst: str) -> "MemoryGraphStore":
        import copy
        new = MemoryGraphStore(dst)
        new._G = self._G.copy()
        self._snapshots[dst] = new
        return new

    def delete_graph(self, name: str) -> None:
        self._snapshots.pop(name, None)

    # ── Introspection ─────────────────────────────────────────────────────────

    def node_count(self) -> int:
        return self._G.number_of_nodes()

    def edge_count(self) -> int:
        return self._G.number_of_edges()

    @property
    def graph_name(self) -> str:
        return self._graph_name
