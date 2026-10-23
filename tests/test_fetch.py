"""Offline tests: .env file for secrets."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_cache import config as cfg  # noqa: E402
from wikibase_cache.config import Auth, Config, ConfigError, Operator, Target  # noqa: E402

OPERATOR = Operator("TestOperatorBot", "https://example.net/contact")


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
