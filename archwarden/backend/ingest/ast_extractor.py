"""
Archwarden — Python AST Code Graph Extractor
Parses a multi-service repo into Service/File/Symbol/Route/ClientCall/Table nodes.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

# ── AST visitor ──────────────────────────────────────────────────────────────


class ArchwardenASTVisitor(ast.NodeVisitor):
    """
    Extracts from a single Python file:
      - Function/class definitions → Symbol nodes
      - FastAPI/Flask/aiohttp route decorators → Route nodes
      - httpx/requests/aiohttp call sites → ClientCall nodes
      - DB ORM model usage → Table ACCESSES edges
      - Kafka/Redis publish calls → Topic PRODUCES/CONSUMES edges
    """

    HTTP_CLIENTS = {"httpx", "requests", "aiohttp", "urllib", "urllib3"}
    DB_ORM_METHODS = {"query", "execute", "fetchone", "fetchall", "insert", "update", "delete", "bulk_create", "filter", "get", "create"}
    KAFKA_PRODUCE = {"send", "produce", "publish"}
    KAFKA_CONSUME = {"subscribe", "consume", "receive"}

    def __init__(self, file_path: str, service_name: str):
        self.file_path = file_path
        self.service_name = service_name
        self.symbols: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []
        self.client_calls: list[dict[str, Any]] = []
        self.table_accesses: list[dict[str, Any]] = []
        self.topic_produces: list[dict[str, Any]] = []
        self.topic_consumes: list[dict[str, Any]] = []
        self._scope_stack: list[str] = []

    def _qname(self, name: str) -> str:
        prefix = ".".join(self._scope_stack)
        return f"{self.service_name}::{prefix}.{name}" if prefix else f"{self.service_name}::{name}"

    def _current_qname(self) -> str | None:
        return f"{self.service_name}::{'.'.join(self._scope_stack)}" if self._scope_stack else None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append({
            "qname": self._qname(node.name),
            "kind": "class",
            "file": self.file_path,
            "line": node.lineno,
            "service": self.service_name,
        })
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qname = self._qname(node.name)
        kind = "handler" if self._is_handler(node) else "method"
        self.symbols.append({
            "qname": qname,
            "kind": kind,
            "file": self.file_path,
            "line": node.lineno,
            "service": self.service_name,
        })

        # Route decorators
        for dec in node.decorator_list:
            route = self._extract_route(dec)
            if route:
                self.routes.append({
                    **route,
                    "service": self.service_name,
                    "file": self.file_path,
                    "line": node.lineno,
                    "handler_qname": qname,
                })

        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_Call(self, node: ast.Call) -> None:
        caller = self._current_qname()
        if caller:
            # HTTP client call detection
            call_str = self._call_to_str(node)
            if call_str:
                for client in self.HTTP_CLIENTS:
                    if client in call_str:
                        target_hint, method, path = self._extract_http_call(node, call_str)
                        has_timeout = self._has_timeout_kwarg(node)
                        self.client_calls.append({
                            "caller_qname": caller,
                            "target_hint": target_hint or "unknown",
                            "method": method,
                            "path": path,
                            "file": self.file_path,
                            "line": node.lineno,
                            "service": self.service_name,
                            "resolved": False,
                            "resolution_source": "UNRESOLVED",
                            "has_timeout": has_timeout,
                        })
                        break

                # Table access detection (SQLAlchemy / Django ORM / raw execute)
                if isinstance(node.func, ast.Attribute) and node.func.attr in self.DB_ORM_METHODS:
                    table_name = self._guess_table_name(node)
                    if table_name:
                        mode = "write" if node.func.attr in ("insert", "update", "delete", "create", "bulk_create") else "read"
                        self.table_accesses.append({
                            "accessor_qname": caller,
                            "table": table_name,
                            "mode": mode,
                            "evidence": f"{self.file_path}:{node.lineno}",
                            "service": self.service_name,
                        })

                # Topic produce/consume detection
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.KAFKA_PRODUCE:
                        topic = self._guess_topic(node)
                        if topic:
                            self.topic_produces.append({
                                "producer_qname": caller,
                                "topic": topic,
                                "service": self.service_name,
                                "file": self.file_path,
                                "line": node.lineno,
                            })
                    elif node.func.attr in self.KAFKA_CONSUME:
                        topic = self._guess_topic(node)
                        if topic:
                            self.topic_consumes.append({
                                "consumer_qname": caller,
                                "topic": topic,
                                "service": self.service_name,
                                "file": self.file_path,
                                "line": node.lineno,
                            })
        self.generic_visit(node)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_handler(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for dec in node.decorator_list:
            s = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            if any(m in s for m in ("get", "post", "put", "delete", "patch", "route", "endpoint")):
                return True
        return False

    def _extract_route(self, dec: ast.expr) -> dict | None:
        methods = ("get", "post", "put", "delete", "patch", "options", "head", "route")
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr in methods:
                method = func.attr.upper()
                path_template = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    path_template = str(dec.args[0].value)
                return {"method": method, "path_template": path_template, "protocol": "http"}
        return None

    def _call_to_str(self, node: ast.Call) -> str:
        try:
            return ast.unparse(node) if hasattr(ast, "unparse") else ""
        except Exception:
            return ""

    def _extract_http_call(self, node: ast.Call, call_str: str) -> tuple[str, str, str]:
        method = "GET"
        for m in ("post", "put", "delete", "patch", "get"):
            if f".{m}(" in call_str.lower():
                method = m.upper()
                break
        path = ""
        target = ""
        if node.args and isinstance(node.args[0], ast.Constant):
            url = str(node.args[0].value)
            # Parse host as target_hint
            m = re.match(r"https?://([^/]+)(.*)", url)
            if m:
                target = m.group(1)
                path = m.group(2)
            else:
                path = url
        return target, method, path

    def _has_timeout_kwarg(self, node: ast.Call) -> bool:
        return any(kw.arg == "timeout" for kw in node.keywords)

    def _guess_table_name(self, node: ast.Call) -> str | None:
        # Try to get model name from the object being called on
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return node.func.value.id.lower()
        return None

    def _guess_topic(self, node: ast.Call) -> str | None:
        if node.args and isinstance(node.args[0], ast.Constant):
            return str(node.args[0].value)
        for kw in node.keywords:
            if kw.arg in ("topic", "channel") and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        return None
