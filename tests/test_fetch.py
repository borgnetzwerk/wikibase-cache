"""Offline tests: cache-first fetch modes, imports read in place, budget, SPARQL cache, .env file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_wiki import FakeWiki  # noqa: E402
from wikibase_cache import config as cfg  # noqa: E402
from wikibase_cache.config import Auth, Config, ConfigError, Operator, Target  # noqa: E402
from wikibase_cache.fetch import BudgetExceeded, Cache, NotConfirmed, Offline, Rules, fetch_decision  # noqa: E402
from wikibase_cache.store import Store  # noqa: E402

OPERATOR = Operator("TestOperatorBot", "https://example.net/contact")


@pytest.fixture
def wiki():
    wiki = FakeWiki()
    for n in range(1, 8):
        wiki.put(f"Q{n}", 100 + n, f"item {n}")
    wiki.link("Q1", "P31", "Q2")
    wiki.link("Q1", "P50", "Q3")
    wiki.link("Q1", "P999", "Q4")
    wiki.link("Q3", "P50", "Q5")
    return wiki


@pytest.fixture
def config(tmp_path):
    target = Target(name="wd", api="https://fake.invalid/w/api.php", namespaces={"item": 0},
                    sparql="https://fake.invalid/sparql", languages=["de", "en"], min_interval=0, batch_size=2,
                    confirm_requests=3, backoff_base=0)
    return Config(OPERATOR, tmp_path / "data", "m1", {"wd": target}, path=tmp_path / "config.local.yaml")


def make_cache(config, wiki, **kwargs):
    cache = Cache(config, config.targets["wd"], session=wiki, log=lambda *a: None, **kwargs)
    wiki.headers = {}
    return cache


def entity_calls(wiki):
    return [c for c in wiki.calls if c.get("action") == "wbgetentities"]


def test_basic_fetch_keeps_only_p31_p279_and_is_cache_first(config, wiki):
    with make_cache(config, wiki) as cache:
        got = cache.basic_fetch(["Q1", "Q2"])
    assert set(got["Q1"]["claims"]) == {"P31"}
    call = entity_calls(wiki)[0]
    assert call["props"] == "labels|descriptions|aliases|claims|info" and call["languages"] == "de|en"
    wiki.calls.clear()
    with make_cache(config, wiki) as cache:
        assert cache.basic_fetch(["Q1", "Q2"])["Q2"]["id"] == "Q2"
    assert entity_calls(wiki) == []


def test_full_fetch_is_not_answered_by_basic(config, wiki):
    with make_cache(config, wiki) as cache:
        cache.basic_fetch(["Q1"])
        full = cache.full_fetch(["Q1"])
    assert set(full["Q1"]["claims"]) == {"P31", "P50", "P999"}
    assert "props" not in entity_calls(wiki)[-1]
    with make_cache(config, wiki) as cache:  # full answers basic too
        assert set(cache.basic_fetch(["Q1"])["Q1"]["claims"]) == {"P31", "P50", "P999"}


def test_refresh_fetches_again_and_keeps_both_revisions(config, wiki):
    with make_cache(config, wiki) as cache:
        cache.full_fetch(["Q2"])
    wiki.put("Q2", 300, "item 2 changed")
    with make_cache(config, wiki) as cache:
        assert cache.full_fetch(["Q2"])["Q2"]["lastrevid"] == 102  # no refresh: stored answer
        assert cache.full_fetch(["Q2"], refresh=True)["Q2"]["lastrevid"] == 300
    assert [h["revision"] for h in Store(config.target_dir("wd"), "m1").history("Q2")] == [102, 300]


def test_offline_answers_from_store_only(config, wiki):
    with make_cache(config, wiki) as cache:
        cache.basic_fetch(["Q1"])
    wiki.calls.clear()
    with make_cache(config, wiki, offline=True) as cache:
        assert "Q1" in cache.basic_fetch(["Q1"])
        with pytest.raises(Offline):
            cache.basic_fetch(["Q6"])
    assert wiki.calls == []


def test_budget_and_confirmation(config, wiki):
    ids = [f"Q{n}" for n in range(1, 8)]  # 7 entities, batch size 2: 4 requests
    with pytest.raises(BudgetExceeded):
        with make_cache(config, wiki, max_requests=3) as cache:
            cache.basic_fetch(ids)
    with pytest.raises(NotConfirmed):  # above confirm_requests (3), nobody confirms
        with make_cache(config, wiki) as cache:
            cache.basic_fetch(ids)
    assert entity_calls(wiki) == []
    asked = []
    with make_cache(config, wiki, confirm=lambda message: asked.append(message) or True) as cache:
        assert len(cache.basic_fetch(ids)) == 7
    assert len(asked) == 1 and "4 requests" in asked[0]


def test_fetch_decision_and_expand(config, wiki):
    rules = Rules.from_dict({"follow": {"P31": "basic", "P50": "full"}, "default": "skip"})
    assert fetch_decision(wiki.entities["Q1"], rules) == {"Q2": "basic", "Q3": "full"}
    with make_cache(config, wiki) as cache:
        reached = cache.expand(["Q1"], rules, depth=2)
    assert reached == {"Q1": "full", "Q2": "basic", "Q3": "full", "Q5": "full"}
    assert "Q4" not in reached  # P999 is skipped


def test_failed_run_is_recorded_as_incomplete(config, wiki):
    wiki.fail_next = [503] * 10
    with pytest.raises(Exception):
        with make_cache(config, wiki) as cache:
            cache.basic_fetch(["Q1"])
    finished = [e for e in Store(config.target_dir("wd"), "m1").iter_events() if e["type"] == "run_finished"]
    assert finished[-1]["complete"] is False and "ApiError" in finished[-1]["reason"]


def test_sparql_is_cached(config, wiki):
    query = "SELECT ?x WHERE { ?x wdt:P31 wd:Q5 }  "
    with make_cache(config, wiki) as cache:
        first = cache.sparql(query)
    with make_cache(config, wiki) as cache:
        again = cache.sparql("SELECT ?x WHERE { ?x wdt:P31 wd:Q5 }")
    assert first == again
    assert len([c for c in wiki.calls if "sparql" in c]) == 1


def write_speaker_mining_chunk(path: Path, entities: dict, query: str, time: str) -> None:
    event = {"event_version": "v3", "event_type": "query_response", "timestamp_utc": time,
             "payload": {"endpoint": "wikidata_api", "normalized_query": query,
                         "response_data": {"entities": entities}}}
    other = {"event_version": "v3", "event_type": "triple_discovered", "payload": {"subject_qid": "Q1"}}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(other) + "\n" + json.dumps(event) + "\n")


def test_import_is_read_in_place_and_answers_requests(config, wiki):
    folder = config.target_dir("wd") / "imports" / "sm"
    (folder / "chunks").mkdir(parents=True)
    (folder / "source.yaml").write_text('format: speaker-mining-v3\nfiles: ["chunks/*.jsonl"]\n', encoding="utf-8")
    chunk = folder / "chunks" / "eventstore_chunk_0001.jsonl"
    full_doc = {"labels": {}, "descriptions": {}, "aliases": {}, "claims": {"P31": []}}
    write_speaker_mining_chunk(chunk, {"Q1": {"id": "Q1", **full_doc}},
                               "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1"
                               "&props=labels%7Cdescriptions%7Caliases%7Cclaims", "2026-04-10T10:00:00Z")
    write_speaker_mining_chunk(chunk, {"Q2": {"id": "Q2", "labels": {}, "claims": {}}},
                               "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q2&props=labels%7Cclaims",
                               "2026-04-11T10:00:00Z")
    write_speaker_mining_chunk(chunk, {"P50": {"id": "P50", "datatype": "wikibase-item", **full_doc}},
                               "property:P50", "2026-04-12T10:00:00Z")  # speaker-mining's property_fetch
    before = chunk.read_bytes()
    with make_cache(config, wiki) as cache:
        assert cache.full_fetch(["Q1"])["Q1"]["claims"] == {"P31": []}  # import-full answers full
        assert cache.full_fetch(["P50"])["P50"]["datatype"] == "wikibase-item"
        assert cache.basic_fetch(["Q2"])["Q2"]["id"] == "Q2"           # import-basic answers basic
        cache.full_fetch(["Q2"])                                        # but not full
    assert [c["ids"] for c in entity_calls(wiki)] == ["Q2"]
    assert chunk.read_bytes() == before  # the archive is never changed
    history = Store(config.target_dir("wd"), "m1").history("Q2")
    assert [h["scope"] for h in history] == ["import-basic", "full"]


def test_env_file_is_used_after_environment(tmp_path, monkeypatch):
    env = tmp_path / "secrets" / ".env"
    env.parent.mkdir()
    env.write_text('# comment\nexport WIKI_TOKEN="from-file"\nOTHER=x\n', encoding="utf-8")
    data_root = tmp_path / "data"
    path = cfg.validate_env_file(str(env), data_root)
    auth = Auth(method="oauth2", token_env="WIKI_TOKEN", env_file_values=cfg.read_env_file(path))
    monkeypatch.delenv("WIKI_TOKEN", raising=False)
    assert auth.secret("WIKI_TOKEN") == "from-file"
    monkeypatch.setenv("WIKI_TOKEN", "from-environment")
    assert auth.secret("WIKI_TOKEN") == "from-environment"


def test_env_file_inside_repo_or_data_root_is_refused(tmp_path):
    inside_root = tmp_path / "data" / ".env"
    inside_root.parent.mkdir()
    inside_root.write_text("A=1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="data root"):
        cfg.validate_env_file(str(inside_root), tmp_path / "data")
    with pytest.raises(ConfigError, match="repository"):
        cfg.validate_env_file(str(cfg.REPO_ROOT / "README.md"), tmp_path / "data")


def test_config_with_env_file_round_trips(tmp_path):
    env = tmp_path / "s.env"
    env.write_text("T=1\n", encoding="utf-8")
    config = Config(OPERATOR, tmp_path / "data", "m1",
                    {"w": Target(name="w", api="https://x.invalid/w/api.php", namespaces={"item": 0},
                                 auth=Auth(method="oauth2", token_env="T"))},
                    path=tmp_path / "config.local.yaml", env_file=env)
    config.save()
    assert "T=1" not in config.path.read_text(encoding="utf-8")
    loaded = cfg.load(config.path)
    assert loaded.env_file == env and loaded.targets["w"].auth.secret("T") == "1"
