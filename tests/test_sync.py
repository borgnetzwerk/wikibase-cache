"""Offline tests: setup, sync, incremental second run, two machines, reading, login methods, leak protection.
No network access (see conftest.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_wiki import FakeWiki  # noqa: E402
from wikibase_cache import __main__ as cli  # noqa: E402
from wikibase_cache import config as cfg  # noqa: E402
from wikibase_cache.api import Api, ApiError  # noqa: E402
from wikibase_cache.config import Auth, ConfigError, NotSetUp, Operator, Target  # noqa: E402
from wikibase_cache.scan import scan  # noqa: E402
from wikibase_cache.store import LeakError, Store  # noqa: E402
from wikibase_cache.sync import sync  # noqa: E402

TOKEN = "test-token-abc123"
PASSWORD = "bot-password-xyz789"
OPERATOR = Operator("TestOperatorBot", "https://example.net/contact")


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setenv("TEST_WIKIBASE_TOKEN", TOKEN)
    return Target(name="fake", api="https://fake.invalid/w/api.php", namespaces={"item": 120, "property": 122},
                  auth=Auth(method="oauth2", token_env="TEST_WIKIBASE_TOKEN", account="ExampleBot"),
                  min_interval=0, batch_size=2, full_sync=True)


@pytest.fixture
def wiki():
    wiki = FakeWiki(php_notice=True)
    for n in range(1, 6):
        wiki.put(f"Q{n}", 100 + n, f"item {n}")
    wiki.put("P1", 50, "property 1")
    return wiki


def make_api(target, wiki):
    api = Api(target, OPERATOR, session=wiki, sleep=lambda s: None, log=lambda *a: None)
    wiki.headers = api.session.headers
    return api


def run(target, wiki, root, machine="m1", **kwargs):
    api = make_api(target, wiki)
    return sync(api, Store(root, machine, secrets=api.secrets), install_signals=False, log=lambda *a: None, **kwargs)


# ── Sync ──────────────────────────────────────────────────────────────────────

def test_first_sync_fetches_everything(target, wiki, tmp_path):
    result = run(target, wiki, tmp_path)
    assert result.complete and result.listed == 6 and result.fetched == 6
    store = Store(tmp_path, "m1")
    assert store.get("Q3")["labels"]["en"]["value"] == "item 3"
    assert store.get("P1")["lastrevid"] == 50
    assert not list(tmp_path.glob("events/*.partial"))


def test_second_sync_fetches_only_changed_and_new(target, wiki, tmp_path):
    run(target, wiki, tmp_path)
    wiki.put("Q2", 200, "item 2 renamed")
    wiki.put("Q6", 106, "item 6")
    wiki.calls.clear()
    result = run(target, wiki, tmp_path)
    assert result.complete and result.fetched == 2
    assert [c["ids"] for c in wiki.calls if c.get("action") == "wbgetentities"] == ["Q2|Q6"]
    store = Store(tmp_path, "m1")
    assert store.get("Q2")["labels"]["en"]["value"] == "item 2 renamed"
    assert store.get("Q2", revision=102)["labels"]["en"]["value"] == "item 2"
    assert [h["revision"] for h in store.history("Q2")] == [102, 200]


def test_unchanged_wiki_needs_no_entity_requests(target, wiki, tmp_path):
    run(target, wiki, tmp_path)
    wiki.calls.clear()
    assert run(target, wiki, tmp_path).fetched == 0
    assert not [c for c in wiki.calls if c.get("action") == "wbgetentities"]


def test_deleted_entity_is_marked_unlisted(target, wiki, tmp_path):
    run(target, wiki, tmp_path)
    del wiki.entities["Q4"]
    assert run(target, wiki, tmp_path).unlisted == 1
    store = Store(tmp_path, "m1")
    assert "Q4" not in store.revisions()
    assert store.get("Q4")["id"] == "Q4"  # the last seen revision stays readable


def test_request_budget_interrupts_and_next_run_continues(target, wiki, tmp_path):
    first = run(target, wiki, tmp_path, max_requests=6)
    assert not first.complete and first.reason.startswith("request budget")
    assert 0 < first.fetched < 6
    second = run(target, wiki, tmp_path)
    assert second.complete and first.fetched + second.fetched == 6


def test_stop_file_ends_run(target, wiki, tmp_path):
    (tmp_path / "STOP").write_text("stop", encoding="utf-8")
    result = run(target, wiki, tmp_path)
    assert not result.complete and result.reason == "STOP file" and result.fetched == 0


def test_too_large_wiki_is_not_fully_synced(target, wiki, tmp_path):
    target.full_sync_max_entities = 4
    result = run(target, wiki, tmp_path)
    assert not result.complete and "full_sync_max_entities" in result.reason
    assert not [c for c in wiki.calls if c.get("action") == "wbgetentities"]


def test_wrong_account_fetches_nothing(target, wiki, tmp_path):
    wiki.user = "SomeoneElse"
    with pytest.raises(PermissionError):
        run(target, wiki, tmp_path)
    assert not [c for c in wiki.calls if c.get("action") == "wbgetentities"]


def test_backoff_on_overload(target, wiki, tmp_path):
    wiki.fail_next = [503, 429]
    assert run(target, wiki, tmp_path).complete


# ── Several machines sharing one data root ────────────────────────────────────

def test_second_machine_reuses_first_machines_fetches(target, wiki, tmp_path):
    run(target, wiki, tmp_path, machine="aaaaaa")
    wiki.calls.clear()
    result = run(target, wiki, tmp_path, machine="bbbbbb")
    assert result.fetched == 0
    assert not [c for c in wiki.calls if c.get("action") == "wbgetentities"]
    assert Store(tmp_path, "bbbbbb").get("Q1")["id"] == "Q1"


def test_parallel_fetch_of_same_revision_counts_once(target, wiki, tmp_path):
    # both machines fetch before either sees the other's file (sync service not yet caught up)
    run(target, wiki, tmp_path / "a", machine="aaaaaa")
    run(target, wiki, tmp_path / "b", machine="bbbbbb")
    merged = tmp_path / "merged" / "events"
    merged.mkdir(parents=True)
    for path in list((tmp_path / "a" / "events").glob("*.jsonl")) + list((tmp_path / "b" / "events").glob("*.jsonl")):
        path.replace(merged / path.name)
    store = Store(tmp_path / "merged", "cccccc")
    assert len(store.index["entities"]) == 6
    assert [h["revision"] for h in store.history("Q1")] == [101]


def test_files_of_each_machine_are_named_by_machine(target, wiki, tmp_path):
    run(target, wiki, tmp_path, machine="aaaaaa")
    run(target, wiki, tmp_path, machine="bbbbbb")
    names = sorted(p.name for p in (tmp_path / "events").glob("*.jsonl"))
    assert len(names) == 2 and "_aaaaaa_" in names[0] + names[1] and "_bbbbbb_" in names[0] + names[1]
    assert sorted(p.name for p in (tmp_path / "index").glob("*.json")) == ["aaaaaa.json", "bbbbbb.json"]


def test_other_machines_partial_file_is_ignored_and_own_is_recovered(target, wiki, tmp_path):
    events = tmp_path / "events"
    events.mkdir()
    line = json.dumps({"time": "t", "type": "entity_revision", "run": "r", "id": "Q9", "revision": 9,
                       "entity": {"id": "Q9"}})
    (events / "2026-01-01_bbbbbb_0001.jsonl.partial").write_text(line + "\n", encoding="utf-8")
    (events / "2026-01-01_aaaaaa_0001.jsonl.partial").write_text(line + "\n{broken", encoding="utf-8")
    run(target, wiki, tmp_path, machine="aaaaaa")
    store = Store(tmp_path, "aaaaaa")
    assert (events / "2026-01-01_aaaaaa_0001.jsonl").exists()
    assert store.get("Q9") == {"id": "Q9"}  # recovered own file
    assert (events / "2026-01-01_bbbbbb_0001.jsonl.partial").exists()  # other machine's file untouched


# ── Secrets ───────────────────────────────────────────────────────────────────

def test_stored_data_contains_no_secret_or_debuginfo(target, wiki, tmp_path):
    run(target, wiki, tmp_path)
    assert scan(tmp_path, [TOKEN]) == {}
    assert TOKEN in json.dumps(dict(wiki.headers))  # the fake really did see the token


def test_entity_containing_token_is_refused(target, wiki, tmp_path):
    wiki.put("Q7", 107, f"Bearer {TOKEN}")
    with pytest.raises(LeakError):
        run(target, wiki, tmp_path)
    assert scan(tmp_path, [TOKEN]) == {}


def test_scan_reports_planted_secret(tmp_path):
    (tmp_path / "x.jsonl").write_text(f'{{"a": "{TOKEN}"}}\n', encoding="utf-8")
    assert scan(tmp_path, [TOKEN]) == {"x.jsonl": {"secret1": 1}}


def test_error_message_never_contains_token(target, wiki):
    api = make_api(target, wiki)
    wiki._answer = lambda params: {"error": {"code": "permissiondenied", "info": f"header {TOKEN}"}}
    with pytest.raises(ApiError) as error:
        api.get({"action": "query"})
    assert TOKEN not in str(error.value)


def test_bot_password_login_and_sync(monkeypatch, wiki, tmp_path):
    monkeypatch.setenv("BOT_USER", "Example@cache")
    monkeypatch.setenv("BOT_PASSWORD", PASSWORD)
    wiki.bot_login = ("Example@cache", PASSWORD)
    wiki.user = "Example"
    target = Target(name="fake", api="https://fake.invalid/w/api.php", namespaces={"item": 120, "property": 122},
                    auth=Auth(method="botpassword", username_env="BOT_USER", password_env="BOT_PASSWORD",
                              account="Example"), min_interval=0, full_sync=True)
    result = run(target, wiki, tmp_path)
    assert result.complete and result.fetched == 6
    login = [c for c in wiki.calls if c.get("action") == "login"]
    assert len(login) == 1 and login[0]["lgtoken"] == "login-token+\\"
    assert scan(tmp_path, [PASSWORD, "session-cookie-value"]) == {}


def test_wrong_bot_password_fails(monkeypatch, wiki):
    monkeypatch.setenv("BOT_USER", "Example@cache")
    monkeypatch.setenv("BOT_PASSWORD", "wrong")
    wiki.bot_login = ("Example@cache", PASSWORD)
    target = Target(name="fake", api="https://fake.invalid/w/api.php", namespaces={"item": 120},
                    auth=Auth(method="botpassword", username_env="BOT_USER", password_env="BOT_PASSWORD"),
                    min_interval=0)
    with pytest.raises(ApiError, match="login failed"):
        make_api(target, wiki).userinfo()


def test_user_agent_names_operator_then_tool(target, wiki):
    agent = make_api(target, wiki).session.headers["User-Agent"]
    assert agent.startswith("TestOperatorBot (https://example.net/contact) wikibase-cache/")
    assert "(https://github.com/borgnetzwerk/wikibase-cache) python-requests/" in agent


# ── Setup ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def local_config(monkeypatch, tmp_path):
    path = tmp_path / "config.local.yaml"
    monkeypatch.setattr(cfg, "LOCAL_CONFIG", path)
    original_init = cfg.Config.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.path = path

    monkeypatch.setattr(cfg.Config, "__init__", init)
    return path


def test_nothing_works_before_setup(local_config, tmp_path, capsys):
    assert cli.main(["sync", "fake"]) == 2
    assert cli.main(["get", "fake", "Q1"]) == 2
    assert "setup" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_setup_and_add_target(local_config, tmp_path, monkeypatch, wiki):
    monkeypatch.setattr(requests, "Session", lambda: wiki)
    monkeypatch.setenv("TEST_WIKIBASE_TOKEN", TOKEN)
    root = tmp_path / "data"
    assert cli.main(["setup", "--operator-name", "TestOperatorBot", "--operator-contact", "https://example.net",
                     "--data-root", str(root), "--yes"]) == 0
    assert cli.main(["add-target", "mywiki", "--api", "https://fake.invalid/w/api.php", "--auth", "oauth2",
                     "--token-env", "TEST_WIKIBASE_TOKEN", "--full-sync", "--yes"]) == 0
    config = cfg.load(local_config)
    target = config.target("mywiki")
    assert target.namespaces == {"item": 120, "property": 122}
    assert target.auth.account == "ExampleBot"
    assert TOKEN not in local_config.read_text(encoding="utf-8")
    assert root.exists() and config.target_dir("mywiki") == root / "mywiki"


def test_add_target_with_bot_password_records_account(local_config, tmp_path, monkeypatch, wiki):
    monkeypatch.setattr(requests, "Session", lambda: wiki)
    monkeypatch.setenv("BOT_USER", "Example@cache")
    monkeypatch.setenv("BOT_PASSWORD", PASSWORD)
    wiki.bot_login = ("Example@cache", PASSWORD)
    cli.main(["setup", "--operator-name", "Op", "--operator-contact", "https://example.net",
              "--data-root", str(tmp_path / "d"), "--yes"])
    assert cli.main(["add-target", "w", "--api", "https://fake.invalid/w/api.php", "--auth", "botpassword",
                     "--username-env", "BOT_USER", "--password-env", "BOT_PASSWORD", "--yes"]) == 0
    assert cfg.load(local_config).target("w").auth.account == "ExampleBot"


def test_data_root_must_be_outside_repo():
    with pytest.raises(ConfigError):
        cfg.validate_data_root(str(cfg.REPO_ROOT / "data"))


def test_example_operator_is_refused():
    with pytest.raises(ConfigError):
        cfg.validate_operator("YourNameOrOrganisation", "https://example.org")


def test_missing_config_is_not_set_up(tmp_path):
    with pytest.raises(NotSetUp):
        cfg.load(tmp_path / "config.local.yaml")
