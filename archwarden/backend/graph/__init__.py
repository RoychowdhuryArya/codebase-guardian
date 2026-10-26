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
        try:
            from .falkor_store import FalkorGraphStore
            store = FalkorGraphStore(
                graph_name=graph_name,
                host=settings.falkordb_host,
                port=settings.falkordb_port,
                password=settings.falkordb_password,
            )
            # Connectivity check
            store.ping()
            return store
        except Exception as e:
            print(f"[Archwarden] FalkorDB unreachable ({e}); falling back to MemoryGraphStore")

    from .memory_store import MemoryGraphStore
    return MemoryGraphStore(graph_name)


__all__ = ["make_store", "GraphStore"]
