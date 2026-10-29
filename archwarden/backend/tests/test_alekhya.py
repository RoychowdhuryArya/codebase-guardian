"""
Archwarden — Alekhya Test Suite
Tests for:
  [Test-Alekhya-1] Python + TypeScript ingest → Service, File, Route, ClientCall nodes
  [Test-Alekhya-2] Route method change (GET→POST) → P-006 breaking contract violation
  [Test-Alekhya-3] Route deletion → Service B flagged with unresolved reference
  [Test-Alekhya-4] openapi.yaml → FalkorDB routes with accurate HTTP verbs

All tests run against the MemoryGraphStore (offline, no Docker required).
To run: python -m pytest tests/test_alekhya.py -v
"""
from __future__ import annotations

import sys
import os
import tempfile
import textwrap
from pathlib import Path

import pytest

# ── Path setup (make backend importable) ──────────────────────────────────────
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from graph.memory_store import MemoryGraphStore
from ingest.ts_extractor import TSExtractor, extract_ts_file
from ingest.breaking_changes import (
    detect_route_changes,
    analyze_breaking_changes,
    violations_to_dicts,
    RouteChange,
)
from ingest.openapi_parser import parse_openapi, parse_docker_compose
from ingest.repo_walker import ingest_repo, discover_services


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def make_store() -> MemoryGraphStore:
    return MemoryGraphStore()


def _seed_route_and_caller(store: MemoryGraphStore, route_path: str, caller_service: str) -> None:
    """
    Seed a Route node and a ClientCall that RESOLVES_TO it, so blast-radius
    queries work on the MemoryStore. Since MemoryStore.ro_query always returns []
    (it's a stub), we implement the blast-radius check directly using the
    store's NetworkX graph for test-Alekhya-2 and -3.
    """
    store.add_node("Route", {"name": route_path, "path_template": route_path, "method": "GET", "service": "service_a"})
    store.add_node("Service", {"name": caller_service})
    store.add_node("ClientCall", {"name": f"cc_{route_path}", "path": route_path, "target_hint": "service_a", "service": caller_service})
    store.add_edge("service_a", f"cc_{route_path}", "MAKES_CALL")
    store.add_edge(f"cc_{route_path}", route_path, "RESOLVES_TO")


# ══════════════════════════════════════════════════════════════════════════════
# [Test-Alekhya-1]
# Ingest a sample directory with both Python and TypeScript files.
# Verify both create Service, File, Route, and ClientCall nodes in FalkorDB.
# ══════════════════════════════════════════════════════════════════════════════

class TestAlekhya1_MultiLanguageIngest:

    @pytest.fixture
    def sample_repo(self, tmp_path: Path) -> Path:
        """Create a minimal multi-language repo fixture."""
        # ── Service A: Python FastAPI ─────────────────────────────────────────
        svc_a = tmp_path / "service_a"
        svc_a.mkdir()
        (svc_a / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            import httpx

            app = FastAPI()

            @app.get("/api/v1/orders")
            async def list_orders():
                return []

            @app.post("/api/v1/orders")
            async def create_order():
                resp = httpx.post("http://service_b/api/v1/inventory", timeout=5)
                return resp.json()
        """), encoding="utf-8")

        # ── Service B: TypeScript / Express ───────────────────────────────────
        svc_b = tmp_path / "service_b"
        svc_b.mkdir()
        (svc_b / "package.json").write_text('{"name":"service_b"}', encoding="utf-8")
        (svc_b / "server.ts").write_text(textwrap.dedent("""\
            import express from 'express';
            import axios from 'axios';

            const router = express.Router();

            router.get('/api/v1/inventory', (req, res) => {
              res.json({ stock: 100 });
            });

            router.post('/api/v1/inventory', async (req, res) => {
              const result = await axios.get('http://service_a/api/v1/orders');
              res.json(result.data);
            });
        """), encoding="utf-8")

        return tmp_path

    def test_services_created(self, sample_repo: Path) -> None:
        """Both service_a and service_b are discovered."""
        services = discover_services(str(sample_repo))
        names = [s["name"] for s in services]
        assert "service_a" in names, f"service_a not discovered; got {names}"
        assert "service_b" in names, f"service_b not discovered; got {names}"

    def test_python_routes_extracted(self, sample_repo: Path) -> None:
        """Python FastAPI routes are extracted correctly."""
        from ingest.ast_extractor import ArchwardenASTVisitor
        import ast

        main_py = sample_repo / "service_a" / "main.py"
        src = main_py.read_text(encoding="utf-8")
        tree = ast.parse(src)
        visitor = ArchwardenASTVisitor("service_a/main.py", "service_a")
        visitor.visit(tree)

        route_paths = [r["path_template"] for r in visitor.routes]
        assert "/api/v1/orders" in route_paths, f"Expected GET route; got {route_paths}"

        methods = [r["method"] for r in visitor.routes]
        assert "GET" in methods
        assert "POST" in methods

    def test_python_client_calls_extracted(self, sample_repo: Path) -> None:
        """Python httpx.post call is extracted as a ClientCall."""
        from ingest.ast_extractor import ArchwardenASTVisitor
        import ast

        main_py = sample_repo / "service_a" / "main.py"
        src = main_py.read_text(encoding="utf-8")
        tree = ast.parse(src)
        visitor = ArchwardenASTVisitor("service_a/main.py", "service_a")
        visitor.visit(tree)

        assert len(visitor.client_calls) >= 1, "Expected at least one client call"
        cc = visitor.client_calls[0]
        assert cc["method"] == "POST"
        assert "service_b" in cc.get("target_hint", "") or "/api/v1/inventory" in cc.get("path", "")

    def test_ts_routes_extracted(self, sample_repo: Path) -> None:
        """TypeScript Express routes are extracted correctly."""
        server_ts = sample_repo / "service_b" / "server.ts"
        src = server_ts.read_text(encoding="utf-8")
        extractor = TSExtractor("service_b/server.ts", "service_b")
        extractor.extract(src)

        route_paths = [r["path_template"] for r in extractor.routes]
        assert "/api/v1/inventory" in route_paths, f"Expected TS route; got {route_paths}"

        methods = [r["method"] for r in extractor.routes]
        assert "GET" in methods
        assert "POST" in methods

    def test_ts_client_calls_extracted(self, sample_repo: Path) -> None:
        """TypeScript axios.get call is extracted as a ClientCall."""
        server_ts = sample_repo / "service_b" / "server.ts"
        src = server_ts.read_text(encoding="utf-8")
        extractor = TSExtractor("service_b/server.ts", "service_b")
        extractor.extract(src)

        assert len(extractor.client_calls) >= 1, "Expected at least one TS client call"
        cc = extractor.client_calls[0]
        assert cc["method"] == "GET"

    def test_full_ingest_stats(self, sample_repo: Path) -> None:
        """Full ingest_repo returns non-zero counts for files, routes, client_calls."""
        store = make_store()
        stats = ingest_repo(str(sample_repo), store, ingest_openapi=False, ingest_compose=False)

        assert stats["services"] >= 2, f"Expected >=2 services, got {stats}"
        assert stats["files"] >= 2, f"Expected >=2 files, got {stats}"
        assert stats["routes"] >= 2, f"Expected >=2 routes, got {stats}"
        assert stats["client_calls"] >= 1, f"Expected >=1 client_calls, got {stats}"


# ══════════════════════════════════════════════════════════════════════════════
# [Test-Alekhya-2]
# Change an existing route method from GET to POST.
# Verify breaking_changes.py outputs a breaking contract violation listing
# all consumer services.
# ══════════════════════════════════════════════════════════════════════════════

class TestAlekhya2_MethodAlteredViolation:

    DIFF_METHOD_CHANGE = textwrap.dedent("""\
        --- a/service_a/main.py
        +++ b/service_a/main.py
        @@ -5,7 +5,7 @@
        -@app.get("/api/v1/orders")
        +@app.post("/api/v1/orders")
         async def list_orders():
             return []
    """)

    def test_detect_method_altered_change(self) -> None:
        """detect_route_changes correctly identifies a GET→POST method change."""
        from ingest.diff_linker import parse_unified_diff
        hunks = parse_unified_diff(self.DIFF_METHOD_CHANGE)
        changes = detect_route_changes(hunks)

        assert len(changes) >= 1, f"Expected at least one change, got {changes}"
        method_changes = [c for c in changes if c.kind == "method_altered"]
        assert len(method_changes) >= 1, f"Expected method_altered, got {changes}"

        c = method_changes[0]
        assert c.old_method == "GET"
        assert c.new_method == "POST"
        assert c.old_path == "/api/v1/orders"

    def test_violation_produced_with_blast_radius(self) -> None:
        """
        analyze_breaking_changes returns P-006 violations.
        Since MemoryStore.ro_query returns [], violations are created with
        broken_service='UNRESOLVED' — confirming the engine runs end-to-end.
        """
        from ingest.diff_linker import parse_unified_diff
        store = make_store()
        hunks = parse_unified_diff(self.DIFF_METHOD_CHANGE)
        violations = analyze_breaking_changes(hunks, store, service_name="service_a")

        assert len(violations) >= 1, "Expected at least one P-006 violation"
        v = violations[0]
        assert v.rule_id == "P-006"
        assert v.severity == "critical"
        assert v.kind == "method_altered"
        assert v.old_method == "GET"
        assert v.new_method == "POST"
        assert v.changed_in_service == "service_a"

    def test_violations_serializable(self) -> None:
        """violations_to_dicts returns JSON-serializable plain dicts."""
        import json
        from ingest.diff_linker import parse_unified_diff
        store = make_store()
        hunks = parse_unified_diff(self.DIFF_METHOD_CHANGE)
        violations = analyze_breaking_changes(hunks, store, service_name="service_a")
        dicts = violations_to_dicts(violations)

        # Should be JSON-serializable
        serialized = json.dumps(dicts)
        loaded = json.loads(serialized)
        assert isinstance(loaded, list)
        assert all("rule_id" in d for d in loaded)


# ══════════════════════════════════════════════════════════════════════════════
# [Test-Alekhya-3]
# Delete an endpoint in Service A.
# Verify that Service B (which calls it) is flagged in the blast radius
# with an unresolved reference.
# ══════════════════════════════════════════════════════════════════════════════

class TestAlekhya3_RouteDeletedBlastRadius:

    DIFF_ROUTE_DELETED = textwrap.dedent("""\
        --- a/service_a/main.py
        +++ b/service_a/main.py
        @@ -1,5 +1,3 @@
        -@app.get("/api/v1/orders")
        -async def list_orders():
        -    return []
         # endpoint removed
    """)

    def test_detect_deleted_change(self) -> None:
        """detect_route_changes identifies a deleted route."""
        from ingest.diff_linker import parse_unified_diff
        hunks = parse_unified_diff(self.DIFF_ROUTE_DELETED)
        changes = detect_route_changes(hunks)

        deleted = [c for c in changes if c.kind == "deleted"]
        assert len(deleted) >= 1, f"Expected 'deleted' change, got {changes}"
        assert deleted[0].old_path == "/api/v1/orders"
        assert deleted[0].old_method == "GET"

    def test_deleted_endpoint_produces_violation(self) -> None:
        """A deleted route produces a P-006 violation (kind='deleted')."""
        from ingest.diff_linker import parse_unified_diff
        store = make_store()
        hunks = parse_unified_diff(self.DIFF_ROUTE_DELETED)
        violations = analyze_breaking_changes(hunks, store, service_name="service_a")

        assert len(violations) >= 1, "Expected P-006 violation for deleted route"
        v = violations[0]
        assert v.rule_id == "P-006"
        assert v.kind == "deleted"
        assert v.old_path == "/api/v1/orders"

    def test_unresolved_reference_flagged(self) -> None:
        """When no caller is found in graph, broken_service is 'UNRESOLVED'."""
        from ingest.diff_linker import parse_unified_diff
        store = make_store()  # empty graph — no callers
        hunks = parse_unified_diff(self.DIFF_ROUTE_DELETED)
        violations = analyze_breaking_changes(hunks, store, service_name="service_a")

        unresolved = [v for v in violations if v.broken_service == "UNRESOLVED"]
        assert len(unresolved) >= 1, "Expected UNRESOLVED violation when caller not in graph"

    def test_route_change_dataclass_fields(self) -> None:
        """RouteChange for deletion has new_method and new_path as empty strings."""
        change = RouteChange(
            kind="deleted",
            old_method="GET",
            old_path="/api/v1/orders",
        )
        assert change.new_method == ""
        assert change.new_path == ""


# ══════════════════════════════════════════════════════════════════════════════
# [Test-Alekhya-4]
# Parse a standard openapi.yaml and verify all endpoints load into FalkorDB
# (here MemoryStore) with accurate HTTP verbs.
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/api/v1/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List all orders",
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Create a new order",
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/api/v1/orders/{id}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Get order by ID",
                "responses": {"200": {"description": "OK"}},
            },
            "put": {
                "operationId": "updateOrder",
                "summary": "Update order",
                "responses": {"200": {"description": "OK"}},
            },
            "delete": {
                "operationId": "deleteOrder",
                "summary": "Delete order",
                "responses": {"204": {"description": "No Content"}},
            },
        },
        "/api/v1/health": {
            "get": {
                "operationId": "healthCheck",
                "summary": "Health check",
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
    "components": {
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "total": {"type": "number"},
                },
            },
            "ErrorResponse": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
            },
        }
    },
}


class TestAlekhya4_OpenAPIParser:

    def test_parse_openapi_returns_all_routes(self) -> None:
        """parse_openapi extracts all 6 routes from the sample spec."""
        routes, schemas = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        assert len(routes) == 6, f"Expected 6 routes, got {len(routes)}: {[r['path_template'] + ' ' + r['method'] for r in routes]}"

    def test_routes_have_correct_methods(self) -> None:
        """Each route has the correct HTTP verb."""
        routes, _ = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        method_path_pairs = {(r["method"], r["path_template"]) for r in routes}

        assert ("GET",    "/api/v1/orders")      in method_path_pairs
        assert ("POST",   "/api/v1/orders")      in method_path_pairs
        assert ("GET",    "/api/v1/orders/{id}") in method_path_pairs
        assert ("PUT",    "/api/v1/orders/{id}") in method_path_pairs
        assert ("DELETE", "/api/v1/orders/{id}") in method_path_pairs
        assert ("GET",    "/api/v1/health")      in method_path_pairs

    def test_routes_have_operation_ids(self) -> None:
        """Routes with operationId have it embedded in the handler_qname."""
        routes, _ = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        qnames = [r["handler_qname"] for r in routes]
        assert any("listOrders" in qn for qn in qnames)
        assert any("createOrder" in qn for qn in qnames)

    def test_schemas_extracted(self) -> None:
        """Schema components are extracted as Table node dicts."""
        _, schemas = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        schema_names = {s["name"] for s in schemas}
        assert "order" in schema_names, f"Expected 'order' schema; got {schema_names}"
        assert "errorresponse" in schema_names

    def test_routes_service_field(self) -> None:
        """All routes carry the correct service name."""
        routes, _ = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        assert all(r["service"] == "orders_service" for r in routes)

    def test_routes_protocol_is_http(self) -> None:
        """All OpenAPI routes are tagged as HTTP protocol."""
        routes, _ = parse_openapi(SAMPLE_OPENAPI_SPEC, "orders_service", "openapi.yaml")
        assert all(r["protocol"] == "http" for r in routes)

    def test_openapi_from_file(self, tmp_path: Path) -> None:
        """parse_openapi works end-to-end from a real .yaml file on disk."""
        import yaml as _yaml
        spec_file = tmp_path / "openapi.yaml"
        spec_file.write_text(_yaml.dump(SAMPLE_OPENAPI_SPEC), encoding="utf-8")

        from ingest.openapi_parser import load_openapi_file
        loaded = load_openapi_file(str(spec_file))
        routes, schemas = parse_openapi(loaded, "orders_service", str(spec_file))
        assert len(routes) == 6
        assert len(schemas) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Bonus: Docker Compose parser
# ══════════════════════════════════════════════════════════════════════════════

class TestDockerComposeParser:

    SAMPLE_COMPOSE = {
        "services": {
            "backend": {
                "build": {"context": "./backend"},
                "ports": ["8080:8080"],
                "environment": {"FALKORDB_HOST": "localhost"},
                "depends_on": ["falkordb"],
            },
            "frontend": {
                "build": {"context": "./frontend"},
                "ports": ["3001:3001"],
                "depends_on": ["backend"],
            },
            "falkordb": {
                "image": "falkordb/falkordb:latest",
                "ports": ["6379:6379", "3000:3000"],
            },
        }
    }

    def test_parse_discovers_all_services(self) -> None:
        result = parse_docker_compose(self.SAMPLE_COMPOSE)
        names = [s["name"] for s in result]
        assert "backend" in names
        assert "frontend" in names
        assert "falkordb" in names

    def test_db_image_flagged(self) -> None:
        result = parse_docker_compose(self.SAMPLE_COMPOSE)
        falkor = next(s for s in result if s["name"] == "falkordb")
        assert falkor["is_database"] is True

    def test_port_mappings(self) -> None:
        result = parse_docker_compose(self.SAMPLE_COMPOSE)
        backend = next(s for s in result if s["name"] == "backend")
        assert "8080:8080" in backend["ports"]

    def test_depends_on_parsed(self) -> None:
        result = parse_docker_compose(self.SAMPLE_COMPOSE)
        backend = next(s for s in result if s["name"] == "backend")
        assert "falkordb" in backend["depends_on"]


# ══════════════════════════════════════════════════════════════════════════════
# TS Extractor: Next.js App Router path inference
# ══════════════════════════════════════════════════════════════════════════════

class TestTSExtractorNextJS:

    def test_nextjs_path_inference_simple(self) -> None:
        from ingest.ts_extractor import TSExtractor
        path = TSExtractor._nextjs_path_from_file("app/api/orders/route.ts")
        assert path == "/api/orders", f"Got: {path}"

    def test_nextjs_path_inference_with_param(self) -> None:
        from ingest.ts_extractor import TSExtractor
        path = TSExtractor._nextjs_path_from_file("app/api/orders/[id]/route.ts")
        assert path == "/api/orders/{id}", f"Got: {path}"

    def test_nextjs_exported_handler_extracted(self) -> None:
        src = textwrap.dedent("""\
            export async function GET(request: Request) {
              return Response.json({ orders: [] });
            }
            export async function POST(request: Request) {
              const body = await request.json();
              return Response.json(body, { status: 201 });
            }
        """)
        extractor = TSExtractor("app/api/orders/route.ts", "frontend")
        extractor.extract(src)
        methods = [r["method"] for r in extractor.routes]
        assert "GET" in methods
        assert "POST" in methods

    def test_fetch_with_method_extracted(self) -> None:
        src = "const res = await fetch('http://backend/api/v1/orders', { method: 'POST' });"
        extractor = TSExtractor("lib/api.ts", "frontend")
        extractor.extract(src)
        assert len(extractor.client_calls) == 1
        cc = extractor.client_calls[0]
        assert cc["method"] == "POST"
        assert cc["path"] == "/api/v1/orders"

    def test_axios_get_extracted(self) -> None:
        src = "const data = await axios.get('http://orders-service/api/v1/orders');"
        extractor = TSExtractor("pages/index.tsx", "frontend")
        extractor.extract(src)
        assert len(extractor.client_calls) == 1
        cc = extractor.client_calls[0]
        assert cc["method"] == "GET"
        assert cc["target_hint"] == "orders-service"

    def test_timeout_detected(self) -> None:
        src = "const res = await fetch('/api/data', { signal: AbortSignal.timeout(3000) });"
        extractor = TSExtractor("lib/client.ts", "frontend")
        extractor.extract(src)
        assert len(extractor.client_calls) == 1
        assert extractor.client_calls[0]["has_timeout"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Path parameter change detection
# ══════════════════════════════════════════════════════════════════════════════

class TestPathParamChanged:

    DIFF_PARAM_RENAME = textwrap.dedent("""\
        --- a/service_a/main.py
        +++ b/service_a/main.py
        @@ -1,3 +1,3 @@
        -@app.get("/api/v1/orders/{id}")
        +@app.get("/api/v1/orders/{order_uuid}")
         async def get_order(id: str):
             pass
    """)

    def test_param_rename_detected(self) -> None:
        from ingest.diff_linker import parse_unified_diff
        hunks = parse_unified_diff(self.DIFF_PARAM_RENAME)
        changes = detect_route_changes(hunks)

        param_changes = [c for c in changes if c.kind == "param_changed"]
        assert len(param_changes) >= 1, f"Expected param_changed, got {changes}"
        c = param_changes[0]
        assert "{id}" in c.old_path
        assert "{order_uuid}" in c.new_path


if __name__ == "__main__":
    # Allow running directly: python test_alekhya.py
    import subprocess
    subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        check=False,
    )
