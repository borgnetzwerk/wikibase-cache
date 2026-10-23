"""Local storage of one target: an append-only event log and an index derived from it.

The layout is safe for a data root that a file sync service (Nextcloud, Syncthing, ...) shares between machines:
no file is ever changed by two machines, and no file is changed after it is complete.

Layout below <data_root>/<target>/:
    events/<date>_<machine>_<NNNN>.jsonl           one file per run, written once, never changed afterwards
    events/<date>_<machine>_<NNNN>.jsonl.partial   the file of a run in progress; only its machine writes it,
                                                   other machines ignore it until it is renamed
    index/<machine>.json                           this machine's index, derived from all complete event files
    STOP                                           a non-empty file here ends a running sync after the current batch

Event files of other machines are picked up on the next open: whatever is not yet in this machine's index is
read and added. If two machines fetched the same revision, the duplicate counts once.

Events (one JSON object per line, each with time (UTC, ISO 8601), type and run):
    run_started      {mode, kinds}
    entity_revision  {id, revision, entity}     the entity document exactly as the server sent it
    entity_missing   {id}                       the server reported the ID as missing
    entity_unlisted  {id}                       the ID no longer appears in the listing (deleted or moved)
    run_finished     {requests, fetched, complete, reason}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Text that must never reach the disk (some instances echo request headers in debuginfo)
LEAK_MARKERS = ("Bearer ", "debuginfo", "Authorization:")
PARTIAL = ".partial"


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


def iter_lines(path: Path):
    """(line number, event) for every complete event; a truncated last line (crash during writing) is skipped."""
    with path.open("r", encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield number, event


class Store:
    def __init__(self, root: Path, machine_id: str, secrets: list[str] = ()) -> None:
        self.root = Path(root)
        self.machine_id = machine_id
        self.events_dir = self.root / "events"
        self.index_path = self.root / "index" / f"{machine_id}.json"
        self.secrets = list(secrets)
        self._index: dict | None = None
        self._file: Path | None = None
        self._handle = None
        self._line = 0
        self._run = ""

    # ── Reading ────────────────────────────────────────────────────────────────

    def event_files(self) -> list[Path]:
        """Complete event files of all machines, oldest first."""
        return sorted(self.events_dir.glob("*.jsonl")) if self.events_dir.exists() else []

    def iter_events(self):
        for path in self.event_files():
            for _, event in iter_lines(path):
                yield event

    @property
    def index(self) -> dict:
        if self._index is None:
            if self.index_path.exists():
                self._index = json.loads(self.index_path.read_text(encoding="utf-8"))
            else:
                self._index = {"files": [], "entities": {}}
            self.catch_up()
        return self._index

    def catch_up(self) -> int:
        """Add complete event files that the index does not know yet (from earlier runs or other machines)."""
        index = self._index
        known = set(index["files"])
        new = [path for path in self.event_files() if path.name not in known]
        for path in new:
            for number, event in iter_lines(path):
                self._apply(index, event, path.name, number)
            index["files"].append(path.name)
        if new:
            self.save_index()
        return len(new)

    def rebuild_index(self) -> dict:
        """Derive this machine's index from the event log alone."""
        self._index = {"files": [], "entities": {}}
        self.catch_up()
        self.save_index()
        return self._index

    @staticmethod
    def _apply(index: dict, event: dict, file_name: str, line: int) -> None:
        entities = index["entities"]
        kind, entity_id = event.get("type"), event.get("id")
        if kind == "entity_revision":
            current = entities.get(entity_id)
            if current is None or "status" in current or event["revision"] > current["revision"]:
                entities[entity_id] = {"revision": event["revision"], "file": file_name, "line": line}
        elif kind in ("entity_missing", "entity_unlisted") and entity_id in entities:
            entities[entity_id]["status"] = kind.removeprefix("entity_")

    def save_index(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
        tmp.replace(self.index_path)

    def revisions(self) -> dict[str, int]:
        """Entity ID -> latest stored revision, for entities still listed on the server."""
        return {key: value["revision"] for key, value in self.index["entities"].items() if "status" not in value}

    def _event_path(self, file_name: str) -> Path:
        path = self.events_dir / file_name
        return path if path.exists() else path.with_name(file_name + PARTIAL)

    def get(self, entity_id: str, revision: int | None = None) -> dict | None:
        """The stored entity document: the latest revision, or the given one. None if it was never fetched."""
        if revision is None:
            ref = self.index["entities"].get(entity_id)
            if not ref:
                return None
            for number, event in iter_lines(self._event_path(ref["file"])):
                if number == ref["line"]:
                    return event["entity"]
            return None
        for event in self.iter_events():
            if event.get("type") == "entity_revision" and event["id"] == entity_id and event["revision"] == revision:
                return event["entity"]
        return None

    def history(self, entity_id: str) -> list[dict]:
        """All stored revisions of one entity, oldest first, each revision once: [{revision, time}]."""
        seen, result = set(), []
        for event in self.iter_events():
            if event.get("type") == "entity_revision" and event["id"] == entity_id and event["revision"] not in seen:
                seen.add(event["revision"])
                result.append({"revision": event["revision"], "time": event["time"]})
        return sorted(result, key=lambda item: item["revision"])

    # ── Writing ────────────────────────────────────────────────────────────────

    def recover(self) -> list[str]:
        """Complete this machine's files that a crashed run left as .partial: drop a truncated last line, rename."""
        recovered = []
        for partial in sorted(self.events_dir.glob(f"*_{self.machine_id}_*.jsonl{PARTIAL}")):
            lines = [json.dumps(event, ensure_ascii=False, separators=(",", ":")) for _, event in iter_lines(partial)]
            final = partial.with_name(partial.name.removesuffix(PARTIAL))
            tmp = partial.with_name(partial.name + ".tmp")
            tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")
            tmp.replace(final)
            partial.replace(final.with_name(final.name + ".recovered"))
            recovered.append(final.name)
        return recovered

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
        self._line = 0
        self._run = run
        self._handle = self._file.with_name(self._file.name + PARTIAL).open("x", encoding="utf-8", newline="\n")

    def append(self, kind: str, **fields) -> None:
        """Append one event. The line is checked for secrets and echoed headers before it is written."""
        if self._handle is None:
            raise RuntimeError("open_run() first")
        event = {"time": utc_now(), "type": kind, "run": self._run, **fields}
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        check_clean(line, self.secrets)
        self._handle.write(line + "\n")
        self._line += 1
        self._apply(self.index, event, self._file.name, self._line)

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
        self.index["files"].append(self._file.name)
        self.save_index()

    def stop_requested(self) -> bool:
        stop = self.root / "STOP"
        return stop.exists() and bool(stop.read_text(encoding="utf-8").strip())
