"""Offline tests: cache-first search and the local /w/api.php stand-in (serve.answer)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_wiki import FakeWiki  # noqa: E402
from test_fetch import OPERATOR, make_cache  # noqa: E402,F401
from wikibase_cache.config import Config, Target  # noqa: E402
from wikibase_cache.fetch import Offline  # noqa: E402
from wikibase_cache.serve import answer  # noqa: E402


@pytest.fixture
def wiki():
    wiki = FakeWiki()
    for n, label in enumerate(["Aristotle", "Thomas Aquinas", "Aristotelianism"], 1):
        wiki.put(f"Q{n}", 100 + n, label)
    wiki.link("Q2", "P31", "Q5")
    return wiki


@pytest.fixture
def config(tmp_path):
    target = Target(name="wd", api="https://fake.invalid/w/api.php", namespaces={"item": 0}, languages=["en"],
                    min_interval=0, batch_size=50, confirm_requests=3, backoff_base=0)
    return Config(OPERATOR, tmp_path / "data", "m1", {"wd": target}, path=tmp_path / "config.local.yaml")


def searches(wiki):
    return [c for c in wiki.calls if c.get("action") == "wbsearchentities"]


def test_search_is_cache_first_and_survives_a_new_process(config, wiki):
    with make_cache(config, wiki) as cache:
        first = cache.search("Aristot", "en", limit=5)
        assert cache.search("Aristot", "en", limit=5) == first
    assert [h["id"] for h in first["search"]] == ["Q1", "Q3"]
    assert len(searches(wiki)) == 1
    with make_cache(config, wiki, offline=True) as cache:
        assert cache.search("Aristot", "en", limit=5) == first
        with pytest.raises(Offline):
            cache.search("Aristot", "en", limit=1)  # another limit is another question


def test_answer_serves_entities_with_requested_props_and_marks_missing(config, wiki):
    with make_cache(config, wiki) as cache:
        got = answer(cache, {"action": "wbgetentities", "ids": "Q2|Q99", "props": "labels|claims"})
    assert set(got["entities"]["Q2"]) == {"id", "type", "labels", "claims"}
    assert got["entities"]["Q99"] == {"id": "Q99", "missing": ""}


def test_answer_refuses_other_actions(config, wiki):
    with make_cache(config, wiki) as cache:
        got = answer(cache, {"action": "wbeditentity"})
    assert got["error"]["code"] == "unsupported"
    assert wiki.calls == []
