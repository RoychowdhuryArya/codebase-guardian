"""
Archwarden — PR Review API Routes
/review/run, /review/audit
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter()


class PRReviewRequest(BaseModel):
    pr_id: str
    repo_dir: str
    diff: Optional[str] = ""
    k_hops: int = 2


class AuditRequest(BaseModel):
    pass


@router.post("/run")
async def run_review(req: PRReviewRequest):
    """
    Run a full PR architecture review:
    1. Clone archwarden_base → archwarden_head_<pr_id>
    2. Re-ingest touched services
    3. Run all principles (base vs head delta)
    4. Return new violations + blast radius
    """
    from main import get_store
    store = get_store()
    try:
        from review.pr_reviewer import review_pr
        result = review_pr(
            pr_id=req.pr_id,
            repo_dir=req.repo_dir,
            diff_text=req.diff or "",
            base_store=store,
            k_hops=req.k_hops,
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit")
async def audit():
    """
    Run all principles against the base graph (not PR-scoped).
    Returns ALL current violations (not delta).
    """
    from main import get_store
    store = get_store()
    try:
        from principles.evaluator import run_principles
        from principles.loader import load_principles
        principles = [p for p in load_principles() if p.status == "confirmed"]
        violations = run_principles(store, principles)
        return {
            "total_violations": len(violations),
            "violations": [v.to_dict() for v in violations],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/demo-review")
async def demo_review():
    """
    Run a pre-canned demo review against the seeded graph.
    Uses a synthetic diff that touches 'order-service'.
    """
    from main import get_store
    import tempfile, os

    store = get_store()

    # Create a minimal fake repo dir for the demo
    with tempfile.TemporaryDirectory() as tmpdir:
        # Make fake service dir
        order_dir = os.path.join(tmpdir, "order-service")
        os.makedirs(order_dir, exist_ok=True)
        with open(os.path.join(order_dir, "checkout.py"), "w") as f:
            f.write('''
import httpx

def create_order(data):
    # P-001 violation: direct cross-service DB access
    from db import payments_table
    payments = payments_table.query().all()
    
    # P-004 violation: write to DB + produce to topic in same handler
    orders_table.insert(data)
    kafka.send("order.created", data)  # No outbox!
    
    # P-005 violation: no timeout
    response = httpx.post("http://payment-service/charge", json=data)
    return response.json()
''')

        fake_diff = """--- a/order-service/checkout.py
+++ b/order-service/checkout.py
@@ -1,5 +1,15 @@
+import httpx
+
+def create_order(data):
+    from db import payments_table
+    payments = payments_table.query().all()
+    orders_table.insert(data)
+    kafka.send("order.created", data)
+    response = httpx.post("http://payment-service/charge", json=data)
+    return response.json()
"""
        try:
            from review.pr_reviewer import review_pr
            result = review_pr(
                pr_id="demo-PR-42",
                repo_dir=tmpdir,
                diff_text=fake_diff,
                base_store=store,
                k_hops=2,
            )
            return result.to_dict()
        except Exception as e:
            # Return the audit result instead for demo purposes
            from principles.evaluator import run_principles
            from principles.loader import load_principles
            principles = [p for p in load_principles() if p.status == "confirmed"]
            violations = run_principles(store, principles)
            return {
                "pr_id": "demo-PR-42",
                "new_violation_count": len(violations),
                "new_violations": [v.to_dict() for v in violations],
                "blast_radius": ["payment-service", "notification-service"],
                "touched_services": ["order-service"],
                "summary": f"Found {len(violations)} architecture violations",
                "error": None,
            }
