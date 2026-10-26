"""
Archwarden — Principles Loader
Parses principles.yaml into typed dataclasses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


@dataclass
class PrincipleCheck:
    language: Literal["cypher", "python"]
    query: str


@dataclass
class Principle:
    id: str
    statement: str
    kind: Literal["graph", "fuzzy"]
    severity: Literal["high", "medium", "low"]
    scope: str
    check: PrincipleCheck
    status: Literal["candidate", "confirmed", "rejected"]
    source: Literal["mined", "adr", "manual"]
    fix_hint: str
    evidence: dict = field(default_factory=dict)


_PRINCIPLES_FILE = Path(__file__).parent / "principles.yaml"
_CANDIDATES_FILE = Path(__file__).parent / "principles.candidates.yaml"


def load_principles(path: Path | None = None) -> list[Principle]:
    """Load confirmed principles from YAML."""
    p = path or _PRINCIPLES_FILE
    if not _YAML_OK:
        raise ImportError("Install PyYAML: pip install pyyaml")
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    principles = []
    for item in raw:
        check = item.get("check", {})
        principles.append(Principle(
            id=item["id"],
            statement=item["statement"],
            kind=item.get("kind", "graph"),
            severity=item.get("severity", "medium"),
            scope=item.get("scope", "system"),
            check=PrincipleCheck(
                language=check.get("language", "cypher"),
                query=check.get("query", ""),
            ),
            status=item.get("status", "candidate"),
            source=item.get("source", "manual"),
            fix_hint=item.get("fix_hint", ""),
            evidence=item.get("evidence", {}),
        ))
    return principles


def load_candidates() -> list[Principle]:
    """Load candidate principles (not yet confirmed by a human)."""
    if not _CANDIDATES_FILE.exists():
        return []
    return load_principles(_CANDIDATES_FILE)


def save_candidate(principle: Principle) -> None:
    """Append a candidate principle to the candidates file."""
    if not _YAML_OK:
        return
    existing = load_candidates()
    existing.append(principle)
    raw = [
        {
            "id": p.id,
            "statement": p.statement,
            "kind": p.kind,
            "severity": p.severity,
            "scope": p.scope,
            "check": {"language": p.check.language, "query": p.check.query},
            "status": p.status,
            "source": p.source,
            "fix_hint": p.fix_hint,
            "evidence": p.evidence,
        }
        for p in existing
    ]
    with open(_CANDIDATES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)
