"""GitHub pull-request webhook receiver."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest

router = APIRouter()


def _download_diff(url: str) -> str:
    headers = {"Accept": "application/vnd.github.v3.diff", "User-Agent": "archwarden"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        return response.read().decode("utf-8")


def _checkout_head(payload: dict[str, Any], directory: str) -> str:
    repo = payload.get("pull_request", {}).get("head", {}).get("repo", {}) or {}
    clone_url = repo.get("clone_url") or payload.get("repository", {}).get("clone_url")
    head_sha = payload["pull_request"]["head"]["sha"]
    if not clone_url:
        raise ValueError("GitHub payload does not contain a clone URL")
    subprocess.run(["git", "clone", "--quiet", clone_url, directory], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", directory, "checkout", "--quiet", head_sha], check=True, capture_output=True, text=True)
    return directory


@router.post("/github")
async def github_webhook(request: FastAPIRequest):
    payload = await request.json()
    pull_request = payload.get("pull_request") or {}
    action = payload.get("action")
    if action and action not in {"opened", "synchronize", "reopened"}:
        return {"status": "ignored", "action": payload.get("action")}
    head_sha = pull_request.get("head", {}).get("sha")
    base_sha = pull_request.get("base", {}).get("sha")
    if not head_sha or not base_sha:
        raise HTTPException(status_code=400, detail="pull_request head.sha and base.sha are required")

    diff_url = pull_request.get("diff_url")
    try:
        diff_text = _download_diff(diff_url) if diff_url else payload.get("diff", "")
        supplied_dir = payload.get("repo_dir")
        temp_dir = None
        if supplied_dir:
            repo_dir = str(Path(supplied_dir).resolve())
        else:
            temp_dir = tempfile.mkdtemp(prefix="archwarden-pr-")
            repo_dir = _checkout_head(payload, temp_dir)
        try:
            from main import get_store
            from review.pr_reviewer import review_pr
            result = review_pr(
                pr_id=str(pull_request.get("number") or head_sha[:12]),
                repo_dir=repo_dir,
                diff_text=diff_text,
                base_store=get_store(),
                k_hops=int(os.getenv("ARCHWARDEN_K_HOPS", "2")),
            )
            response = result.to_dict()
            response["head_sha"] = head_sha
            response["base_sha"] = base_sha
            return response
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GitHub PR review failed: {exc}") from exc
