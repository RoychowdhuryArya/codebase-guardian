"""
Archwarden — Graph API Routes
/graph/stats, /graph/ingest, /graph/query, /graph/blast-radius
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter()


def _store():
    from main import get_store
    return get_store()


# ── Models ────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    repo_dir: str
    table_owners: Optional[dict[str, str]] = None


class QueryRequest(BaseModel):
    cypher: str
    params: Optional[dict[str, Any]] = None
    read_only: bool = True


class BlastRadiusRequest(BaseModel):
    service: str
    k_hops: int = 2


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats")
async def graph_stats():
    """Return node/edge counts and label breakdown."""
    store = _store()
    try:
        node_count = store.node_count()
        edge_count = store.edge_count()

        # Label breakdown
        labels_raw = store.ro_query(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"
        )
        labels = [{"label": row[0], "count": row[1]} for row in labels_raw if row[0]]

        # Service list
        svcs_raw = store.ro_query(
            "MATCH (s:Service) RETURN s.name AS name, s.language AS lang ORDER BY name"
        )
        services = [{"name": r[0], "language": r[1]} for r in svcs_raw]

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "labels": labels,
            "services": services,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest_repo(req: IngestRequest):
    """Ingest a local repository into the graph."""
    if not os.path.isdir(req.repo_dir):
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.repo_dir}")
    store = _store()
    try:
        from ingest.repo_walker import ingest_repo as _ingest
        stats = _ingest(req.repo_dir, store, req.table_owners)
        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def run_query(req: QueryRequest):
    """Run an arbitrary Cypher query (read-only by default)."""
    store = _store()
    try:
        if req.read_only:
            rows = store.ro_query(req.cypher, req.params)
        else:
            result = store.query(req.cypher, req.params)
            rows = getattr(result, "result_set", []) or []
        return {"rows": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/blast-radius")
async def blast_radius(req: BlastRadiusRequest):
    """Compute k-hop CALLS reachability from a service."""
    store = _store()
    try:
        rows = store.ro_query(
            f"MATCH (s:Service {{name: $svc}})-[:CALLS*1..{req.k_hops}]-(o:Service) "
            "RETURN DISTINCT o.name AS name, o.language AS lang",
            {"svc": req.service},
        )
        affected = [{"name": r[0], "language": r[1]} for r in rows if r[0]]
        return {
            "service": req.service,
            "k_hops": req.k_hops,
            "affected_count": len(affected),
            "affected_services": affected,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph-data")
async def graph_data():
    """
    Return nodes and edges for frontend visualization.
    Limits to 200 nodes for performance.
    """
    store = _store()
    try:
        # Nodes
        nodes_raw = store.ro_query(
            "MATCH (n) RETURN id(n) AS id, labels(n)[0] AS label, "
            "coalesce(n.name, n.qname, n.path, n.path_template, 'unknown') AS display "
            "LIMIT 200"
        )
        nodes = [
            {"id": str(r[0]), "label": r[1] or "Node", "display": r[2] or "?"}
            for r in nodes_raw
        ]

        # Edges
        edges_raw = store.ro_query(
            "MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS dst, type(r) AS rel LIMIT 500"
        )
        edges = [
            {"source": str(r[0]), "target": str(r[1]), "rel": r[2]}
            for r in edges_raw
        ]

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed")
async def seed_demo():
    """Re-seed the demo graph."""
    store = _store()
    try:
        from seeds.seed_demo import seed
        seed(store)
        return {"success": True, "message": "Demo data seeded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
