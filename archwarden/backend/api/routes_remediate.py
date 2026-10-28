
"""API endpoint for AI-generated remediation and shadow verification."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm.nemotron_remediator import generate_patch
from review.shadow_patcher import verify_shadow_fix

router = APIRouter()


class RemediateRequest(BaseModel):
    violation_id: str = Field(..., min_length=1)
    principle_statement: str
    file_path: str
    code_snippet: str
    fix_hint: str = ""


@router.post("/remediate")
def remediate(request: RemediateRequest) -> dict[str, Any]:
    """Generate a patch and report shadow verification separately."""

    try:
        ai_result = generate_patch(
            violation_id=request.violation_id,
            principle_statement=request.principle_statement,
            file_path=request.file_path,
            code_snippet=request.code_snippet,
            fix_hint=request.fix_hint,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nemotron remediation failed: {exc}",
        ) from exc

    # Generating a patch does not mean it has been applied or verified.
    verification: dict[str, Any] = {
        "verified": False,
        "message": (
            "Patch generated only. Shadow verification requires a "
            "matching graph violation and a supported simulation."
        ),
    }

    # Only attempt graph verification when a matching store is available.
    try:
        from main import get_store

        store = get_store()
        verification = verify_shadow_fix(
            base_store=store,
            violation_id=request.violation_id,
        )
    except Exception as exc:
        verification = {
            "verified": False,
            "message": f"Shadow verification unavailable: {exc}",
        }

    return {
        "violation_id": request.violation_id,
        "patch": ai_result["patch"],
        "explanation": ai_result["explanation"],
        "verification": verification,
    }
