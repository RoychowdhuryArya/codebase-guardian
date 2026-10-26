"""
Archwarden — PR Reviewer
Orchestrates the base→head graph branching and violation diffing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from graph.falkor_store import FalkorGraphStore
from graph.store_protocol import GraphStore
from ingest.repo_walker import ingest_repo
from ingest.diff_linker import diff_to_services
from principles.evaluator import run_principles, delta_violations, Violation
from principles.loader import load_principles


BASE_GRAPH = "archwarden_base"


@dataclass
class PRReviewResult:
    pr_id: str
    base_graph: str
    head_graph: str
    touched_services: list[str]
    base_violations: list[Violation]
    head_violations: list[Violation]
    new_violations: list[Violation]
    blast_radius: list[str]
    summary: str
    duration_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "pr_id": self.pr_id,
            "base_graph": self.base_graph,
            "head_graph": self.head_graph,
            "touched_services": self.touched_services,
            "new_violations": [v.to_dict() for v in self.new_violations],
            "base_violation_count": len(self.base_violations),
            "head_violation_count": len(self.head_violations),
            "new_violation_count": len(self.new_violations),
            "blast_radius": self.blast_radius,
            "summary": self.summary,
            "duration_ms": round(self.duration_ms, 1),
            "error": self.error,
        }


def review_pr(
    pr_id: str,
    repo_dir: str,
    diff_text: str,
    base_store: GraphStore,
    k_hops: int = 2,
) -> PRReviewResult:
    """
    Full PR review:
    1. Clone archwarden_base → archwarden_head_<pr_id>
    2. Re-ingest only the touched services into head
    3. Run principles on both base and head
    4. Compute delta (new violations only)
    5. Compute blast radius
    6. Generate summary
    7. Clean up head graph
    """
    t0 = time.time()
    head_graph_name = f"archwarden_head_{pr_id.replace('/', '_').replace('#', '')}"
    error: Optional[str] = None
    head_store: Optional[GraphStore] = None

    try:
        # ── 1. Discover touched services ──────────────────────────────────────
        from ingest.repo_walker import discover_services
        known_services = [s["name"] for s in discover_services(repo_dir)]
        touched = diff_to_services(diff_text, known_services)
        if not touched:
            touched = known_services  # No diff info — assume all touched

        # ── 2. Clone base → head ──────────────────────────────────────────────
        if isinstance(base_store, FalkorGraphStore):
            head_store = base_store.copy_graph(BASE_GRAPH, head_graph_name)
        else:
            head_store = base_store  # Memory fallback — in-place

        # ── 3. Re-ingest touched services into head ───────────────────────────
        ingest_repo(repo_dir, head_store, service_filter=touched)

        # ── 4. Evaluate principles on both graphs ─────────────────────────────
        principles = [p for p in load_principles() if p.status == "confirmed"]
        base_violations = run_principles(base_store, principles)
        head_violations = run_principles(head_store, principles)

        # ── 5. Compute delta (new violations only) ────────────────────────────
        new_violations = delta_violations(base_violations, head_violations)

        # ── 6. Compute blast radius (k-hop CALLS reachability) ────────────────
        blast = _blast_radius(head_store, touched, k_hops)

        # ── 7. Generate summary ───────────────────────────────────────────────
        summary = _build_summary(pr_id, touched, new_violations, blast)

    except Exception as e:
        error = str(e)
        base_violations = []
        head_violations = []
        new_violations = []
        blast = []
        touched = []
        summary = f"Review failed: {error}"
        print(f"[PR Review] Error for PR {pr_id}: {e}")

    finally:
        # ── 8. Clean up head graph ────────────────────────────────────────────
        if head_store and isinstance(head_store, FalkorGraphStore) and head_store.graph_name != BASE_GRAPH:
            try:
                base_store.delete_graph(head_graph_name)
            except Exception:
                pass

    duration_ms = (time.time() - t0) * 1000

    return PRReviewResult(
        pr_id=pr_id,
        base_graph=BASE_GRAPH,
        head_graph=head_graph_name,
        touched_services=touched,
        base_violations=base_violations,
        head_violations=head_violations,
        new_violations=new_violations,
        blast_radius=blast,
        summary=summary,
        duration_ms=duration_ms,
        error=error,
    )


def _blast_radius(store: GraphStore, touched: list[str], k_hops: int) -> list[str]:
    """k-hop CALLS reachability from touched services."""
    if not touched:
        return []
    affected = set()
    for svc in touched:
        try:
            rows = store.ro_query(
                f"MATCH (s:Service {{name: $svc}})-[:CALLS*1..{k_hops}]-(o:Service) "
                "RETURN DISTINCT o.name AS name",
                {"svc": svc},
            )
            for row in rows:
                if row and row[0]:
                    affected.add(str(row[0]))
        except Exception:
            pass
    return sorted(affected - set(touched))


def _build_summary(
    pr_id: str,
    touched: list[str],
    violations: list[Violation],
    blast: list[str],
) -> str:
    lines = [
        f"## Archwarden Review — PR {pr_id}",
        f"",
        f"**Touched services:** {', '.join(touched) or 'none'}",
        f"**Blast radius ({len(blast)} services):** {', '.join(blast) or 'none'}",
        f"**New violations:** {len(violations)}",
    ]
    if violations:
        lines.append("")
        lines.append("### Violations")
        for v in violations:
            svc = v.fields.get("service") or v.fields.get("from_service", "?")
            lines.append(f"- **[{v.principle_id}]** `{svc}` — {v.statement}")
            lines.append(f"  > Fix: {v.fix_hint}")
    else:
        lines.append("")
        lines.append("✅ No new architecture violations detected.")
    return "\n".join(lines)
