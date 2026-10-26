"""
Archwarden — Repository Walker + Graph Ingestor
Walks a multi-service repo, runs AST extraction on each service,
and upserts nodes/edges into FalkorDB.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .ast_extractor import ArchwardenASTVisitor
from graph.store_protocol import GraphStore


# ── Service discovery ─────────────────────────────────────────────────────────

def discover_services(repo_dir: str) -> list[dict[str, str]]:
    """
    Auto-detect services in a repo.
    A 'service' is any directory that contains a Python entrypoint:
      - main.py / app.py / server.py / __main__.py
    or any top-level directory.
    """
    repo_path = Path(repo_dir).resolve()
    services: list[dict[str, str]] = []

    # Check if top-level is itself a service
    for entry_file in ("main.py", "app.py", "server.py", "api.py"):
        if (repo_path / entry_file).exists():
            services.append({
                "name": repo_path.name,
                "path": str(repo_path),
                "kind": "service",
                "language": "python",
            })
            return services

    # Otherwise walk one level
    for d in sorted(repo_path.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if name.startswith(".") or name in ("node_modules", "venv", ".venv", "__pycache__", ".git"):
            continue
        services.append({
            "name": name,
            "path": str(d),
            "kind": "service",
            "language": "python",
            "repo": repo_path.name,
        })

    if not services:
        # Flat repo — treat the whole thing as one service
        services.append({
            "name": repo_path.name,
            "path": str(repo_path),
            "kind": "service",
            "language": "python",
        })

    return services


# ── Graph upsert helpers ──────────────────────────────────────────────────────

def _upsert_service(store: GraphStore, svc: dict) -> None:
    store.query(
        """
        MERGE (s:Service {name: $name})
        SET s.kind = $kind, s.path = $path, s.language = $language
        """,
        {"name": svc["name"], "kind": svc.get("kind", "service"),
         "path": svc.get("path", ""), "language": svc.get("language", "python")},
    )


def _upsert_file(store: GraphStore, file_path: str, service_name: str) -> None:
    store.query(
        """
        MERGE (f:File {path: $path})
        SET f.service = $service
        WITH f
        MATCH (s:Service {name: $service})
        MERGE (s)-[:CONTAINS]->(f)
        """,
        {"path": file_path, "service": service_name},
    )


def _upsert_symbol(store: GraphStore, sym: dict) -> None:
    store.query(
        """
        MERGE (sym:Symbol {qname: $qname})
        SET sym.kind = $kind, sym.file = $file, sym.line = $line, sym.service = $service
        WITH sym
        MATCH (f:File {path: $file})
        MERGE (f)-[:CONTAINS]->(sym)
        """,
        sym,
    )


def _upsert_route(store: GraphStore, route: dict) -> None:
    store.query(
        """
        MERGE (r:Route {path_template: $path_template, service: $service})
        SET r.method = $method, r.protocol = $protocol, r.file = $file, r.line = $line
        WITH r
        MATCH (sym:Symbol {qname: $handler_qname})
        MERGE (sym)-[:DEFINES]->(r)
        """,
        route,
    )


def _upsert_client_call(store: GraphStore, cc: dict) -> None:
    store.query(
        """
        MERGE (c:ClientCall {target_hint: $target_hint, path: $path, service: $service})
        SET c.method = $method, c.file = $file, c.line = $line,
            c.resolved = $resolved, c.resolution_source = $resolution_source,
            c.has_timeout = $has_timeout
        WITH c
        MATCH (sym:Symbol {qname: $caller_qname})
        MERGE (sym)-[:MAKES_CALL]->(c)
        """,
        cc,
    )


def _upsert_table_access(store: GraphStore, ta: dict, known_table_owners: dict[str, str]) -> None:
    store.query(
        """
        MERGE (t:Table {name: $table})
        WITH t
        MATCH (sym:Symbol {qname: $accessor_qname})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode = $mode, x.evidence = $evidence
        """,
        ta,
    )
    # If we know who owns this table, create OWNS_TABLE
    owner = known_table_owners.get(ta["table"])
    if owner:
        store.query(
            """
            MATCH (s:Service {name: $owner}), (t:Table {name: $table})
            MERGE (s)-[:OWNS_TABLE]->(t)
            """,
            {"owner": owner, "table": ta["table"]},
        )


def _upsert_topic(store: GraphStore, tp: dict, kind: str) -> None:
    rel = "PRODUCES" if kind == "produce" else "CONSUMES"
    qname_key = "producer_qname" if kind == "produce" else "consumer_qname"
    store.query(
        f"""
        MERGE (top:Topic {{name: $topic}})
        WITH top
        MATCH (sym:Symbol {{qname: $qname}})
        MERGE (sym)-[:{rel}]->(top)
        """,
        {"topic": tp["topic"], "qname": tp[qname_key]},
    )


def _derive_calls_edges(store: GraphStore) -> None:
    """
    Derive Service→Service CALLS edges from resolved ClientCall→Route links.
    Also derives from target_hint matching.
    """
    # First resolve ClientCalls by matching target_hint to Service names
    store.query(
        """
        MATCH (cc:ClientCall)
        WHERE NOT cc.resolved
        MATCH (s:Service)
        WHERE cc.target_hint CONTAINS s.name OR s.name CONTAINS cc.target_hint
        SET cc.resolved = true, cc.resolution_source = 'HEURISTIC'
        WITH cc, s
        MERGE (cc)-[:RESOLVES_TO {confidence: 'HEURISTIC'}]->(s)
        """
    )

    # Derive CALLS edges
    store.query(
        """
        MATCH (caller:Symbol)-[:MAKES_CALL]->(cc:ClientCall)-[:RESOLVES_TO]->(callee:Service)
        MATCH (caller_svc:Service)-[:CONTAINS*1..3]->(caller)
        WHERE caller_svc.name <> callee.name
        MERGE (caller_svc)-[c:CALLS]->(callee)
        ON CREATE SET c.via = 'http', c.count = 1
        ON MATCH SET c.count = c.count + 1
        """
    )


# ── Main ingest entry point ───────────────────────────────────────────────────

def ingest_repo(
    repo_dir: str,
    store: GraphStore,
    table_owners: dict[str, str] | None = None,
    service_filter: list[str] | None = None,
) -> dict[str, int]:
    """
    Walk repo_dir, extract all symbols, and upsert into store.
    table_owners: {table_name: owning_service_name} overrides (from config/migrations)
    service_filter: only ingest these service names (for PR head update)
    Returns stats dict.
    """
    table_owners = table_owners or {}
    services = discover_services(repo_dir)

    if service_filter:
        services = [s for s in services if s["name"] in service_filter]

    stats = {
        "services": 0,
        "files": 0,
        "symbols": 0,
        "routes": 0,
        "client_calls": 0,
        "table_accesses": 0,
        "topics": 0,
    }

    for svc in services:
        _upsert_service(store, svc)
        stats["services"] += 1

        svc_path = Path(svc["path"])
        for py_file in sorted(svc_path.rglob("*.py")):
            # Skip venv / caches
            if any(p in py_file.parts for p in (".venv", "venv", "__pycache__", ".git", "node_modules")):
                continue

            rel_path = str(py_file.relative_to(svc_path)).replace("\\", "/")
            full_rel = f"{svc['name']}/{rel_path}"

            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as fh:
                    src = fh.read()
                import ast
                tree = ast.parse(src, filename=str(py_file))
            except Exception:
                continue

            _upsert_file(store, full_rel, svc["name"])
            stats["files"] += 1

            visitor = ArchwardenASTVisitor(full_rel, svc["name"])
            visitor.visit(tree)

            for sym in visitor.symbols:
                _upsert_symbol(store, sym)
                stats["symbols"] += 1

            for route in visitor.routes:
                _upsert_route(store, route)
                stats["routes"] += 1

            for cc in visitor.client_calls:
                _upsert_client_call(store, cc)
                stats["client_calls"] += 1

            for ta in visitor.table_accesses:
                _upsert_table_access(store, ta, table_owners)
                stats["table_accesses"] += 1

            for tp in visitor.topic_produces:
                _upsert_topic(store, tp, "produce")
                stats["topics"] += 1

            for tc in visitor.topic_consumes:
                _upsert_topic(store, tc, "consume")
                stats["topics"] += 1

    _derive_calls_edges(store)
    return stats
