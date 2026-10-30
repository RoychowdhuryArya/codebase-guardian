"""
Archwarden — Breaking API Change Detection Engine
Analyzes unified diffs for modifications to existing API routes and queries
FalkorDB to identify downstream services broken by the change.

Detects:
  P-006a: Route Deleted          — an existing route URL is removed from code
  P-006b: HTTP Method Altered    — e.g. GET /orders → POST /orders
  P-006c: Path Parameter Changed — e.g. /orders/{id} → /orders/{order_uuid}

Violation severity: critical
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from graph.store_protocol import GraphStore


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class RouteChange:
    """Describes a single detected change to an API route."""

    kind: str                   # "deleted" | "method_altered" | "param_changed"
    old_method: str
    old_path: str
    new_method: str = ""
    new_path: str = ""
    service: str = ""
    file: str = ""


@dataclass
class BreakingViolation:
    """P-006: Breaking API Contract violation."""

    rule_id: str = "P-006"
    severity: str = "critical"
    kind: str = ""              # sub-kind from RouteChange
    old_method: str = ""
    old_path: str = ""
    new_method: str = ""
    new_path: str = ""
    changed_in_service: str = ""
    broken_service: str = ""
    caller_file: str = ""
    caller_line: int = 0
    evidence: str = ""


# ── Route pattern extraction from diff lines ──────────────────────────────────

# Matches: @app.get("/path"), router.post('/path'), app.route('/path')
_PY_ROUTE = re.compile(
    r"""(?:@(?:app|router|api|blueprint)\s*\.\s*(get|post|put|delete|patch|options|head|route)\s*\(\s*['"`]([^'"`]+)['"`])""",
    re.IGNORECASE,
)

# Express / Next.js: app.get('/path'), router.post('/path')
_TS_EXPR_ROUTE = re.compile(
    r"""(?:app|router|server)\s*\.\s*(get|post|put|delete|patch|options|head)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# Next.js App Router exported handler
_TS_NEXT_ROUTE = re.compile(
    r"""export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\("""
)

# Path parameter patterns: {param} or :param or [param]
_PATH_PARAM = re.compile(r"\{([^}]+)\}|:([A-Za-z_]\w*)|(?<=/)(\[[^\]]+\])(?=/|$)")


def _normalize_param(path: str) -> str:
    """Normalize all path params to {*} for structural comparison."""
    return re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*|\[[^\]]+\]", "{*}", path)


def _extract_routes_from_lines(lines: list[str]) -> list[tuple[str, str]]:
    """
    Extract (METHOD, path_template) tuples from a list of source lines.
    Used to parse added/removed diff hunks.
    """
    routes: list[tuple[str, str]] = []
    for line in lines:
        for m in _PY_ROUTE.finditer(line):
            method = m.group(1).upper()
            path = m.group(2)
            routes.append((method, path))
        for m in _TS_EXPR_ROUTE.finditer(line):
            method = m.group(1).upper()
            path = m.group(2)
            routes.append((method, path))
        for m in _TS_NEXT_ROUTE.finditer(line):
            method = m.group(1).upper()
            routes.append((method, "__nextjs_inferred__"))
    return routes


# ── Diff analysis ─────────────────────────────────────────────────────────────


def detect_route_changes(diff_hunks: list[dict]) -> list[RouteChange]:
    """
    Given a list of diff hunks [{file, added, removed}], return all
    RouteChange events detected across the diff.

    Args:
        diff_hunks: Output of ``ingest.diff_linker.parse_unified_diff``.

    Returns:
        List of RouteChange objects.
    """
    changes: list[RouteChange] = []

    for hunk in diff_hunks:
        file_path: str = hunk.get("file", "")
        added_lines: list[str] = hunk.get("added", [])
        removed_lines: list[str] = hunk.get("removed", [])

        added_routes = _extract_routes_from_lines(added_lines)
        removed_routes = _extract_routes_from_lines(removed_lines)

        added_set = set(added_routes)
        removed_set = set(removed_routes)

        # Index removed routes by normalized path for param comparison
        removed_by_norm: dict[str, tuple[str, str]] = {
            _normalize_param(path): (method, path)
            for method, path in removed_routes
        }
        added_by_norm: dict[str, tuple[str, str]] = {
            _normalize_param(path): (method, path)
            for method, path in added_routes
        }

        # Detect: Route fully deleted (in removed, not in added by any norm)
        for method, path in removed_set:
            norm = _normalize_param(path)
            if (method, path) not in added_set:
                if norm not in added_by_norm:
                    # Truly deleted — not re-added with different params
                    changes.append(RouteChange(
                        kind="deleted",
                        old_method=method,
                        old_path=path,
                        file=file_path,
                    ))
                else:
                    # Same structural path, same method — path param rename
                    new_method, new_path = added_by_norm[norm]
                    if new_method == method and new_path != path:
                        changes.append(RouteChange(
                            kind="param_changed",
                            old_method=method,
                            old_path=path,
                            new_method=new_method,
                            new_path=new_path,
                            file=file_path,
                        ))

        # Detect: HTTP Method Altered — same path different method
        removed_by_path: dict[str, str] = {path: method for method, path in removed_routes}
        added_by_path: dict[str, str] = {path: method for method, path in added_routes}

        for path, old_method in removed_by_path.items():
            if path in added_by_path:
                new_method = added_by_path[path]
                if new_method != old_method:
                    changes.append(RouteChange(
                        kind="method_altered",
                        old_method=old_method,
                        old_path=path,
                        new_method=new_method,
                        new_path=path,
                        file=file_path,
                    ))

    return changes


# ── FalkorDB blast radius query ───────────────────────────────────────────────

_BLAST_CYPHER = """
MATCH (s:Service)-[:CONTAINS*1..3]->(:Symbol)-[:MAKES_CALL]->(cc:ClientCall)
MATCH (cc)-[:RESOLVES_TO]->(r:Route)
WHERE r.path_template = $modified_path
  AND ($method = '' OR r.method = $method)
  AND (cc.method IS NULL OR cc.method = '' OR $method = '' OR cc.method = r.method)
RETURN s.name AS broken_service, cc.file AS caller_file, cc.line AS caller_line
"""


def query_blast_radius(
    store: GraphStore,
    path_template: str,
    method: str = "",
) -> list[dict[str, Any]]:
    """
    Query FalkorDB for all services that call a given route path and method.

    Args:
        store:         Read-only-capable GraphStore (FalkorDB or Memory).
        path_template: The route path that was modified/deleted.
        method:        The HTTP method that was modified/deleted (e.g. 'GET', 'POST').
                       If omitted or empty, matches any method.

    Returns:
        List of {broken_service, caller_file, caller_line} dicts.
    """
    params = {
        "modified_path": path_template,
        "method": (method or "").upper(),
    }
    rows = store.ro_query(_BLAST_CYPHER, params)
    results = []
    for row in rows:
        results.append({
            "broken_service": row[0] if len(row) > 0 else "",
            "caller_file": row[1] if len(row) > 1 else "",
            "caller_line": int(row[2]) if len(row) > 2 and row[2] is not None else 0,
        })
    return results


# ── Top-level API ─────────────────────────────────────────────────────────────


def analyze_breaking_changes(
    diff_hunks: list[dict],
    store: GraphStore,
    service_name: str = "",
) -> list[BreakingViolation]:
    """
    End-to-end breaking-change analysis:
      1. Detect route changes from the diff.
      2. For each change, query FalkorDB to find affected downstream services.
      3. Return a list of BreakingViolation (P-006) items.

    Args:
        diff_hunks:   Output of ``ingest.diff_linker.parse_unified_diff``.
        store:        GraphStore (FalkorDB preferred; memory fallback supported).
        service_name: Name of the service that owns the changed file (optional).

    Returns:
        List of BreakingViolation objects. Empty list means no breaking changes.
    """
    violations: list[BreakingViolation] = []

    route_changes = detect_route_changes(diff_hunks)
    if not route_changes:
        return violations

    for change in route_changes:
        # Query FalkorDB for services calling the old (modified/deleted) route
        blast = query_blast_radius(store, change.old_path, change.old_method)

        if blast:
            for hit in blast:
                violations.append(BreakingViolation(
                    rule_id="P-006",
                    severity="critical",
                    kind=change.kind,
                    old_method=change.old_method,
                    old_path=change.old_path,
                    new_method=change.new_method,
                    new_path=change.new_path,
                    changed_in_service=service_name or change.file,
                    broken_service=hit["broken_service"],
                    caller_file=hit["caller_file"],
                    caller_line=hit["caller_line"],
                    evidence=f"{change.file} → {hit['caller_file']}:{hit['caller_line']}",
                ))
        else:
            # No known callers — still report as a potential unresolved reference
            violations.append(BreakingViolation(
                rule_id="P-006",
                severity="critical",
                kind=change.kind,
                old_method=change.old_method,
                old_path=change.old_path,
                new_method=change.new_method,
                new_path=change.new_path,
                changed_in_service=service_name or change.file,
                broken_service="UNRESOLVED",
                caller_file="",
                caller_line=0,
                evidence=f"{change.file} — no resolved callers in graph",
            ))

    return violations


def violations_to_dicts(violations: list[BreakingViolation]) -> list[dict[str, Any]]:
    """Serialize violations to plain dicts (JSON-serializable)."""
    return [
        {
            "rule_id": v.rule_id,
            "severity": v.severity,
            "kind": v.kind,
            "old_method": v.old_method,
            "old_path": v.old_path,
            "new_method": v.new_method,
            "new_path": v.new_path,
            "changed_in_service": v.changed_in_service,
            "broken_service": v.broken_service,
            "caller_file": v.caller_file,
            "caller_line": v.caller_line,
            "evidence": v.evidence,
        }
        for v in violations
    ]
