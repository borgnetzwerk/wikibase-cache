"""Offline tests for reset (WC9): three questions only in a terminal, checked archive, old folder moved, nothing
deleted, a fresh sync afterwards. No network access (see conftest.py)."""
from __future__ import annotations

import json
import random
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_sync import OPERATOR, make_api, run, target, wiki  # noqa: E402,F401  (fixtures)
from wikibase_cache import __main__ as cli  # noqa: E402
from wikibase_cache import reset  # noqa: E402
from wikibase_cache.config import Config  # noqa: E402
from wikibase_cache.store import Store  # noqa: E402

NOW = datetime(2026, 10, 29, 12, 0, 0)


def answers(*values):
    queue = list(values)
    return lambda prompt: queue.pop(0)


def right_sum(seed: int) -> str:
    rng = random.Random(seed)
    return str(rng.randint(12, 89) + rng.randint(12, 89))


@pytest.fixture
def filled(target, wiki, tmp_path):
    root = tmp_path / target.name
    run(target, wiki, root)
    return tmp_path, root


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_refuses_without_terminal(target, filled):
    data_root, root = filled
    before = snapshot(root)
    p = reset.plan(data_root, target.name, NOW)
    with pytest.raises(reset.NotInteractive):
        reset.confirm(p, ask=answers("yes", "0", target.name), interactive=lambda: False, out=lambda *a: None)
    assert snapshot(root) == before and not (data_root / reset.ARCHIVES).exists()


@pytest.mark.parametrize("given", [("no", "", ""), ("yes", "wrong", "fake"), ("yes", None, "other")])
def test_each_question_must_be_answered(target, filled, given):
    data_root, root = filled
    before = snapshot(root)
    p = reset.plan(data_root, target.name, NOW)
    first, total, name = given
    with pytest.raises(reset.NotConfirmed):
        reset.confirm(p, ask=answers(first, right_sum(7) if total is None else total, name), interactive=lambda: True,
                      rng=random.Random(7), out=lambda *a: None)
    assert snapshot(root) == before and not (data_root / reset.ARCHIVES).exists()


def test_archives_checks_and_moves_without_deleting(target, wiki, filled):
    data_root, root = filled
    before = snapshot(root)
    p = reset.plan(data_root, target.name, NOW)
    reset.confirm(p, ask=answers("yes", right_sum(3), target.name), interactive=lambda: True, rng=random.Random(3),
                  out=lambda *a: None)
    manifest = reset.archive(p, out=lambda *a: None)

    assert not root.exists()
    assert snapshot(p.moved_to) == before                       # moved, not deleted
    with zipfile.ZipFile(p.archive) as zf:
        assert {n: zf.read(n) for n in zf.namelist()} == before    # the archive holds exactly the store
    saved = json.loads(p.archive.with_suffix(".json").read_text(encoding="utf-8"))
    assert saved["files"] == len(before) == manifest["files"] and saved["archive_sha256"]

    run(target, wiki, root)                                     # a fresh store from the server
    assert Store(root, "m1").get("Q1")["labels"]["en"]["value"] == "item 1"


def test_end_of_input_counts_as_no(target, filled):
    data_root, root = filled
    before = snapshot(root)

    def closed(prompt):
        raise EOFError

    p = reset.plan(data_root, target.name, NOW)
    with pytest.raises(reset.NotConfirmed):
        reset.confirm(p, ask=closed, interactive=lambda: True, out=lambda *a: None)
    assert snapshot(root) == before


def test_cli_without_terminal_changes_nothing(target, filled):
    data_root, root = filled
    before = snapshot(root)
    config = Config(OPERATOR, data_root, "m1", {target.name: target})
    code = cli.run_reset(config, target, root, ask=answers("yes", "1", target.name), interactive=lambda: False)
    assert code == 1 and snapshot(root) == before


def test_cli_reset_of_a_target_without_full_sync(target, filled, monkeypatch):
    data_root, root = filled
    target.full_sync = False                                    # no sync afterwards, so no network in this test
    config = Config(OPERATOR, data_root, "m1", {target.name: target})
    monkeypatch.setattr(reset.random, "SystemRandom", lambda: random.Random(11))
    code = cli.run_reset(config, target, root, ask=answers("yes", right_sum(11), target.name), interactive=lambda: True)
    assert code == 0 and not root.exists()
    assert len(list((data_root / reset.ARCHIVES / target.name).glob("*.zip"))) == 1


def test_source_has_no_delete_calls():
    forbidden = ["un" + "link(", "rm" + "tree(", "os." + "remove(", "rm" + "dir("]
    package = Path(__file__).resolve().parent.parent / "wikibase_cache"
    hits = [f"{p.name}: {word}" for p in package.glob("*.py") for word in forbidden if word in p.read_text(encoding="utf-8")]
    assert hits == []
