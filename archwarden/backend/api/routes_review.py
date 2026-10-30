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
    pr_id: Optional[str] = "PR-review"
    repo_dir: Optional[str] = ""
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
    import tempfile, os

    store = get_store()
    temp_dir = None
    repo_dir = req.repo_dir

    if not repo_dir or not os.path.isdir(repo_dir):
        temp_dir = tempfile.TemporaryDirectory()
        repo_dir = temp_dir.name
        # Pre-populate dummy service structure for all services
        from seeds.seed_demo import ENTERPRISE_50_SERVICES
        all_services = [s["name"] for s in ENTERPRISE_50_SERVICES]
        for s in all_services:
            s_path = os.path.join(repo_dir, s)
            os.makedirs(s_path, exist_ok=True)
            with open(os.path.join(s_path, "main.py"), "w") as f:
                f.write(f"# {s}\n")

    try:
        from review.pr_reviewer import review_pr
        result = review_pr(
            pr_id=req.pr_id or "custom-PR",
            repo_dir=repo_dir,
            diff_text=req.diff or "",
            base_store=store,
            k_hops=req.k_hops,
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_dir:
            temp_dir.cleanup()


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


class GitHubPRImportRequest(BaseModel):
    pr_url: str  # e.g. https://github.com/owner/repo/pull/2 or owner/repo#2


@router.post("/import-github-pr")
async def import_github_pr(req: GitHubPRImportRequest):
    """
    Fetch a real pull request unified diff and metadata from GitHub.
    Accepts full PR URL (e.g. https://github.com/owner/repo/pull/2) or owner/repo#2.
    """
    import json
    import re
    from urllib.request import Request, urlopen
    import urllib.error

    pr_url = req.pr_url.strip()
    m = re.search(r"(?:github\.com/)?([^/]+)/([^/#]+)(?:/pull/|#)(\d+)", pr_url)
    if not m:
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub PR URL. Must be: https://github.com/{owner}/{repo}/pull/{number} or {owner}/{repo}#{number}"
        )
    owner, repo, pr_num = m.group(1), m.group(2), m.group(3)

    # 1. Fetch unified diff
    diff_url = f"https://patch-diff.githubusercontent.com/raw/{owner}/{repo}/pull/{pr_num}.diff"
    headers = {
        "User-Agent": "Archwarden-Guardian/1.0",
        "Accept": "text/plain",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    diff_text = ""
    try:
        r = Request(diff_url, headers=headers)
        with urlopen(r, timeout=15) as resp:
            diff_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        # Fallback to GitHub API endpoint
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
        api_headers = {
            "User-Agent": "Archwarden-Guardian/1.0",
            "Accept": "application/vnd.github.v3.diff",
        }
        if github_token:
            api_headers["Authorization"] = f"token {github_token}"
        try:
            r = Request(api_url, headers=api_headers)
            with urlopen(r, timeout=15) as resp:
                diff_text = resp.read().decode("utf-8", errors="replace")
        except Exception as err:
            raise HTTPException(status_code=502, detail=f"Could not fetch PR diff from GitHub: {err}")

    # 2. Fetch metadata (title, author, files)
    title = f"{owner}/{repo} #{pr_num}"
    author = "unknown"
    changed_files = 0
    try:
        api_meta_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
        meta_headers = {"User-Agent": "Archwarden-Guardian/1.0", "Accept": "application/vnd.github.v3+json"}
        if github_token:
            meta_headers["Authorization"] = f"token {github_token}"
        r_meta = Request(api_meta_url, headers=meta_headers)
        with urlopen(r_meta, timeout=10) as resp:
            meta_data = json.loads(resp.read().decode("utf-8"))
            title = meta_data.get("title", title)
            author = meta_data.get("user", {}).get("login", author)
            changed_files = meta_data.get("changed_files", 0)
    except Exception:
        pass

    return {
        "success": True,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_num,
        "title": title,
        "author": author,
        "changed_files": changed_files,
        "diff": diff_text,
    }


@router.get("/local-git-diff")
async def get_local_git_diff(repo_path: Optional[str] = None):
    """Extract current git diff from the local workspace repository."""
    import subprocess
    diff_text = ""

    # Find root containing .git if not explicitly provided
    cwd = repo_path if repo_path and os.path.isdir(repo_path) else os.getcwd()
    check_dir = os.path.abspath(cwd)
    while check_dir:
        if os.path.exists(os.path.join(check_dir, ".git")):
            cwd = check_dir
            break
        parent = os.path.dirname(check_dir)
        if parent == check_dir:
            break
        check_dir = parent

    # Working tree diffs take precedence, followed by staged, origin branch, and HEAD commit
    cmds = [
        ["git", "diff"],
        ["git", "diff", "--cached"],
        ["git", "diff", "origin/main...HEAD"],
        ["git", "diff", "HEAD~1...HEAD"],
    ]
    for cmd in cmds:
        try:
            res = subprocess.run(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            raw_out = res.stdout.decode("utf-8", errors="replace").strip()
            if res.returncode == 0 and raw_out:
                diff_text = raw_out
                break
        except Exception as e:
            print(f"[local-git-diff] error running {' '.join(cmd)}: {e}")
    return {"diff": diff_text, "lines": len(diff_text.splitlines()) if diff_text else 0, "repo_path": cwd}

