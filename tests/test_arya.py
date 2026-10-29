from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "archwarden" / "backend"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from archwarden.cli import guardian


class AryaCliTests(unittest.TestCase):
    def test_arya_1_clean_pre_push_returns_zero(self) -> None:
        with patch.object(guardian, "_diff", return_value=""), patch.object(
            guardian,
            "_request",
            return_value={"new_violations": []},
        ), patch.object(guardian, "_git", return_value="feature/test\n"):
            output = StringIO()
            with redirect_stdout(output):
                result = guardian.run_pre_push()

        self.assertEqual(result, 0)
        self.assertIn("0 architectural regressions detected", output.getvalue())

    def test_arya_2_high_violation_rejects_staged_push(self) -> None:
        violation = {
            "principle_id": "P-001",
            "severity": "high",
            "fields": {"from_service": "orders", "table": "payments"},
            "statement": "Cross-service database access",
        }
        with patch.object(guardian, "_diff", return_value="diff --cached"), patch.object(
            guardian,
            "_request",
            return_value={"new_violations": [violation]},
        ), patch.object(guardian, "_git", return_value="feature/test\n"):
            output = StringIO()
            with redirect_stdout(output):
                result = guardian.run_pre_push()

        self.assertEqual(result, 1)
        self.assertIn("push rejected", output.getvalue())
        self.assertIn("P-001", output.getvalue())
        self.assertIn("HIGH", output.getvalue())

    def test_arya_3_install_hook_creates_executable_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".git" / "hooks").mkdir(parents=True)
            with patch.object(guardian, "_git", return_value=f"{root}\n"):
                result = guardian.install_hook()

            hook = root / ".git" / "hooks" / "pre-push"
            self.assertEqual(result, 0)
            self.assertTrue(hook.is_file())
            if os.name != "nt":
                self.assertTrue(stat.S_IMODE(hook.stat().st_mode) & 0o111)
            self.assertIn("-m archwarden.cli.guardian pre-push", hook.read_text())


class AryaWebhookTests(unittest.TestCase):
    def test_arya_4_github_webhook_returns_review_summary(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from archwarden.backend.api import routes_webhook

        app = FastAPI()
        app.include_router(routes_webhook.router, prefix="/webhook")
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 7,
                "head": {"sha": "head-sha"},
                "base": {"sha": "base-sha"},
            },
            "diff": "diff --git a/orders.py b/orders.py",
            "repo_dir": str(REPOSITORY_ROOT),
        }
        fake_result = SimpleNamespace(
            to_dict=lambda: {
                "pr_id": "7",
                "new_violations": [],
                "summary": "✅ No new architecture violations detected.",
            }
        )

        # Exercise the actual HTTP route so status handling is covered.
        with patch.object(
            routes_webhook, "_download_diff", return_value=payload["diff"]
        ), patch.dict(
            sys.modules,
            {
                "main": SimpleNamespace(get_store=lambda: object()),
                "review.pr_reviewer": SimpleNamespace(
                    review_pr=lambda **_: fake_result
                ),
            },
        ):
            response = TestClient(app).post("/webhook/github", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["head_sha"], "head-sha")
        self.assertEqual(body["base_sha"], "base-sha")
        self.assertIn("summary", body)


if __name__ == "__main__":
    unittest.main()
