"""
Archwarden — TypeScript / JavaScript AST & Route Extractor
Parses JS/TS files to extract:
  - Route definitions (Express, Next.js App Router, FastAPI/Flask)
  - Client calls (fetch, axios, httpx)
  - Emits Route and ClientCall node dicts compatible with the FalkorDB schema.

NOTE: Pure-Python implementation using regex and line-by-line analysis — no
Node.js or external toolchain required. This is intentional so the backend
container stays Python-only.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ── Pattern library ───────────────────────────────────────────────────────────

# Express: app.get('/path', ...) | router.post('/path', ...)
_EXPR_ROUTE = re.compile(
    r"""(?:app|router|server)\s*\.\s*(get|post|put|delete|patch|options|head|use)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# Next.js App Router: export async function GET(req) / export function POST(request)
_NEXT_ROUTE = re.compile(
    r"""export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\(""",
)

# FastAPI/Flask style in TS (rare but seen in isomorphic SSR codegen):
# app.route('/path', { methods: ['GET'] })
_FLASK_ROUTE_TS = re.compile(
    r"""app\s*\.\s*route\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# fetch('https://...', { method: 'POST' }) — and bare fetch('/api/...')
_FETCH_CALL = re.compile(
    r"""fetch\s*\(\s*['"`]([^'"`]+)['"`](?:\s*,\s*\{[^}]*method\s*:\s*['"`](\w+)['"`])?""",
    re.IGNORECASE,
)

# axios.get('/url') | axios.post(url) | axios({ url: '...', method: '...' })
_AXIOS_CALL = re.compile(
    r"""axios\s*\.\s*(get|post|put|delete|patch|head|options)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# httpx.get / httpx.post (used in edge-runtime / SSR Python-mirroring)
_HTTPX_CALL = re.compile(
    r"""httpx\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# Detect timeout presence: { timeout: ... } or signal: AbortSignal.timeout(...)
_HAS_TIMEOUT = re.compile(
    r"""timeout\s*[:=]|AbortSignal\.timeout""",
    re.IGNORECASE,
)

# URL parse helper
_URL_PARSE = re.compile(r"https?://([^/]+)(.*)")


def _parse_url(url: str) -> tuple[str, str]:
    """Return (target_hint, path) from a URL string."""
    m = _URL_PARSE.match(url)
    if m:
        return m.group(1), m.group(2) or "/"
    # Relative URL
    return "unknown", url if url.startswith("/") else f"/{url}"


# ── Main extractor ────────────────────────────────────────────────────────────


class TSExtractor:
    """
    Parses a single TypeScript / JavaScript file and collects:
      - routes:       list[dict]  — Route node dicts
      - client_calls: list[dict]  — ClientCall node dicts
    """

    def __init__(self, file_path: str, service_name: str):
        self.file_path = file_path
        self.service_name = service_name
        self.routes: list[dict[str, Any]] = []
        self.client_calls: list[dict[str, Any]] = []

    def extract(self, source: str) -> None:
        """Run all extractors against source text."""
        self._extract_routes(source)
        self._extract_client_calls(source)

    # ── Route extraction ──────────────────────────────────────────────────────

    def _extract_routes(self, source: str) -> None:
        lines = source.splitlines()

        # Express router patterns — scan line by line for accurate line numbers
        for lineno, line in enumerate(lines, start=1):
            # Express / Koa / Fastify style
            for m in _EXPR_ROUTE.finditer(line):
                self.routes.append({
                    "method": m.group(1).upper(),
                    "path_template": m.group(2),
                    "protocol": "http",
                    "service": self.service_name,
                    "file": self.file_path,
                    "line": lineno,
                    "handler_qname": f"{self.service_name}::ts_handler@L{lineno}",
                })

            # Next.js App Router — exported HTTP method functions
            for m in _NEXT_ROUTE.finditer(line):
                # Infer path from file location (Next.js convention)
                path = self._nextjs_path_from_file(self.file_path)
                self.routes.append({
                    "method": m.group(1).upper(),
                    "path_template": path,
                    "protocol": "http",
                    "service": self.service_name,
                    "file": self.file_path,
                    "line": lineno,
                    "handler_qname": f"{self.service_name}::nextjs_{m.group(1).lower()}@L{lineno}",
                })

            # Flask-style TS route
            for m in _FLASK_ROUTE_TS.finditer(line):
                self.routes.append({
                    "method": "GET",  # default; methods block parsed separately if needed
                    "path_template": m.group(1),
                    "protocol": "http",
                    "service": self.service_name,
                    "file": self.file_path,
                    "line": lineno,
                    "handler_qname": f"{self.service_name}::ts_route@L{lineno}",
                })

    @staticmethod
    def _nextjs_path_from_file(file_path: str) -> str:
        """
        Derive the URL path from a Next.js App Router file path.
        E.g. app/api/orders/[id]/route.ts → /api/orders/{id}
        """
        p = Path(file_path)
        # Collect path parts starting after 'app' directory
        parts = list(p.parts)
        try:
            idx = next(i for i, x in enumerate(parts) if x == "app")
            parts = parts[idx + 1:]
        except StopIteration:
            pass

        # Drop route.ts / route.js / page.tsx etc.
        if parts and parts[-1] in ("route.ts", "route.tsx", "route.js", "page.tsx", "page.ts"):
            parts = parts[:-1]

        # Convert [param] → {param}
        parts = [re.sub(r"^\[(.+)\]$", r"{\1}", part) for part in parts]

        return "/" + "/".join(parts) if parts else "/"

    # ── Client call extraction ────────────────────────────────────────────────

    def _extract_client_calls(self, source: str) -> None:
        lines = source.splitlines()

        for lineno, line in enumerate(lines, start=1):
            has_timeout = bool(_HAS_TIMEOUT.search(line))

            # fetch(...)
            for m in _FETCH_CALL.finditer(line):
                url = m.group(1)
                method = (m.group(2) or "GET").upper()
                target, path = _parse_url(url)
                self.client_calls.append(self._make_cc(target, method, path, lineno, has_timeout))

            # axios.<method>(url)
            for m in _AXIOS_CALL.finditer(line):
                method = m.group(1).upper()
                url = m.group(2)
                target, path = _parse_url(url)
                self.client_calls.append(self._make_cc(target, method, path, lineno, has_timeout))

            # httpx.<method>(url)
            for m in _HTTPX_CALL.finditer(line):
                method = m.group(1).upper()
                url = m.group(2)
                target, path = _parse_url(url)
                self.client_calls.append(self._make_cc(target, method, path, lineno, has_timeout))

    def _make_cc(
        self,
        target_hint: str,
        method: str,
        path: str,
        line: int,
        has_timeout: bool,
    ) -> dict[str, Any]:
        return {
            "caller_qname": f"{self.service_name}::ts_caller@L{line}",
            "target_hint": target_hint,
            "method": method,
            "path": path,
            "file": self.file_path,
            "line": line,
            "service": self.service_name,
            "resolved": False,
            "resolution_source": "UNRESOLVED",
            "has_timeout": has_timeout,
        }


# ── Module-level convenience function ─────────────────────────────────────────


def extract_ts_file(
    file_path: str,
    service_name: str,
    source: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Parse a TS/JS file and return (routes, client_calls).

    Args:
        file_path:    Relative path used as node identity in the graph.
        service_name: Owning service name.
        source:       Source text. If None, the file is read from disk.

    Returns:
        (routes, client_calls) — lists of dicts ready for FalkorDB upsert.
    """
    if source is None:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            source = fh.read()

    extractor = TSExtractor(file_path, service_name)
    extractor.extract(source)
    return extractor.routes, extractor.client_calls
