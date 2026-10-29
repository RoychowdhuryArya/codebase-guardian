"""Developer-facing Archwarden CLI and git hook entry point."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "http://localhost:8080"


def _api_url() -> str:
    return os.getenv("ARCHWARDEN_API_URL", DEFAULT_API_URL).rstrip("/")


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{_api_url()}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=float(os.getenv("ARCHWARDEN_API_TIMEOUT", "120"))) as response:
            data = response.read().decode("utf-8")
            return json.loads(data) if data else {}
    except (HTTPError, URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", exc)
        raise RuntimeError(f"Archwarden API request failed: {detail}") from exc


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "").strip() or str(exc)
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}") from exc
    return result.stdout


def _diff() -> str:
    try:
        diff = _git("diff", "origin/main...HEAD")
    except RuntimeError:
        diff = ""
    if not diff.strip():
        diff = _git("diff", "--cached")
    if not diff.strip():
        diff = _git("diff")
    return diff


def _format_violations(violations: list[dict[str, Any]]) -> str:
    headers = ("Principle", "Severity", "Service", "Evidence")
    rows = []
    for violation in violations:
        fields = violation.get("fields") or violation
        rows.append(
            (
                str(violation.get("principle_id", "?")),
                str(violation.get("severity", "?")).upper(),
                str(fields.get("service") or fields.get("from_service") or "?"),
                str(violation.get("statement") or violation.get("evidence") or "?"),
            )
        )
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    line = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    output = [line, "| " + " | ".join(header.ljust(width) for header, width in zip(headers, widths)) + " |", line]
    output.extend("| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |" for row in rows)
    output.append(line)
    return "\n".join(output)


def install_hook() -> int:
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    hook = root / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    script = "#!/bin/sh\nexec \"${PYTHON:-python}\" -m archwarden.cli.guardian pre-push\n"
    hook.write_text(script, encoding="utf-8")
    try:
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError as exc:
        raise RuntimeError(f"could not make {hook} executable: {exc}") from exc
    print(f"Archwarden pre-push hook installed at {hook}")
    return 0


def run_pre_push() -> int:
    diff = _diff()
    result = _request(
        "POST",
        "/review/run",
        {
            "pr_id": os.getenv("ARCHWARDEN_PR_ID", _git("branch", "--show-current").strip() or "local"),
            "repo_dir": str(Path.cwd().resolve()),
            "diff": diff,
            "k_hops": int(os.getenv("ARCHWARDEN_K_HOPS", "2")),
        },
    )
    violations = result.get("new_violations") or []
    high = [v for v in violations if str(v.get("severity", "")).lower() == "high"]
    if high:
        print("Archwarden: architectural regressions detected; push rejected.")
        print(_format_violations(high))
        return 1
    print("\u2705 Archwarden: 0 architectural regressions detected.")
    return 0


def scan(directory: str) -> int:
    repo_dir = str(Path(directory).expanduser().resolve())
    if not Path(repo_dir).is_dir():
        raise RuntimeError(f"directory not found: {repo_dir}")
    result = _request("POST", "/graph/ingest", {"repo_dir": repo_dir})
    print(json.dumps(result, indent=2))
    return 0


def audit() -> int:
    result = _request("GET", "/review/audit")
    violations = result.get("violations") or []
    print(f"Archwarden system debt: {result.get('total_violations', len(violations))} violation(s)")
    if violations:
        print(_format_violations(violations))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian", description="Archwarden architecture guardrail")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install-hook", help="install the git pre-push hook")
    subparsers.add_parser("pre-push", help="review changes before pushing")
    scan_parser = subparsers.add_parser("scan", help="ingest a repository into the base graph")
    scan_parser.add_argument("directory", nargs="?", default=".")
    subparsers.add_parser("audit", help="display current architecture debt")
    args = parser.parse_args(argv)
    try:
        if args.command == "install-hook":
            return install_hook()
        if args.command == "pre-push":
            return run_pre_push()
        if args.command == "scan":
            return scan(args.directory)
        return audit()
    except RuntimeError as exc:
        print(f"Archwarden: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
