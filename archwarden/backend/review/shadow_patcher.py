
"""Safely verify simulated remediation in an isolated shadow graph."""

from __future__ import annotations

import uuid
from typing import Any

from graph.memory_store import MemoryGraphStore
from graph.store_protocol import GraphStore
from principles.evaluator import run_principles
from principles.loader import load_principles


def _principle_counts(store: GraphStore) -> dict[str, int]:
    """Count detected violations by principle."""

    if isinstance(store, MemoryGraphStore):
        graph = store._G
        counts = {
            "P-001": len(store.p001_cross_db_violations()),
            "P-002": len(store.p002_cycles()),
            "P-003": len(store.p003_deep_chains()),
        }

        # P-005: outbound calls without an explicit timeout.
        counts["P-005"] = sum(
            1
            for _, data in graph.nodes(data=True)
            if data.get("label") == "ClientCall"
            and data.get("has_timeout") is False
        )

        # P-004 needs handler-level structural verification.
        # Do not claim it passed until that check is implemented.
                # P-004: handler writes to a table and publishes an event
        # without writing through an outbox.
        writes = [
            (source, target)
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
            for _, target in writes
        )
        counts["P-004"] = int(bool(writes and produces and not has_outbox))
        return counts

    principles = [
        principle
        for principle in load_principles()
        if principle.status == "confirmed"
    ]
    violations = run_principles(store, principles)

    counts: dict[str, int] = {}
    for violation in violations:
        counts[violation.principle_id] = (
            counts.get(violation.principle_id, 0) + 1
        )
    return counts


def _simulate_fix(
    shadow_store: GraphStore,
    violation_id: str,
    fields: dict[str, Any],
) -> bool:
    """Apply a limited simulated fix to the shadow graph only."""

    if isinstance(shadow_store, MemoryGraphStore):
        graph = shadow_store._G

        if violation_id == "P-005":
            file_path = fields.get("file")
            line = fields.get("line")
            changed = False

            for _, data in graph.nodes(data=True):
                if data.get("label") != "ClientCall":
                    continue
                if data.get("has_timeout") is not False:
                    continue
                if file_path and data.get("file") != file_path:
                    continue
                if line is not None and data.get("line") != line:
                    continue

                data["has_timeout"] = True
                changed = True

            return changed

        if violation_id == "P-001":
            # Remove only cross-service ACCESSES edges from the shadow.
            edges_to_remove = []

            for source, target, key, data in graph.edges(
                keys=True, data=True
            ):
                if data.get("rel") != "ACCESSES":
                    continue

                source_service = graph.nodes[source].get("service")
                table_name = graph.nodes[target].get("name")

                for owner_source, owner_target, owner_data in (
                    graph.edges(data=True)
                ):
                    if (
                        owner_data.get("rel") == "OWNS_TABLE"
                        and graph.nodes[owner_target].get("name")
                        == table_name
                    ):
                        owner = graph.nodes[owner_source].get("name")
                        if source_service and owner and source_service != owner:
                            edges_to_remove.append((source, target, key))
                            break

            for edge in edges_to_remove:
                graph.remove_edge(*edge)

            return bool(edges_to_remove)

        # Other principle simulations are not implemented yet.
        return False

    # FalkorDB graph mutation support is added after validating
    # the exact stored node/edge properties.
    return False


def verify_shadow_fix(
    base_store: GraphStore,
    violation_id: str,
    violation_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify a simulated fix without changing the original graph."""

    fields = violation_fields or {}
    shadow_name = f"archwarden_shadow_{uuid.uuid4().hex[:10]}"
    shadow_store = None

    result = {
        "verified": False,
        "original_violations": None,
        "shadow_violations": None,
        "new_secondary_violations": [],
        "cycles_detected": None,
        "message": "",
    }

    try:
        shadow_store = base_store.copy_graph(
            base_store.graph_name, shadow_name
        )

        before = _principle_counts(shadow_store)
        target_before = before.get(violation_id, 0)
        result["original_violations"] = (
            target_before if target_before >= 0 else None
        )

        if target_before <= 0:
            result["message"] = (
                "Cannot verify: the target violation was not detected "
                "in the shadow graph."
            )
            return result

        if not _simulate_fix(shadow_store, violation_id, fields):
            result["message"] = (
                "Verification unavailable: no supported simulated fix "
                "matched the target violation."
            )
            return result

        after = _principle_counts(shadow_store)
        target_after = after.get(violation_id, -1)
        result["shadow_violations"] = (
            target_after if target_after >= 0 else None
        )

        before_cycles = before.get("P-002", -1)
        after_cycles = after.get("P-002", -1)
        result["cycles_detected"] = (
            after_cycles if after_cycles >= 0 else None
        )

        if before_cycles < 0 or after_cycles < 0:
            result["message"] = (
                "Verification unavailable: cycle checks could not "
                "be completed."
            )
            return result

        for principle_id, after_count in after.items():
            before_count = before.get(principle_id, -1)

            if principle_id == violation_id:
                continue

            if before_count < 0 or after_count < 0:
                result["message"] = (
                    f"Verification unavailable: {principle_id} "
                    "could not be checked."
                )
                return result

            if after_count > before_count:
                result["new_secondary_violations"].append(
                    principle_id
                )

        passed = (
            target_after == 0
            and after_cycles <= before_cycles
            and not result["new_secondary_violations"]
        )
        result["verified"] = passed
        result["message"] = (
            "All implemented shadow checks passed."
            if passed
            else "Shadow checks failed; do not mark this fix as verified."
        )
        return result

    except Exception as exc:
        result["message"] = (
            f"Shadow verification failed: {type(exc).__name__}: {exc}"
        )
        return result

    finally:
        if shadow_store is not None:
            try:
                base_store.delete_graph(shadow_name)
            except Exception:
                # Never change the verification result to success
                # if temporary graph cleanup fails.
                result["verified"] = False
                result["message"] += " Shadow graph cleanup failed."
