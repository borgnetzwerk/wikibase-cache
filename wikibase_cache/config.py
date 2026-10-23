"""Configuration. Everything that differs between operators lives in one local file, config.local.yaml, which is
never committed and is written by `setup` and `add-target`. Without it the tool fetches and writes nothing."""
from __future__ import annotations

import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_URL = "https://github.com/borgnetzwerk/wikibase-cache"
LOCAL_CONFIG = REPO_ROOT / "config.local.yaml"

# Request behaviour; a target may override any of these in config.local.yaml
DEFAULTS = {
    "maxlag": 5,             # https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
    "retries": 5,            # on 429/502/503/504, maxlag, ratelimited and dropped connections
    "backoff_base": 2,       # seconds; backoff_base * 2^attempt unless the server sends Retry-After
    "timeout": 60,           # seconds per request
    "min_interval": 1.0,     # seconds between two requests
    "batch_size": 50,        # wbgetentities takes at most 50 IDs per request
    "full_sync": False,      # list and fetch every entity; only for small wikis
    "full_sync_max_entities": 50000,
    "run_max_seconds": 300,
    "run_max_requests": 200,
}
AUTH_METHODS = ("none", "oauth2", "botpassword")


class ConfigError(Exception):
    pass


class NotSetUp(ConfigError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what} Run `python -m wikibase_cache setup` first (see README, Setup).")


@dataclass
class Auth:
    method: str = "none"
    token_env: str | None = None      # oauth2: environment variable holding the access token
    username_env: str | None = None   # botpassword: environment variable holding "User@BotName"
    password_env: str | None = None   # botpassword: environment variable holding the bot password
    account: str | None = None        # account the credentials belonged to at add-target; checked before each run

    def secret(self, name: str | None) -> str:
        value = os.environ.get(name or "", "").strip()
        if not value:
            raise ConfigError(f"Environment variable {name} is not set.")
        return value


@dataclass
class Target:
    name: str
    api: str
    namespaces: dict[str, int]
    auth: Auth = field(default_factory=Auth)
    maxlag: int = DEFAULTS["maxlag"]
    retries: int = DEFAULTS["retries"]
    backoff_base: float = DEFAULTS["backoff_base"]
    timeout: float = DEFAULTS["timeout"]
    min_interval: float = DEFAULTS["min_interval"]
    batch_size: int = DEFAULTS["batch_size"]
    full_sync: bool = DEFAULTS["full_sync"]
    full_sync_max_entities: int = DEFAULTS["full_sync_max_entities"]
    run_max_seconds: int = DEFAULTS["run_max_seconds"]
    run_max_requests: int = DEFAULTS["run_max_requests"]

    def to_yaml(self) -> dict:
        data = asdict(self)
        data.pop("name")
        data["auth"] = {k: v for k, v in data["auth"].items() if v is not None}
        return {k: v for k, v in data.items() if k in ("api", "namespaces", "auth") or v != DEFAULTS.get(k)}


@dataclass
class Operator:
    name: str
    contact: str


@dataclass
class Config:
    operator: Operator
    data_root: Path
    machine_id: str
    targets: dict[str, Target]
    path: Path = LOCAL_CONFIG

    def target(self, name: str) -> Target:
        if name not in self.targets:
            known = ", ".join(sorted(self.targets)) or "none yet"
            raise ConfigError(f"Unknown target {name!r} (configured: {known}). Add it with `add-target`.")
        return self.targets[name]

    def target_dir(self, name: str) -> Path:
        return self.data_root / self.target(name).name

    def save(self) -> None:
        data = {
            "operator": asdict(self.operator),
            "data_root": str(self.data_root),
            "machine_id": self.machine_id,
            "targets": {name: target.to_yaml() for name, target in sorted(self.targets.items())},
        }
        header = ("# wikibase-cache local configuration, written by `setup` and `add-target`. Never committed.\n"
                  "# Secrets are not stored here, only the names of the environment variables that hold them.\n")
        self.path.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                             encoding="utf-8", newline="\n")


def validate_operator(name: str, contact: str) -> Operator:
    name, contact = name.strip(), contact.strip()
    if not name or not contact:
        raise ConfigError("Operator name and contact are required.")
    if " " in name:
        raise ConfigError("Operator name must not contain spaces.")
    if name == "YourNameOrOrganisation" or contact == "https://example.org":
        raise ConfigError("Enter your own operator name and contact, not the example values.")
    return Operator(name, contact)


def validate_data_root(value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value.strip())))
    if not path.is_absolute():
        raise ConfigError(f"The data root must be an absolute path, got {value!r}.")
    if path.resolve().is_relative_to(REPO_ROOT):
        raise ConfigError("The data root must lie outside this repository.")
    return path


def new_machine_id() -> str:
    """Random, stable per clone; names this machine's event files so two machines never write the same file."""
    return secrets.token_hex(3)


def load(path: Path | None = None) -> Config:
    path = path or LOCAL_CONFIG
    if not path.exists():
        raise NotSetUp(f"{path.name} does not exist.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        operator = validate_operator(raw["operator"]["name"], raw["operator"]["contact"])
        data_root = validate_data_root(raw["data_root"])
        machine_id = str(raw["machine_id"])
    except (KeyError, TypeError) as error:
        raise NotSetUp(f"{path.name} is incomplete ({error}).") from None
    targets = {}
    for name, values in (raw.get("targets") or {}).items():
        values = dict(values)
        auth = Auth(**(values.pop("auth", None) or {}))
        if auth.method not in AUTH_METHODS:
            raise ConfigError(f"Target {name}: unknown auth method {auth.method!r} ({', '.join(AUTH_METHODS)}).")
        targets[name] = Target(name=name, auth=auth, **values)
    return Config(operator, data_root, machine_id, targets, path)
