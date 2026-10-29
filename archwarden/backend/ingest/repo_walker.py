"""
Archwarden — Repository Walker + Graph Ingestor
Walks a multi-service repo, runs AST extraction on each service,
and upserts nodes/edges into FalkorDB.

Upgraded: now handles TypeScript / JavaScript files alongside Python,
and triggers OpenAPI spec and docker-compose ingestion automatically.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .ast_extractor import ArchwardenASTVisitor, extract_ts_nodes
from graph.store_protocol import GraphStore


# ── File-type constants ───────────────────────────────────────────────────────

_PYTHON_EXTS = {".py"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", ".next", "dist", "build", ".turbo"}


# ── Service discovery ─────────────────────────────────────────────────────────

def discover_services(repo_dir: str) -> list[dict[str, str]]:
    """
    Auto-detect services in a repo.
    A 'service' is any directory that contains a Python entrypoint:
      - main.py / app.py / server.py / __main__.py
    or a TypeScript/Next.js entrypoint:
      - package.json / next.config.js / next.config.ts / index.ts / server.ts
    or any top-level directory.
    """
    repo_path = Path(repo_dir).resolve()
    services: list[dict[str, str]] = []

    # Check if top-level is itself a Python service
    for entry_file in ("main.py", "app.py", "server.py", "api.py"):
        if (repo_path / entry_file).exists():
            services.append({
                "name": repo_path.name,
                "path": str(repo_path),
                "kind": "service",
                "language": "python",
            })
            return services

    # Check if top-level is itself a TS/Next.js service
    for entry_file in ("package.json", "next.config.js", "next.config.ts"):
        if (repo_path / entry_file).exists():
            lang = _detect_language(repo_path)
            services.append({
                "name": repo_path.name,
                "path": str(repo_path),
                "kind": "service",
                "language": lang,
            })
            return services

    # Otherwise walk one level
    for d in sorted(repo_path.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if name.startswith(".") or name in _SKIP_DIRS:
            continue
        lang = _detect_language(d)
        services.append({
            "name": name,
            "path": str(d),
            "kind": "service",
            "language": lang,
            "repo": repo_path.name,
        })

    if not services:
        # Flat repo — treat the whole thing as one service
        services.append({
            "name": repo_path.name,
            "path": str(repo_path),
            "kind": "service",
            "language": _detect_language(repo_path),
        })

    return services


def _detect_language(service_path: Path) -> str:
    """
    Heuristic: if a directory has package.json or .ts/.tsx files, it's TypeScript/JS.
    If it has .py files (or main.py), it's Python.
    Defaults to 'python' if ambiguous.
    """
    has_py = any(service_path.rglob("*.py"))
    has_ts = any(service_path.rglob("*.ts")) or any(service_path.rglob("*.tsx"))
    has_pkg = (service_path / "package.json").exists()

    if has_pkg or has_ts:
        return "typescript"
    if has_py:
        return "python"
    return "python"


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
    # First resolve ClientCalls to Route nodes by matching cc.path to Route.path_template
    store.query(
        """
        MATCH (cc:ClientCall), (r:Route)
        WHERE cc.path = r.path_template AND cc.service <> r.service
        SET cc.resolved = true, cc.resolution_source = 'STATIC'
        WITH cc, r
        MERGE (cc)-[:RESOLVES_TO {confidence: 'FACT'}]->(r)
        """
    )

    # Fallback: resolve ClientCalls by matching target_hint to Service names
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

    # Derive CALLS edges from ClientCall→Service resolution
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

    # Derive CALLS edges from ClientCall→Route resolution
    store.query(
        """
        MATCH (caller:Symbol)-[:MAKES_CALL]->(cc:ClientCall)-[:RESOLVES_TO]->(r:Route)
        MATCH (caller_svc:Service)-[:CONTAINS*1..3]->(caller)
        MATCH (callee_svc:Service {name: r.service})
        WHERE caller_svc.name <> callee_svc.name
        MERGE (caller_svc)-[c:CALLS]->(callee_svc)
        ON CREATE SET c.via = 'http', c.count = 1
        ON MATCH SET c.count = c.count + 1
        """
    )


# ── TypeScript / JavaScript file ingestor ─────────────────────────────────────

def _ingest_ts_file(
    store: GraphStore,
    ts_file: Path,
    svc: dict,
    svc_path: Path,
    stats: dict,
) -> None:
    """Parse a single TS/JS file and upsert its routes and client calls."""
    rel_path = str(ts_file.relative_to(svc_path)).replace("\\", "/")
    full_rel = f"{svc['name']}/{rel_path}"

    try:
        with open(ts_file, "r", encoding="utf-8", errors="ignore") as fh:
            src = fh.read()
    except Exception:
        return

    _upsert_file(store, full_rel, svc["name"])
    stats["files"] += 1

    routes, client_calls = extract_ts_nodes(full_rel, svc["name"], src)

    for route in routes:
        # Ensure stub Symbol for handler
        handler_qname = route.get("handler_qname", f"{svc['name']}::ts_handler@{full_rel}")
        stub_sym = {
            "qname": handler_qname,
            "kind": "handler",
            "file": full_rel,
            "line": route.get("line", 0),
            "service": svc["name"],
        }
        _upsert_symbol(store, stub_sym)
        _upsert_route(store, route)
        stats["routes"] += 1

    for cc in client_calls:
        # Ensure stub caller Symbol
        caller_qname = cc.get("caller_qname", f"{svc['name']}::ts_caller@{full_rel}")
        stub_sym = {
            "qname": caller_qname,
            "kind": "method",
            "file": full_rel,
            "line": cc.get("line", 0),
            "service": svc["name"],
        }
        _upsert_symbol(store, stub_sym)
        _upsert_client_call(store, cc)
        stats["client_calls"] += 1


# ── Main ingest entry point ───────────────────────────────────────────────────

def ingest_repo(
    repo_dir: str,
    store: GraphStore,
    table_owners: dict[str, str] | None = None,
    service_filter: list[str] | None = None,
    ingest_openapi: bool = True,
    ingest_compose: bool = True,
) -> dict[str, int]:
    """
    Walk repo_dir, extract all symbols from Python AND TypeScript/JS files,
    and upsert into store.

    Args:
        repo_dir:       Root of the repository to scan.
        store:          GraphStore instance (FalkorDB or Memory).
        table_owners:   {table_name: owning_service_name} overrides.
        service_filter: Only ingest these service names (for PR head update).
        ingest_openapi: Auto-scan for openapi.yaml/json files (default: True).
        ingest_compose: Auto-scan for docker-compose.yml (default: True).

    Returns:
        Stats dict with counts of ingested nodes.
    """
    import ast as _ast

    table_owners = table_owners or {}
    services = discover_services(repo_dir)

    if service_filter:
        services = [s for s in services if s["name"] in service_filter]

    stats: dict[str, int] = {
        "services": 0,
        "files": 0,
        "symbols": 0,
        "routes": 0,
        "client_calls": 0,
        "table_accesses": 0,
        "topics": 0,
        "openapi_routes": 0,
        "openapi_schemas": 0,
        "compose_services": 0,
    }

    # ── Docker Compose ingestion ───────────────────────────────────────────────
    if ingest_compose:
        try:
            from .openapi_parser import scan_and_ingest_compose
            compose_result = scan_and_ingest_compose(repo_dir, store)
            stats["compose_services"] = compose_result.get("services_found", 0)
        except Exception:
            pass  # Non-fatal: compose parsing is best-effort

    # ── OpenAPI ingestion ─────────────────────────────────────────────────────
    if ingest_openapi:
        try:
            from .openapi_parser import scan_and_ingest_openapi
            oa_stats = scan_and_ingest_openapi(repo_dir, store)
            stats["openapi_routes"] = oa_stats.get("routes", 0)
            stats["openapi_schemas"] = oa_stats.get("schemas", 0)
        except Exception:
            pass  # Non-fatal: openapi parsing is best-effort

    # ── Per-service AST / TS ingestion ────────────────────────────────────────
    for svc in services:
        _upsert_service(store, svc)
        stats["services"] += 1

        svc_path = Path(svc["path"])

        # ── Python files ──────────────────────────────────────────────────────
        for py_file in sorted(svc_path.rglob("*.py")):
            # Skip venv / caches
            if any(p in py_file.parts for p in _SKIP_DIRS):
                continue

            rel_path = str(py_file.relative_to(svc_path)).replace("\\", "/")
            full_rel = f"{svc['name']}/{rel_path}"

            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as fh:
                    src = fh.read()
                tree = _ast.parse(src, filename=str(py_file))
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

        # ── TypeScript / JavaScript files ─────────────────────────────────────
        for ext in _TS_EXTS:
            for ts_file in sorted(svc_path.rglob(f"*{ext}")):
                if any(p in ts_file.parts for p in _SKIP_DIRS):
                    continue
                _ingest_ts_file(store, ts_file, svc, svc_path, stats)

    _derive_calls_edges(store)
    return stats
