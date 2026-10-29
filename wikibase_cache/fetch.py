"""Cache-first access to one target: answers from the store and fetches only what is missing.

Fetch modes (taken over from speaker-mining, see docs/glossary.md):
    basic_fetch     labels, descriptions and aliases in the target's languages, and the claims P31 and P279;
                    for many entities, batched 50 per request
    full_fetch      the whole entity document (all claims with qualifiers and references, sitelinks, revision);
                    also batched 50 per request
    fetch_decision  which entities referenced by a fully fetched entity to fetch next, and how; the rules come
                    from the calling project
    expand          full_fetch the seeds, then follow fetch_decision for a given depth
    sparql          a SPARQL query, answered from the store if the same query was asked before

Nothing stored is fetched again unless refresh is asked for (Tim, 2026-10-11: freshness only on explicit request).
Every network run has a request budget; a run that needs more than confirm_requests requests asks first.

    from wikibase_cache.fetch import Cache
    with Cache.open("wikidata") as cache:
        items = cache.basic_fetch(["Q42", "Q1"])
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field

from . import config as cfg
from .config import Config, Target
from .store import FULL_SCOPES, Store, params_key, query_hash

BASIC_PROPS = ["labels", "descriptions", "aliases", "claims", "info"]
BASIC_CLAIMS = ("P31", "P279")
MODES = ("basic", "full", "skip")


class BudgetExceeded(Exception):
    pass


class NotConfirmed(Exception):
    pass


class Offline(Exception):
    """Something is missing from the store and the cache was opened offline."""


@dataclass
class Rules:
    """fetch_decision rules: property -> mode for the entities it points to ('basic', 'full' or 'skip').
    Properties not listed get `default`."""
    follow: dict[str, str] = field(default_factory=dict)
    default: str = "skip"

    @classmethod
    def from_dict(cls, data: dict) -> "Rules":
        rules = cls(dict(data.get("follow") or {}), data.get("default", "skip"))
        bad = [m for m in [*rules.follow.values(), rules.default] if m not in MODES]
        if bad:
            raise ValueError(f"Unknown mode(s) {bad}; allowed: {', '.join(MODES)}")
        return rules


def entity_ids_in_claims(entity: dict) -> list[tuple[str, str]]:
    """(property, entity ID) for every main value that is an entity, in claim order."""
    pairs = []
    for prop, statements in (entity.get("claims") or {}).items():
        for statement in statements or []:
            snak = statement.get("mainsnak") or {}
            value = (snak.get("datavalue") or {}).get("value")
            if snak.get("snaktype") == "value" and isinstance(value, dict) and value.get("id"):
                pairs.append((prop, value["id"]))
    return pairs


def fetch_decision(entity: dict, rules: Rules) -> dict[str, str]:
    """Entity ID -> mode for the entities this one points to; the stronger mode wins (full over basic)."""
    decisions: dict[str, str] = {}
    for prop, target_id in entity_ids_in_claims(entity):
        mode = rules.follow.get(prop, rules.default)
        if mode == "skip":
            continue
        if decisions.get(target_id) != "full":
            decisions[target_id] = mode
    return decisions


def reduce_to_basic(entity: dict) -> dict:
    """Keep what basic_fetch promises: all but claims other than P31 and P279."""
    reduced = {k: v for k, v in entity.items() if k not in ("claims", "sitelinks")}
    reduced["claims"] = {p: v for p, v in (entity.get("claims") or {}).items() if p in BASIC_CLAIMS}
    return reduced


class Cache:
    def __init__(self, config: Config, target: Target, session=None, offline: bool = False,
                 max_requests: int | None = None, confirm=None, log=print) -> None:
        self.config, self.target = config, target
        self.session, self.offline, self.log = session, offline, log
        self.max_requests = max_requests if max_requests is not None else target.run_max_requests
        self.confirm = confirm  # callable(message) -> bool; None means: refuse runs above confirm_requests
        self.store = Store(config.target_dir(target.name), config.machine_id, log=log)
        self._api = None
        self.fetched = 0

    @classmethod
    def open(cls, target_name: str, **kwargs) -> "Cache":
        config = cfg.load()
        return cls(config, config.target(target_name), **kwargs)

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close(error=exc)

    def close(self, error: BaseException | None = None) -> None:
        if self.store.run_open:
            reason = f"{type(error).__name__}: {error}" if error else ""
            self.store.append("run_finished", requests=self.requests, fetched=self.fetched, complete=error is None,
                              reason=reason[:300])
            self.store.close_run()

    @property
    def requests(self) -> int:
        return self._api.requests if self._api else 0

    @property
    def api(self):
        if self._api is None:
            from .api import Api
            from .sync import check_account

            self._api = Api(self.target, self.config.operator, session=self.session, log=self.log)
            self.store.secrets = self._api.secrets
            check_account(self._api)
        return self._api

    # ── Planning ───────────────────────────────────────────────────────────────

    def _approve(self, needed: int, what: str) -> None:
        if needed == 0:
            return
        if self.offline:
            raise Offline(f"{what}: not in the store, and the cache is offline.")
        spent = self.requests
        if spent + needed > self.max_requests:
            raise BudgetExceeded(f"{what} needs {needed} requests; budget {self.max_requests}, used {spent}.")
        if needed > self.target.confirm_requests:
            message = f"{what} needs {needed} requests to {self.target.name}. Continue?"
            if self.confirm is None or not self.confirm(message):
                raise NotConfirmed(message)

    def _ensure_run(self, mode: str) -> None:
        if not self.store.run_open:
            self.api  # login and account check before anything is written
            self.store.open_run(uuid.uuid4().hex[:12])
            self.store.append("run_started", mode=mode)

    # ── Entities ───────────────────────────────────────────────────────────────

    def missing(self, ids: list[str], mode: str) -> list[str]:
        scope = "full" if mode == "full" else "any"
        return [i for i in dict.fromkeys(ids) if self.store.ref(i, scope) is None]

    def entities(self, ids: list[str], mode: str = "basic", refresh: bool = False) -> dict[str, dict]:
        """Entity documents for ids, cache-first. mode 'basic' accepts any stored version, 'full' only full ones."""
        if mode not in ("basic", "full"):
            raise ValueError("mode must be 'basic' or 'full'")
        ids = list(dict.fromkeys(ids))
        todo = ids if refresh else self.missing(ids, mode)
        size = self.target.batch_size
        self._approve(math.ceil(len(todo) / size), f"{mode}_fetch of {len(todo)} entities")
        if todo:
            self._ensure_run(mode + "_fetch")
            for start in range(0, len(todo), size):
                self._fetch_batch(todo[start:start + size], mode)
                self.store.flush()
        scope = "full" if mode == "full" else "any"
        return {i: e for i in ids if (e := self.store.get(i, scope=scope)) is not None}

    def _fetch_batch(self, batch: list[str], mode: str) -> None:
        if mode == "full":
            answer = self.api.entities(batch)
        else:
            answer = self.api.entities(batch, props=BASIC_PROPS, languages=self.target.languages)
        for entity_id, entity in answer.items():
            if "missing" in entity:
                self.store.append("entity_missing", id=entity_id)
                continue
            if mode == "full":
                self.store.append("entity_revision", id=entity_id, revision=entity.get("lastrevid"), scope="full",
                                  entity=entity)
            else:
                self.store.append("entity_revision", id=entity_id, revision=entity.get("lastrevid"), scope="basic",
                                  languages=self.target.languages, entity=reduce_to_basic(entity))
            self.fetched += 1

    def basic_fetch(self, ids: list[str], refresh: bool = False) -> dict[str, dict]:
        return self.entities(ids, "basic", refresh)

    def full_fetch(self, ids: list[str], refresh: bool = False) -> dict[str, dict]:
        return self.entities(ids, "full", refresh)

    def expand(self, seeds: list[str], rules: Rules, depth: int = 1) -> dict[str, str]:
        """full_fetch the seeds, then fetch what fetch_decision names, level by level. Returns ID -> mode reached.
        Entities fetched with basic are not followed further; full ones are, until depth is reached."""
        reached: dict[str, str] = {}
        frontier = list(dict.fromkeys(seeds))
        for level in range(depth + 1):
            if not frontier:
                break
            for entity_id, entity in self.full_fetch(frontier).items():
                reached[entity_id] = "full"
            if level == depth:
                break
            basic, full = set(), set()
            for entity_id in frontier:
                entity = self.store.get(entity_id, scope="full")
                if entity is None:
                    continue
                for target_id, mode in fetch_decision(entity, rules).items():
                    if reached.get(target_id) == "full":
                        continue
                    (full if mode == "full" else basic).add(target_id)
            basic -= full
            for entity_id in self.basic_fetch(sorted(basic)):
                reached.setdefault(entity_id, "basic")
            frontier = sorted(full)
        return reached

    # ── SPARQL ─────────────────────────────────────────────────────────────────

    def sparql(self, query: str, refresh: bool = False) -> dict:
        endpoint = self.target.sparql or ""
        if not refresh:
            cached = self.store.sparql(endpoint, query)
            if cached is not None:
                return cached
        self._approve(1, "SPARQL query")
        self._ensure_run("sparql")
        response = self.api.sparql(query)
        raw = json.dumps(response, ensure_ascii=False, sort_keys=True)
        self.store.append("sparql_response", endpoint=endpoint, query=query, query_hash=query_hash(endpoint, query),
                          response=response, sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.store.flush()
        return response

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, text: str, language: str, limit: int = 7, entity_type: str = "item",
               refresh: bool = False) -> dict:
        """wbsearchentities answer for one text, cache-first. The result part of the answer is kept as the server
        sent it; the entities it names are not fetched (that is entities())."""
        params = {"action": "wbsearchentities", "search": text, "language": language, "uselang": language,
                  "type": entity_type, "limit": int(limit)}
        if not refresh:
            cached = self.store.api_response(self.target.api, params)
            if cached is not None:
                return cached
        self._approve(1, f"search for {text!r}")
        self._ensure_run("search")
        # only the result; some servers echo the request headers in debuginfo, which must never be stored
        response = {k: v for k, v in self.api.get(params).items() if k in ("search", "searchinfo", "success")}
        raw = json.dumps(response, ensure_ascii=False, sort_keys=True)
        self.store.append("api_response", endpoint=self.target.api, params=params,
                          query_hash=query_hash(self.target.api, params_key(params)), response=response,
                          sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.store.flush()
        return response

    def scope_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.store.index["entities"].values():
            scope = entry["latest"]["scope"] if entry.get("latest") else "none"
            counts[scope] = counts.get(scope, 0) + 1
        return counts


__all__ = ["Cache", "Rules", "fetch_decision", "BudgetExceeded", "NotConfirmed", "Offline", "FULL_SCOPES"]
