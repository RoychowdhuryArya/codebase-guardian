"""
Archwarden — Principles API Routes
/principles/list, /principles/mine, /principles/candidates
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter()


class MineRequest(BaseModel):
    natural_language_rule: str
    fix_hint: Optional[str] = ""


@router.get("/list")
async def list_principles():
    """List all confirmed principles."""
    try:
        from principles.loader import load_principles
        principles = load_principles()
        return {
            "count": len(principles),
            "principles": [
                {
                    "id": p.id,
                    "statement": p.statement,
                    "kind": p.kind,
                    "severity": p.severity,
                    "status": p.status,
                    "source": p.source,
                    "fix_hint": p.fix_hint,
                    "query": p.check.query,
                }
                for p in principles
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates")
async def list_candidates():
    """List all candidate principles (awaiting human review)."""
    try:
        from principles.loader import load_candidates
        candidates = load_candidates()
        return {
            "count": len(candidates),
            "candidates": [
                {
                    "id": p.id,
                    "statement": p.statement,
                    "severity": p.severity,
                    "status": p.status,
                    "query": p.check.query,
                    "fix_hint": p.fix_hint,
                    "evidence": p.evidence,
                }
                for p in candidates
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mine")
async def mine_principle(req: MineRequest):
    """
    Use Nemotron Super to draft a new Cypher rule from natural language.
    The rule is saved as a candidate (requires human confirmation).
    """
    from main import get_store
    store = get_store()
    try:
        from principles.miner import mine_principle as _mine
        candidate = _mine(
            natural_language_rule=req.natural_language_rule,
            store=store,
            fix_hint=req.fix_hint or "",
        )
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail="Could not generate a valid Cypher rule. Check NVIDIA_API_KEY.",
            )
        return {
            "success": True,
            "candidate": {
                "id": candidate.id,
                "statement": candidate.statement,
                "query": candidate.check.query,
                "fix_hint": candidate.fix_hint,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evaluate/{principle_id}")
async def evaluate_one(principle_id: str):
    """Run a single principle against the base graph and return violations."""
    from main import get_store
    store = get_store()
    try:
        from principles.loader import load_principles
        from principles.evaluator import run_principles
        all_p = load_principles()
        matching = [p for p in all_p if p.id == principle_id]
        if not matching:
            raise HTTPException(status_code=404, detail=f"Principle {principle_id} not found")
        violations = run_principles(store, matching)
        return {
            "principle_id": principle_id,
            "violation_count": len(violations),
            "violations": [v.to_dict() for v in violations],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
