"""Scan stored data for leaked credentials: the secrets themselves and echoed request headers. Reports file names
and counts only, never the matching text."""
from __future__ import annotations

from pathlib import Path

from .store import LEAK_MARKERS


def scan(root: Path, secrets: list[str] = ()) -> dict[str, dict[str, int]]:
    """{file: {marker: count}} for every file below root that contains a marker; empty means clean."""
    markers = {marker.strip(): marker.encode() for marker in LEAK_MARKERS}
    for number, secret in enumerate(s for s in secrets if s):
        markers[f"secret{number + 1}"] = secret.encode()
    findings: dict[str, dict[str, int]] = {}
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        data = path.read_bytes()
        hits = {name: data.count(needle) for name, needle in markers.items() if needle in data}
        if hits:
            findings[str(path.relative_to(root))] = hits
    return findings
