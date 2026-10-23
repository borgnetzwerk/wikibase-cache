"""Full sync of a small Wikibase: list every entity with its current revision, then fetch only what is missing
from the store or has changed since. A run ends cleanly on its time or request budget, on Ctrl+C or when a
non-empty STOP file exists in the target's data folder; running the same command again continues.
"""
from __future__ import annotations

import signal
import time
import uuid
from dataclasses import dataclass

from .api import Api
from .store import Store


@dataclass
class SyncResult:
    listed: int = 0
    to_fetch: int = 0
    fetched: int = 0
    missing: int = 0
    unlisted: int = 0
    requests: int = 0
    complete: bool = False
    reason: str = ""


class Stopper:
    """Collects the reasons to end a run: signal, STOP file, time and request budget."""

    def __init__(self, store: Store, api: Api, max_seconds: float, max_requests: int, clock=time.monotonic) -> None:
        self.store, self.api = store, api
        self.max_seconds, self.max_requests = max_seconds, max_requests
        self.clock = clock
        self.started = clock()
        self.signalled = False

    def handle_signal(self, signum, frame) -> None:
        self.signalled = True
        print("\nStop requested, ending after the current batch ...", flush=True)

    def reason(self, upcoming_requests: int = 1) -> str | None:
        if self.signalled:
            return "signal"
        if self.store.stop_requested():
            return "STOP file"
        if self.clock() - self.started >= self.max_seconds:
            return f"time budget {self.max_seconds:g} s"
        if self.api.requests + upcoming_requests > self.max_requests:
            return f"request budget {self.max_requests}"
        return None


def check_account(api: Api) -> None:
    """With credentials: they must still belong to the account recorded at add-target."""
    expected = api.target.auth.account
    if api.target.auth.method == "none" or not expected:
        return
    info = api.userinfo()
    if info.get("anon") or info.get("name") != expected:
        raise PermissionError(f"The credentials belong to {info.get('name')!r}, not to {expected} as recorded at "
                              "add-target; nothing fetched. Run add-target again if this is intended.")


def sync(api: Api, store: Store, kinds: list[str] | None = None, max_seconds: float | None = None,
         max_requests: int | None = None, install_signals: bool = True, log=print) -> SyncResult:
    target = api.target
    if not target.full_sync:
        raise ValueError(f"Target {target.name} is not set up for a full sync (add-target --full-sync).")
    kinds = kinds or list(target.namespaces)
    stopper = Stopper(store, api, max_seconds or target.run_max_seconds, max_requests or target.run_max_requests)
    if install_signals:
        previous = {sig: signal.signal(sig, stopper.handle_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    result = SyncResult()
    store.open_run(uuid.uuid4().hex[:12])
    store.append("run_started", mode="sync", kinds=kinds)
    try:
        check_account(api)
        known = store.revisions()
        # Phase 1: list every entity with its current revision (one request per 500 or more entities)
        listed: dict[str, int] = {}
        for kind in kinds:
            cont = None
            while True:
                reason = stopper.reason()
                if reason:
                    result.reason = reason
                    return result
                page, cont = api.list_revisions(target.namespaces[kind], cont)
                listed.update(page)
                if len(listed) > target.full_sync_max_entities:
                    result.reason = (f"more than {target.full_sync_max_entities} entities listed; a full sync is "
                                     "not meant for a wiki of this size (full_sync_max_entities)")
                    return result
                if not cont:
                    break
        result.listed = len(listed)
        log(f"Listed {len(listed)} entities")
        # IDs in the store that the server no longer lists (only after a complete listing)
        for entity_id in sorted(set(known) - set(listed)):
            store.append("entity_unlisted", id=entity_id)
            result.unlisted += 1
        todo = sorted((i for i, rev in listed.items() if known.get(i) != rev), key=_sort_key)
        result.to_fetch = len(todo)
        log(f"{len(todo)} missing or changed, {len(listed) - len(todo)} unchanged")
        # Phase 2: fetch in batches; every batch is on disk before the next request
        size = target.batch_size
        for start in range(0, len(todo), size):
            reason = stopper.reason()
            if reason:
                result.reason = reason
                return result
            batch = todo[start:start + size]
            for entity_id, entity in api.entities(batch).items():
                if "missing" in entity:
                    store.append("entity_missing", id=entity_id)
                    result.missing += 1
                    continue
                store.append("entity_revision", id=entity_id, revision=entity["lastrevid"], scope="full", entity=entity)
                result.fetched += 1
            store.flush()
            log(f"  fetched {min(start + size, len(todo))} of {len(todo)}")
        result.complete = True
        return result
    finally:
        result.requests = api.requests
        store.append("run_finished", requests=result.requests, fetched=result.fetched,
                     complete=result.complete, reason=result.reason)
        store.close_run()
        if install_signals:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def _sort_key(entity_id: str):
    return (entity_id[0], int(entity_id[1:])) if entity_id[1:].isdigit() else (entity_id, 0)
