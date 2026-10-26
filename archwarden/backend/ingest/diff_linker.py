"""
Archwarden — PR Diff Linker
Maps a unified diff (GitHub PR format) to affected service names.
"""
from __future__ import annotations
import re
from pathlib import Path


def parse_unified_diff(diff_text: str) -> list[dict]:
    """
    Parse a unified diff string into a list of file hunks.
    Returns [{file, added_lines, removed_lines}]
    """
    hunks = []
    current_file = None
    added = []
    removed = []

    for line in diff_text.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            m = re.match(r"[+-]{3} [ab]/(.+)", line)
            if m:
                if line.startswith("+++ ") and current_file:
                    pass
                elif line.startswith("--- "):
                    if current_file:
                        hunks.append({"file": current_file, "added": added, "removed": removed})
                    current_file = m.group(1)
                    added, removed = [], []
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])

    if current_file:
        hunks.append({"file": current_file, "added": added, "removed": removed})

    return hunks


def diff_to_services(diff_text: str, known_services: list[str]) -> list[str]:
    """
    Given a unified diff and known service names, return the set of
    service names touched by the diff.
    """
    hunks = parse_unified_diff(diff_text)
    touched = set()
    for hunk in hunks:
        file_path = Path(hunk["file"])
        parts = file_path.parts
        for svc in known_services:
            if svc in parts or (len(parts) > 0 and parts[0] == svc):
                touched.add(svc)
    return sorted(touched)
