"""Archives from other tools, read in place: nothing is copied or rewritten, so the data exists once.

An import is a folder <target>/imports/<name>/ with a source.yaml:

    format: speaker-mining-v3          # reader to use (see READERS)
    files: ["chunks/*.jsonl"]           # glob patterns relative to the folder, read in sorted order
    description: "..."                  # where the archive comes from, for people
    origin: "..."                       # original location before it was moved here

Files of an import are treated as read-only. Records from imports carry scope "import-full" or "import-basic" and
the revision ID only if the archived answer contained one.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import store as _store


@dataclass
class Source:
    folder: Path
    format: str
    patterns: list[str]
    description: str = ""
    origin: str = ""
    extra: dict = field(default_factory=dict)

    def files(self) -> list[Path]:
        found = set()
        for pattern in self.patterns:
            found.update(p for p in self.folder.glob(pattern) if p.is_file())
        return sorted(found)

    def records(self, path: Path):
        """(byte offset of the archived event, normalised record) for every entity in the file."""
        reader = READERS.get(self.format)
        if reader is None:
            raise ValueError(f"Unknown import format {self.format!r} in {self.folder}")
        return reader(path)


def find(imports_dir: Path) -> list[Source]:
    sources = []
    if not imports_dir.exists():
        return sources
    for config in sorted(imports_dir.glob("*/source.yaml")):
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        patterns = data.pop("files", None)
        fmt = data.pop("format", None)
        if not fmt or not patterns:
            raise ValueError(f"{config}: 'format' and 'files' are required")
        sources.append(Source(config.parent, fmt, list(patterns), str(data.pop("description", "")),
                              str(data.pop("origin", "")), data))
    return sources


# ── speaker-mining event store, version 3 ─────────────────────────────────────
# One JSON event per line. Wikidata answers are events of type "query_response" whose payload has
# endpoint "wikidata_api" and the wbgetentities answer in payload.response_data.entities. speaker-mining added
# a field of its own to some documents (_fetched_literal_languages_property); documents are returned as archived.

def _payload(event: dict) -> dict:
    payload = event.get("payload") or {}
    if isinstance(payload, str):  # some versions stored the payload as a Python literal
        try:
            payload = ast.literal_eval(payload)
        except (ValueError, SyntaxError):
            return {}
    return payload if isinstance(payload, dict) else {}


def _response_entities(payload: dict) -> dict:
    data = payload.get("response_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(data)
            except (ValueError, SyntaxError):
                return {}
    entities = data.get("entities") if isinstance(data, dict) else None
    return entities if isinstance(entities, dict) else {}


def _scope(entity: dict) -> str:
    """By content, not by the request: speaker-mining's property_fetch events carry 'property:P…' instead of a URL."""
    return "import-full" if {"labels", "descriptions", "aliases", "claims"} <= set(entity) else "import-basic"


def read_speaker_mining_v3(path: Path):
    for offset, event in _store.iter_events_with_offsets(path):
        if event.get("event_type") != "query_response":
            continue
        payload = _payload(event)
        if payload.get("endpoint") != "wikidata_api":
            continue
        for entity_id, entity in _response_entities(payload).items():
            if not isinstance(entity, dict) or "missing" in entity:
                continue
            yield offset, {"type": "entity_revision", "id": entity_id, "revision": entity.get("lastrevid"),
                           "time": event.get("timestamp_utc") or event.get("recorded_at") or "",
                           "scope": _scope(entity)}


def entity_from_record(event: dict, entity_id: str) -> dict:
    """The entity document inside an archived event (speaker-mining-v3)."""
    return _response_entities(_payload(event))[entity_id]


READERS = {"speaker-mining-v3": read_speaker_mining_v3}
