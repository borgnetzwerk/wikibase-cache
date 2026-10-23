"""Local storage of one target: an append-only event log, imported archives read in place, and an index derived
from both.

The layout is safe for a data root that a file sync service (Nextcloud, Syncthing, ...) shares between machines:
no file is ever changed by two machines, and no file is changed after it is complete.

Layout below <data_root>/<target>/:
    events/<date>_<machine>_<NNNN>.jsonl           one file per run, written once, never changed afterwards
    events/<date>_<machine>_<NNNN>.jsonl.partial   the file of a run in progress; only its machine writes it,
                                                   other machines ignore it until it is renamed
    imports/<name>/source.yaml                     an archive from another tool, read in place, never changed;
                                                   source.yaml names its format and files (see imports.py)
    index/<machine>.json                           this machine's index, derived from all of the above
    STOP                                           a non-empty file here ends a running sync after the current batch

Event files of other machines are picked up on the next open: whatever is not yet in this machine's index is
read and added. If two machines fetched the same revision, the duplicate counts once.

Events (one JSON object per line, each with time (UTC, ISO 8601), type and run):
    run_started      {mode, ...}
    entity_revision  {id, revision, scope, entity[, languages]}
                     scope "full": the entity document exactly as the server sent it (all parts);
                     scope "basic": labels, descriptions and aliases in the listed languages, and of the claims
                     only P31 and P279 (the rest of the server's answer is not kept)
    entity_missing   {id}                       the server reported the ID as missing
    entity_unlisted  {id}                       the ID no longer appears in the listing (deleted or moved)
    sparql_response  {endpoint, query, query_hash, response, sha256}
    run_finished     {requests, fetched, complete, reason}
Imported records have scope "import-full" (all claims, labels, descriptions, aliases in the archived languages)
or "import-basic" (fewer parts), and may lack a revision ID.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import imports

# Text that must never reach the disk (some instances echo request headers in debuginfo)
LEAK_MARKERS = ("Bearer ", "debuginfo", "Authorization:")
PARTIAL = ".partial"
INDEX_VERSION = 2
FULL_SCOPES = ("full", "import-full")


class LeakError(Exception):
    """An event would have written a secret or an echoed request header; nothing of that event was written."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_clean(line: str, secrets: list[str] = ()) -> None:
    found = [marker.strip() for marker in LEAK_MARKERS if marker in line]
    if any(secret and secret in line for secret in secrets):
        found.append("secret")
    if found:
        raise LeakError(f"Refusing to write: event contains {', '.join(found)}.")


def iter_events_with_offsets(path: Path):
    """(byte offset, event) for every complete event; a truncated last line (crash during writing) is skipped."""
    with path.open("rb") as f:
        offset = 0
        for raw in f:
            start, offset = offset, offset + len(raw)
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(event, dict):
                yield start, event


def read_event_at(path: Path, offset: int) -> dict:
    with path.open("rb") as f:
        f.seek(offset)
        return json.loads(f.readline())


def query_hash(endpoint: str, query: str) -> str:
    """Key of a SPARQL query: endpoint plus query text with line ends normalised and outer whitespace removed."""
    text = "\n".join(line.rstrip() for line in query.strip().splitlines())
    return hashlib.sha256(f"{endpoint}\n{text}".encode()).hexdigest()


def newer(a: dict, b: dict | None) -> bool:
    """Is version a newer than version b? By revision where both have one, otherwise by time. For the same
    revision, a full version replaces a reduced one (basic or imported basic)."""
    if b is None:
        return True
    if a.get("revision") is not None and b.get("revision") is not None:
        if a["revision"] == b["revision"]:
            return a.get("scope") in FULL_SCOPES and b.get("scope") not in FULL_SCOPES
        return a["revision"] > b["revision"]
    return a.get("time", "") > b.get("time", "")


class Store:
    def __init__(self, root: Path, machine_id: str, secrets: list[str] = (), log=print) -> None:
        self.root = Path(root)
        self.machine_id = machine_id
        self.events_dir = self.root / "events"
        self.imports_dir = self.root / "imports"
        self.index_path = self.root / "index" / f"{machine_id}.json"
        self.secrets = list(secrets)
        self.log = log
        self._index: dict | None = None
        self._file: Path | None = None
        self._handle = None
        self._offset = 0
        self._run = ""

    # ── Reading ────────────────────────────────────────────────────────────────

    def event_files(self) -> list[Path]:
        """Complete event files of all machines, oldest first."""
        return sorted(self.events_dir.glob("*.jsonl")) if self.events_dir.exists() else []

    def iter_events(self):
        """Events of this tool (not the imports), oldest file first."""
        for path in self.event_files():
            for _, event in iter_events_with_offsets(path):
                yield event

    def import_sources(self) -> list[imports.Source]:
        return imports.find(self.imports_dir)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @property
    def index(self) -> dict:
        if self._index is None:
            if self.index_path.exists():
                self._index = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not self._index or self._index.get("version") != INDEX_VERSION:
                self._index = self._empty_index()
            self.catch_up()
        return self._index

    @staticmethod
    def _empty_index() -> dict:
        return {"version": INDEX_VERSION, "files": [], "entities": {}, "sparql": {}}

    def catch_up(self) -> int:
        """Add complete event files and imported files that the index does not know yet (from earlier runs, other
        machines or new imports)."""
        index = self._index
        known = set(index["files"])
        added = 0
        for path in self.event_files():
            name = self._rel(path)
            if name in known:
                continue
            for offset, event in iter_events_with_offsets(path):
                self._apply(index, event, name, offset)
            index["files"].append(name)
            added += 1
        for source in self.import_sources():
            for path in source.files():
                name = self._rel(path)
                if name in known:
                    continue
                self.log(f"Indexing import {name} ({path.stat().st_size // 1_000_000} MB) ...")
                for offset, record in source.records(path):
                    self._apply(index, record, name, offset)
                index["files"].append(name)
                added += 1
        if added:
            self.save_index()
        return added

    def rebuild_index(self) -> dict:
        """Derive this machine's index from the event log and the imports alone."""
        self._index = self._empty_index()
        self.catch_up()
        self.save_index()
        return self._index

    @staticmethod
    def _apply(index: dict, event: dict, file_name: str, offset: int) -> None:
        kind = event.get("type")
        if kind == "entity_revision":
            entry = index["entities"].setdefault(event["id"], {"versions": []})
            version = {"file": file_name, "offset": offset, "revision": event.get("revision"),
                       "time": event.get("time", ""), "scope": event.get("scope", "full")}
            if version["revision"] is not None and any(
                    v["revision"] == version["revision"] and v["scope"] == version["scope"]
                    for v in entry["versions"]):
                return  # the same revision fetched twice (two machines, or a repeated import)
            entry["versions"].append(version)
            if newer(version, entry.get("latest")):
                entry["latest"] = version
                entry.pop("status", None)
            if version["scope"] in FULL_SCOPES and newer(version, entry.get("full")):
                entry["full"] = version
        elif kind in ("entity_missing", "entity_unlisted"):
            entry = index["entities"].get(event["id"])
            if entry is not None:
                entry["status"] = kind.removeprefix("entity_")
        elif kind == "sparql_response":
            index["sparql"][event["query_hash"]] = {"file": file_name, "offset": offset, "time": event.get("time")}

    def save_index(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
        tmp.replace(self.index_path)

    def revisions(self) -> dict[str, int]:
        """Entity ID -> latest stored full revision, for entities still listed on the server (used by sync)."""
        return {key: entry["full"]["revision"] for key, entry in self.index["entities"].items()
                if "status" not in entry and entry.get("full") and entry["full"].get("revision") is not None}

    def _path(self, file_name: str) -> Path:
        path = self.root / file_name
        return path if path.exists() else path.with_name(path.name + PARTIAL)

    def _load(self, entity_id: str, version: dict) -> dict:
        event = read_event_at(self._path(version["file"]), version["offset"])
        if event.get("type") == "entity_revision":
            return event["entity"]
        return imports.entity_from_record(event, entity_id)

    def ref(self, entity_id: str, scope: str = "any") -> dict | None:
        """Index entry of the version that answers a request: scope 'full' needs a full or full imported version,
        'any' takes the latest of all."""
        entry = self.index["entities"].get(entity_id)
        if not entry:
            return None
        return entry.get("full") if scope == "full" else entry.get("latest")

    def get(self, entity_id: str, revision: int | None = None, scope: str = "any") -> dict | None:
        """The stored entity document: the latest version (scope 'any'), the latest full one (scope 'full'), or the
        given revision. None if nothing suitable is stored."""
        if revision is not None:
            entry = self.index["entities"].get(entity_id) or {"versions": []}
            matches = [v for v in entry["versions"] if v["revision"] == revision]
            matches.sort(key=lambda v: v["scope"] not in FULL_SCOPES)
            return self._load(entity_id, matches[0]) if matches else None
        version = self.ref(entity_id, scope)
        return self._load(entity_id, version) if version else None

    def entities(self, scope: str = "any", prefix: str = ""):
        """(ID, document) for every stored entity still listed on the server, latest version (scope 'any') or latest
        full version (scope 'full'); prefix 'Q' or 'P' limits the kind. Reads from disk one by one."""
        for entity_id in sorted(self.index["entities"], key=lambda i: (i[:1], int(i[1:]) if i[1:].isdigit() else 0)):
            entry = self.index["entities"][entity_id]
            if "status" in entry or not entity_id.startswith(prefix):
                continue
            version = entry.get("full") if scope == "full" else entry.get("latest")
            if version:
                yield entity_id, self._load(entity_id, version)

    def history(self, entity_id: str) -> list[dict]:
        """All stored versions of one entity, oldest first: [{revision, time, scope, file}]."""
        entry = self.index["entities"].get(entity_id) or {"versions": []}
        ordered = sorted(entry["versions"], key=lambda v: (v["time"], v["revision"] or 0))
        return [{"revision": v["revision"], "time": v["time"], "scope": v["scope"], "file": v["file"]}
                for v in ordered]

    def sparql(self, endpoint: str, query: str) -> dict | None:
        ref = self.index["sparql"].get(query_hash(endpoint, query))
        if not ref:
            return None
        return read_event_at(self._path(ref["file"]), ref["offset"])["response"]

    # ── Writing ────────────────────────────────────────────────────────────────

    def recover(self) -> list[str]:
        """Complete this machine's files that a crashed run left as .partial: drop a truncated last line, rename.
        The original partial file is kept next to it with the suffix .recovered."""
        recovered = []
        if not self.events_dir.exists():
            return recovered
        for partial in sorted(self.events_dir.glob(f"*_{self.machine_id}_*.jsonl{PARTIAL}")):
            lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":"))
                     for _, e in iter_events_with_offsets(partial)]
            final = partial.with_name(partial.name.removesuffix(PARTIAL))
            tmp = partial.with_name(partial.name + ".tmp")
            tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")
            tmp.replace(final)
            partial.replace(final.with_name(final.name + ".recovered"))
            recovered.append(final.name)
        return recovered

    @property
    def run_open(self) -> bool:
        return self._handle is not None

    def open_run(self, run: str) -> None:
        """Start a new event file for this run (as .partial until close_run)."""
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.recover()
        self.index  # load and catch up before writing
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prefix = f"{day}_{self.machine_id}_"
        numbers = [int(p.name[len(prefix):len(prefix) + 4]) for p in self.events_dir.glob(prefix + "*")
                   if p.name[len(prefix):len(prefix) + 4].isdigit()]
        self._file = self.events_dir / f"{prefix}{max(numbers, default=0) + 1:04d}.jsonl"
        self._offset = 0
        self._run = run
        self._handle = self._file.with_name(self._file.name + PARTIAL).open("xb")

    def append(self, kind: str, **fields) -> None:
        """Append one event. The line is checked for secrets and echoed headers before it is written."""
        if self._handle is None:
            raise RuntimeError("open_run() first")
        event = {"time": utc_now(), "type": kind, "run": self._run, **fields}
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        check_clean(line, self.secrets)
        data = (line + "\n").encode("utf-8")
        self._handle.write(data)
        self._apply(self.index, event, self._rel(self._file), self._offset)
        self._offset += len(data)

    def flush(self) -> None:
        """Make everything appended so far durable."""
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())

    def close_run(self) -> None:
        """Finish the run's file: from now on it is complete and never changed again."""
        if self._handle is None:
            return
        self.flush()
        self._handle.close()
        self._handle = None
        self._file.with_name(self._file.name + PARTIAL).replace(self._file)
        self.index["files"].append(self._rel(self._file))
        self.save_index()

    def stop_requested(self) -> bool:
        stop = self.root / "STOP"
        return stop.exists() and bool(stop.read_text(encoding="utf-8").strip())
