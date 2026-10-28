
"""Generate safe, reviewable remediation patches using NVIDIA Nemotron."""

import json
import re

from llm.nemotron import get_client


SYSTEM_PROMPT = """
You are an expert Python software remediation assistant for Archwarden.

Return ONLY a valid JSON object with exactly these string fields:
{
  "patch": "unified diff patch",
  "explanation": "short explanation of the fix"
}

Rules:
- Generate a unified diff, not the entire replacement file.
- Use the supplied file path in the diff headers.
- Preserve unrelated code and existing behavior.
- P-001: replace direct cross-service database access with an API call
  to the owning service.
- P-004: recommend a transactional outbox for database writes and
  event publication.
- P-005: add an explicit timeout, such as timeout=5.0, to the
  relevant outbound HTTP/gRPC client call.
- Never claim that a patch has been applied or verified.
- If the snippet lacks enough context for a safe patch, return an
  empty patch and explain what additional context is required.
- Do not include Markdown fences around the JSON.
"""


def generate_patch(
    violation_id: str,
    principle_statement: str,
    file_path: str,
    code_snippet: str,
    fix_hint: str,
) -> dict[str, str]:
    """Ask Nemotron for a unified diff and an explanation."""

    client = get_client()

    if not client.available:
        raise RuntimeError(
            "Nemotron is unavailable. Check NVIDIA_API_KEY configuration."
        )

    user_prompt = f"""
Violation ID: {violation_id}
Architecture principle: {principle_statement}
File path: {file_path}
Suggested fix: {fix_hint}

Code snippet:
```python
{code_snippet}
```

Produce a minimal, relevant unified diff and explain the change.
"""

    response = client.super_(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=2048,
        temperature=0.1,
    )

    if not response or response.startswith("[LLM"):
        raise RuntimeError(f"Nemotron request failed: {response}")

    # Be tolerant of JSON wrapped in accidental Markdown fences.
    cleaned = response.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise RuntimeError("Nemotron returned invalid JSON.")
        try:
            result = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Nemotron returned invalid JSON.") from exc

    patch = result.get("patch")
    explanation = result.get("explanation")

    if not isinstance(patch, str) or not isinstance(explanation, str):
        raise RuntimeError(
            "Nemotron response must contain string fields "
            "'patch' and 'explanation'."
        )

    return {
        "patch": patch,
        "explanation": explanation,
    }
