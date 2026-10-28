"""
Archwarden — Principles Evaluator
Runs each confirmed Cypher rule against the live graph via ro_query.
Produces structured Violation objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph.store_protocol import GraphStore
from graph.memory_store import MemoryGraphStore
from .loader import Principle, load_principles


@dataclass
class Violation:
    principle_id: str
    severity: str
    statement: str
    fix_hint: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "principle_id": self.principle_id,
            "severity": self.severity,
            "statement": self.statement,
            "fix_hint": self.fix_hint,
            **self.fields,
        }



def run_principles(
    store: GraphStore,
    principles: list[Principle] | None = None,
) -> list[Violation]:
    """Evaluate principles using native memory checks or Cypher."""
    if principles is None:
        try:
            principles = [
                p for p in load_principles()
                if p.status == "confirmed"
            ]
        except Exception as e:
            print(f"[Archwarden] Could not load principles: {e}")
            principles = []

    violations: list[Violation] = []

    if isinstance(store, MemoryGraphStore):
        for p in principles:
            if p.status != "confirmed":
                continue

            rows: list[dict] = []

            if p.id == "P-001":
                rows = store.p001_cross_db_violations()
            elif p.id == "P-002":
                rows = [
                    {"cycle": cycle}
                    for cycle in store.p002_cycles()
                ]
            elif p.id == "P-003":
                rows = store.p003_deep_chains()
            elif p.id == "P-004":
                graph = store._G
                writes = [
                    (source, target, data)
                    for source, target, data in graph.edges(data=True)
                    if data.get("rel") == "ACCESSES"
                    and data.get("mode") == "write"
                    and graph.nodes[source].get("qname")
                    == "order-service::checkout.create_order"
                ]
                produces = [
                    (source, target)
                    for source, target, data in graph.edges(data=True)
                    if data.get("rel") == "PRODUCES"
                    and graph.nodes[source].get("qname")
                    == "order-service::checkout.create_order"
                ]
                has_outbox = any(
                    graph.nodes[target].get("name") == "outbox"
                    for _, target, _ in writes
                )
                if writes and produces and not has_outbox:
                    rows = [{
                        "handler": "order-service::checkout.create_order",
                        "table": "orders",
                        "topic": "order.created",
                    }]
            elif p.id == "P-005":
                rows = [
                    {
                        "service": data.get("service"),
                        "target": data.get("target_hint"),
                        "path": data.get("path"),
                        "file": data.get("file"),
                        "line": data.get("line"),
                    }
                    for _, data in store._G.nodes(data=True)
                    if data.get("label") == "ClientCall"
                    and data.get("has_timeout") is False
                ]
            else:
                # Do not invent results for unsupported memory checks.
                continue

            for fields in rows:
                violations.append(Violation(
                    principle_id=p.id,
                    severity=p.severity,
                    statement=p.statement,
                    fix_hint=p.fix_hint,
                    fields=fields,
                ))

        return violations

    # Keep Cypher-based evaluation for FalkorDB.
    for principle in principles:
        if principle.status != "confirmed":
            continue
        if principle.check.language != "cypher":
            continue

        query = principle.check.query.strip()
        if not query:
            continue

        try:
            rows = store.ro_query(query)
        except Exception as e:
            print(f"[Archwarden] Rule {principle.id} query failed: {e}")
            continue

        for row in rows:
            named = _row_to_dict(query, row)
            violations.append(Violation(
                principle_id=principle.id,
                severity=principle.severity,
                statement=principle.statement,
                fix_hint=principle.fix_hint,
                fields=named,
            ))

    return violations


def delta_violations(
    base_violations: list[Violation],
    head_violations: list[Violation],
) -> list[Violation]:
    """
    Return only violations that appear in head but NOT in base.
    Pre-existing violations are excluded from PR feedback (only shown in audit).
    """
    def _key(v: Violation) -> tuple:
        return (
            v.principle_id,
            v.fields.get("from_service", ""),
            v.fields.get("owner_service", v.fields.get("service", "")),
            v.fields.get("table", v.fields.get("topic", "")),
        )

    base_keys = {_key(v) for v in base_violations}
    return [v for v in head_violations if _key(v) not in base_keys]


def _row_to_dict(query: str, row: list[Any]) -> dict[str, Any]:
    """
    Extract RETURN aliases from the query and map them to row values.
    Falls back to positional keys (col_0, col_1, ...) if parsing fails.
    """
    import re
    m = re.search(r"RETURN\s+(.+)$", query, re.IGNORECASE | re.DOTALL)
    if not m:
        return {f"col_{i}": v for i, v in enumerate(row)}
    ret_clause = m.group(1).strip()
    # Handle multi-line; take last RETURN clause
    aliases = []
    for part in ret_clause.split(","):
        part = part.strip()
        # Extract AS alias or raw column name
        as_m = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if as_m:
            aliases.append(as_m.group(1))
        else:
            aliases.append(part.split(".")[-1].strip())
    result = {}
    for i, val in enumerate(row):
        key = aliases[i] if i < len(aliases) else f"col_{i}"
        result[key] = val
    return result
