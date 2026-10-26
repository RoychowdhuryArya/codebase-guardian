"""
Archwarden — Nemotron Principle Miner
Uses Nemotron Super to draft new openCypher rules from natural language.
Validates drafts against the live graph before saving as candidates.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from graph.store_protocol import GraphStore
from llm.nemotron import get_client
from principles.loader import Principle, PrincipleCheck, save_candidate


_DRAFT_SYSTEM = """You are an expert in microservice architecture and FalkorDB openCypher graph queries.

The graph schema is:
- Nodes: Service(name, kind, path, language), File(path, service), Symbol(qname, kind, file, line, service), 
         Route(method, path_template, protocol, service, file, line), 
         ClientCall(target_hint, method, path, file, line, service, resolved, has_timeout),
         Table(name), Topic(name), ConfigKey(name)
- Edges: Service-[:CONTAINS*]->File->Symbol, Symbol-[:DEFINES]->Route, Symbol-[:MAKES_CALL]->ClientCall,
         ClientCall-[:RESOLVES_TO]->Route|Service, Service-[:CALLS]->Service (via, count),
         Symbol-[:ACCESSES]->Table (mode: read|write), Service-[:OWNS_TABLE]->Table,
         Symbol-[:PRODUCES|CONSUMES]->Topic, Symbol-[:READS_CONFIG]->ConfigKey

Write ONLY a valid FalkorDB openCypher query that detects violations of the rule.
The query must end with RETURN clauses that name meaningful fields (e.g. service, handler, file, line).
Use ro_query compatible syntax — no writes, no procedures except basic MATCH/WHERE/RETURN/WITH.
Output only the Cypher query, no explanation."""


_REPAIR_SYSTEM = """You are debugging a FalkorDB openCypher query that failed validation.
Fix the syntax or semantics error and output only the corrected Cypher query."""


def mine_principle(
    natural_language_rule: str,
    store: GraphStore,
    new_id: Optional[str] = None,
    fix_hint: str = "",
) -> Principle | None:
    """
    Given a natural language rule:
    1. Draft a Cypher query with Nemotron Super
    2. Validate it against the live graph (syntax check)
    3. On failure, attempt repair (up to 2 times)
    4. Save as candidate if valid
    Returns the Principle if successful, None on failure.
    """
    client = get_client()
    if not client.available:
        print("[Miner] NVIDIA_API_KEY not set — cannot mine principles")
        return None

    from config import settings

    # Generate a new ID
    if not new_id:
        from principles.loader import load_candidates, load_principles
        existing_ids = [p.id for p in load_principles() + load_candidates()]
        idx = max([int(re.sub(r"\D", "", i)) for i in existing_ids if re.sub(r"\D", "", i).isdigit()], default=0)
        new_id = f"P-{idx + 1:03d}"

    print(f"[Miner] Drafting Cypher for rule: {natural_language_rule!r}")

    # Step 1: Draft
    draft_query = client.super_(
        system=_DRAFT_SYSTEM,
        user=f"Rule: {natural_language_rule}",
        max_tokens=512,
        temperature=0.1,
    )
    draft_query = _extract_cypher(draft_query)

    # Step 2-3: Validate with up to 2 repair attempts
    last_error = ""
    for attempt in range(3):
        try:
            store.ro_query(draft_query)
            # Success — no exception
            break
        except Exception as e:
            last_error = str(e)
            print(f"[Miner] Attempt {attempt + 1} failed: {last_error}")
            if attempt < 2:
                repair_prompt = (
                    f"The following FalkorDB openCypher query has an error:\n\n"
                    f"```cypher\n{draft_query}\n```\n\n"
                    f"Error: {last_error}\n\n"
                    f"Rule intent: {natural_language_rule}"
                )
                draft_query = client.super_(
                    system=_REPAIR_SYSTEM,
                    user=repair_prompt,
                    max_tokens=512,
                    temperature=0.1,
                )
                draft_query = _extract_cypher(draft_query)
    else:
        print(f"[Miner] All repair attempts failed. Last error: {last_error}")
        return None

    # Step 4: Build and save candidate
    candidate = Principle(
        id=new_id,
        statement=natural_language_rule,
        kind="graph",
        severity="medium",
        scope="system",
        check=PrincipleCheck(language="cypher", query=draft_query),
        status="candidate",
        source="mined",
        fix_hint=fix_hint or "Review the violation and refactor accordingly.",
        evidence={"mined_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
    )
    save_candidate(candidate)
    print(f"[Miner] Saved candidate {new_id} to principles.candidates.yaml")
    return candidate


def _extract_cypher(llm_output: str) -> str:
    """Strip markdown fences and return raw Cypher."""
    # Try to extract from ```cypher ... ``` block
    m = re.search(r"```(?:cypher)?\s*([\s\S]+?)\s*```", llm_output, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return llm_output.strip()
