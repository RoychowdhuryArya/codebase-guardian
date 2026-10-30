"""
Archwarden — Graph Factory
Auto-detects FalkorDB availability; falls back to MemoryGraphStore.
"""
from __future__ import annotations
from .store_protocol import GraphStore


def make_store(graph_name: str = "archwarden_base") -> GraphStore:
    """
    Return FalkorGraphStore if ARCHWARDEN_GRAPH=falkor and FalkorDB is reachable,
    otherwise return MemoryGraphStore.
    """
    from config import settings

    if settings.graph_engine == "falkor":
        candidate_hosts = [
            settings.falkordb_host,
            "falkordb",
            "blastradius-falkordb",
            "host.docker.internal",
            "localhost",
            "127.0.0.1",
        ]
        seen = set()
        hosts = [h for h in candidate_hosts if h and not (h in seen or seen.add(h))]
        last_err = None
        for host in hosts:
            try:
                from .falkor_store import FalkorGraphStore
                store = FalkorGraphStore(
                    graph_name=graph_name,
                    host=host,
                    port=settings.falkordb_port,
                    password=settings.falkordb_password,
                )
                store.ping()
                print(f"[Archwarden] Connected to FalkorDB on {host}:{settings.falkordb_port}")
                return store
            except Exception as e:
                last_err = e
                continue
        print(f"[Archwarden] FalkorDB unreachable on candidates ({last_err}); falling back to MemoryGraphStore")

    from .memory_store import MemoryGraphStore
    return MemoryGraphStore(graph_name)


__all__ = ["make_store", "GraphStore"]
