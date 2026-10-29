"""
Archwarden — OpenAPI & Docker Compose Parser
Parses:
  - openapi.yaml / openapi.json → auto-register all documented routes and schemas
  - docker-compose.yml         → discover services, port mappings, DB ownership

The results are upserted into FalkorDB via the GraphStore protocol.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml  # pyyaml, already in requirements.txt

from graph.store_protocol import GraphStore


# ── OpenAPI parser ────────────────────────────────────────────────────────────

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}

# DB image fingerprints for OWNS_TABLE heuristic
_DB_IMAGE_PATTERNS = [
    re.compile(r"postgres|pg|postgresql", re.IGNORECASE),
    re.compile(r"mysql|mariadb", re.IGNORECASE),
    re.compile(r"mongo", re.IGNORECASE),
    re.compile(r"redis", re.IGNORECASE),
    re.compile(r"falkordb", re.IGNORECASE),
    re.compile(r"elasticsearch|opensearch", re.IGNORECASE),
    re.compile(r"cassandra", re.IGNORECASE),
]


def _is_db_image(image: str) -> bool:
    return any(p.search(image) for p in _DB_IMAGE_PATTERNS)


def parse_openapi(
    spec: dict[str, Any],
    service_name: str,
    file_path: str = "openapi.yaml",
) -> tuple[list[dict], list[dict]]:
    """
    Parse an OpenAPI 3.x or Swagger 2.x spec dict.

    Returns:
        (routes, schemas) where:
          routes  — list of Route node dicts
          schemas — list of Table node dicts (one per schema component)
    """
    routes: list[dict] = []
    schemas: list[dict] = []

    paths: dict = spec.get("paths", {})

    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            operation_id = operation.get("operationId", "")
            summary = operation.get("summary", "")
            handler_qname = (
                f"{service_name}::{operation_id}"
                if operation_id
                else f"{service_name}::openapi_{method.upper()}_{path_template.replace('/', '_').strip('_')}"
            )

            routes.append({
                "method": method.upper(),
                "path_template": path_template,
                "protocol": "http",
                "service": service_name,
                "file": file_path,
                "line": 0,           # OpenAPI specs have no line numbers
                "handler_qname": handler_qname,
                "operation_id": operation_id,
                "summary": summary,
            })

    # Schemas → Table nodes (OpenAPI 3.x: components/schemas; Swagger 2.x: definitions)
    schema_container = (
        spec.get("components", {}).get("schemas", {})
        or spec.get("definitions", {})
    )
    for schema_name in schema_container:
        schemas.append({
            "name": schema_name.lower(),
            "store": "openapi_schema",
            "service": service_name,
            "file": file_path,
        })

    return routes, schemas


def load_openapi_file(file_path: str) -> dict[str, Any]:
    """Load an OpenAPI spec from a .yaml/.json file."""
    p = Path(file_path)
    with open(p, "r", encoding="utf-8") as fh:
        if p.suffix in (".yaml", ".yml"):
            return yaml.safe_load(fh) or {}
        return json.load(fh)


# ── Docker Compose parser ─────────────────────────────────────────────────────


def parse_docker_compose(compose: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Parse a docker-compose.yml dict into a list of service descriptors.

    Each descriptor has:
      name:         str
      image:        str | None
      ports:        list[str]           # ["8080:80", ...]
      depends_on:   list[str]           # other service names
      environment:  dict[str, str]
      is_database:  bool
      tables_owned: list[str]           # inferred from image name, empty by default
    """
    raw_services: dict = compose.get("services", {})
    result: list[dict[str, Any]] = []

    for svc_name, svc_cfg in raw_services.items():
        if not isinstance(svc_cfg, dict):
            continue

        image: str = svc_cfg.get("image", "") or ""
        build = svc_cfg.get("build", None)

        # Port mappings
        ports_raw = svc_cfg.get("ports", [])
        ports: list[str] = []
        for p in ports_raw:
            ports.append(str(p))

        # depends_on can be a list or a dict (long syntax)
        dep_raw = svc_cfg.get("depends_on", [])
        depends_on: list[str] = (
            list(dep_raw.keys()) if isinstance(dep_raw, dict) else list(dep_raw)
        )

        # Environment (list ["KEY=VAL"] or dict)
        env_raw = svc_cfg.get("environment", {})
        environment: dict[str, str] = {}
        if isinstance(env_raw, list):
            for item in env_raw:
                if "=" in item:
                    k, _, v = item.partition("=")
                    environment[k.strip()] = v.strip()
        elif isinstance(env_raw, dict):
            environment = {k: str(v) for k, v in env_raw.items()}

        is_db = _is_db_image(image)

        result.append({
            "name": svc_name,
            "image": image or None,
            "build": bool(build),
            "ports": ports,
            "depends_on": depends_on,
            "environment": environment,
            "is_database": is_db,
            "tables_owned": [],  # Populated by caller from migrations/config
        })

    return result


def load_compose_file(file_path: str) -> dict[str, Any]:
    """Load a docker-compose YAML file."""
    with open(file_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ── Graph upsert helpers ──────────────────────────────────────────────────────


def upsert_openapi_routes(
    store: GraphStore,
    routes: list[dict],
) -> int:
    """Upsert Route nodes (and stub handler Symbols) from OpenAPI spec. Returns count."""
    count = 0
    for route in routes:
        # Ensure a stub Symbol exists for the handler
        store.query(
            """
            MERGE (sym:Symbol {qname: $handler_qname})
            SET sym.kind = 'handler', sym.file = $file, sym.line = $line,
                sym.service = $service
            WITH sym
            MATCH (f:File {path: $file})
            FOREACH (_ IN CASE WHEN f IS NOT NULL THEN [1] ELSE [] END |
                MERGE (f)-[:CONTAINS]->(sym)
            )
            """,
            {
                "handler_qname": route["handler_qname"],
                "file": route["file"],
                "line": route["line"],
                "service": route["service"],
            },
        )
        # Upsert Route node
        store.query(
            """
            MERGE (r:Route {path_template: $path_template, service: $service})
            SET r.method = $method, r.protocol = $protocol,
                r.file = $file, r.line = $line
            WITH r
            MATCH (sym:Symbol {qname: $handler_qname})
            MERGE (sym)-[:DEFINES]->(r)
            """,
            route,
        )
        count += 1
    return count


def upsert_openapi_schemas(
    store: GraphStore,
    schemas: list[dict],
    service_name: str,
) -> int:
    """Upsert Table nodes for OpenAPI schema components. Returns count."""
    count = 0
    for schema in schemas:
        store.query(
            """
            MERGE (t:Table {name: $name})
            SET t.store = $store
            WITH t
            MATCH (s:Service {name: $service})
            MERGE (s)-[:OWNS_TABLE]->(t)
            """,
            {"name": schema["name"], "store": schema["store"], "service": service_name},
        )
        count += 1
    return count


def upsert_compose_services(
    store: GraphStore,
    compose_services: list[dict],
) -> dict[str, list[str]]:
    """
    Upsert Service nodes from docker-compose descriptors.
    Returns {service_name: [ports]} mapping for caller use.
    """
    port_map: dict[str, list[str]] = {}

    for svc in compose_services:
        language = "unknown"
        framework = "docker"
        if svc["build"]:
            # Heuristic: built services are application services
            language = "python"  # default; will be overridden during AST walk
        elif svc["is_database"]:
            language = "database"
            framework = "db"

        store.query(
            """
            MERGE (s:Service {name: $name})
            SET s.kind = 'service', s.language = $language, s.framework = $framework,
                s.image = $image
            """,
            {
                "name": svc["name"],
                "language": language,
                "framework": framework,
                "image": svc["image"] or "",
            },
        )

        # Create CALLS edges from depends_on
        for dep in svc["depends_on"]:
            store.query(
                """
                MATCH (a:Service {name: $caller}), (b:Service {name: $callee})
                MERGE (a)-[c:CALLS]->(b)
                ON CREATE SET c.via = 'compose_dep', c.count = 1
                ON MATCH SET c.count = c.count + 1
                """,
                {"caller": svc["name"], "callee": dep},
            )

        port_map[svc["name"]] = svc["ports"]

    return port_map


# ── Convenience: scan a repo for OpenAPI specs and parse them all ─────────────


def scan_and_ingest_openapi(
    repo_dir: str,
    store: GraphStore,
    service_name: str | None = None,
) -> dict[str, int]:
    """
    Walk repo_dir looking for openapi.yaml/json files, parse each one,
    and upsert routes + schemas into the graph.

    Returns stats: {routes, schemas}
    """
    stats = {"routes": 0, "schemas": 0}
    repo_path = Path(repo_dir).resolve()

    for spec_file in sorted(repo_path.rglob("openapi.ya?ml")) + sorted(repo_path.rglob("openapi.json")):
        # Skip node_modules / venv
        if any(p in spec_file.parts for p in ("node_modules", "venv", ".venv", "__pycache__", ".git")):
            continue

        svc = service_name or spec_file.parent.name
        rel_path = str(spec_file.relative_to(repo_path)).replace("\\", "/")

        try:
            spec = load_openapi_file(str(spec_file))
        except Exception:
            continue

        # Ensure service + file nodes exist
        store.query(
            "MERGE (s:Service {name: $name}) SET s.kind = 'service'",
            {"name": svc},
        )
        store.query(
            """
            MERGE (f:File {path: $path})
            SET f.service = $service
            WITH f
            MATCH (s:Service {name: $service})
            MERGE (s)-[:CONTAINS]->(f)
            """,
            {"path": rel_path, "service": svc},
        )

        routes, schemas = parse_openapi(spec, svc, rel_path)
        stats["routes"] += upsert_openapi_routes(store, routes)
        stats["schemas"] += upsert_openapi_schemas(store, schemas, svc)

    return stats


def scan_and_ingest_compose(
    repo_dir: str,
    store: GraphStore,
) -> dict[str, Any]:
    """
    Find docker-compose.yml in repo_dir and ingest services into the graph.
    Returns {services_found, port_map}.
    """
    repo_path = Path(repo_dir).resolve()
    compose_file = None

    for candidate in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        candidate_path = repo_path / candidate
        if candidate_path.exists():
            compose_file = candidate_path
            break

    if compose_file is None:
        return {"services_found": 0, "port_map": {}}

    try:
        compose = load_compose_file(str(compose_file))
    except Exception:
        return {"services_found": 0, "port_map": {}}

    compose_services = parse_docker_compose(compose)
    port_map = upsert_compose_services(store, compose_services)

    return {
        "services_found": len(compose_services),
        "port_map": port_map,
    }
