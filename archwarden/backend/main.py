"""
Archwarden — FastAPI Application Entry Point
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from graph import make_store

# ── App-level graph store (singleton) ─────────────────────────────────────────
_store = None


def get_store():
    global _store
    if _store is None:
        _store = make_store("archwarden_base")
    return _store


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    warnings = settings.validate()
    for w in warnings:
        print(f"[Archwarden] ⚠️  {w}")

    store = get_store()
    try:
        store.bootstrap_indexes()
        print(f"[Archwarden] Graph indexes ready on '{store.graph_name}'")
    except Exception as e:
        print(f"[Archwarden] Index bootstrap warning: {e}")

    # Auto-seed if graph is empty
    try:
        if store.node_count() == 0:
            print("[Archwarden] Graph is empty — seeding demo data...")
            from seeds.seed_demo import seed
            seed(store)
            print("[Archwarden] Demo seed complete!")
    except Exception as e:
        print(f"[Archwarden] Auto-seed warning: {e}")

    yield

    # Shutdown (cleanup if needed)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Archwarden API",
    version="1.0.0",
    description=(
        "Architecture governance engine using FalkorDB graph analysis "
        "and NVIDIA Nemotron for principle mining."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

from api.routes_graph import router as graph_router
from api.routes_review import router as review_router
from api.routes_principles import router as principles_router

app.include_router(graph_router, prefix="/graph", tags=["Graph"])
app.include_router(review_router, prefix="/review", tags=["PR Review"])
app.include_router(principles_router, prefix="/principles", tags=["Principles"])


@app.get("/health")
async def health():
    store = get_store()
    # Detect actual engine from store type
    engine_actual = "falkor" if "Falkor" in type(store).__name__ else "memory"
    return {
        "status": "ok",
        "graph": store.graph_name,
        "engine": engine_actual,
        "engine_configured": settings.graph_engine,
        "nodes": store.node_count(),
        "edges": store.edge_count(),
        "llm_available": settings.nvidia_api_key != "",
        "falkordb_connected": engine_actual == "falkor",
    }


@app.get("/")
async def root():
    return {
        "name": "Archwarden",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
