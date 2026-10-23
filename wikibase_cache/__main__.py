"""Command line.

Setup (required once per clone; nothing is fetched or written before):
    python -m wikibase_cache setup [--operator-name N] [--operator-contact URL] [--data-root PATH]
        [--env-file PATH | --no-env-file] [--yes]
    python -m wikibase_cache add-target <name> --api URL [--sparql URL] [--languages de,en]
        [--auth none|oauth2|botpassword] [--token-env VAR] [--username-env VAR] [--password-env VAR]
        [--full-sync] [--yes]
        Asks the server for its entity namespaces and, with credentials, for the account they belong to (network).
    python -m wikibase_cache targets
        Show the configuration.

Use:
    python -m wikibase_cache fetch <target> <ID>... [--full] [--refresh] [--offline] [--max-requests N] [--yes]
        basic_fetch (or full_fetch) cache-first; fetches only what is missing (network on a miss).
    python -m wikibase_cache expand <target> <ID>... --rules RULES.yaml [--depth N] [--max-requests N] [--yes]
        full_fetch the seeds, then what fetch_decision names (rules: {follow: {P31: basic, P50: full}, default: skip}).
    python -m wikibase_cache sparql <target> <QUERY.rq> [--refresh] [--offline] [--yes]
        Run a SPARQL query cache-first and print the JSON result.
    python -m wikibase_cache sync <target> [--kinds item,property] [--max-seconds N] [--max-requests N]
        Fetch every entity that is missing from the store or has changed (network; full-sync targets only).
    python -m wikibase_cache get <target> <ID> [--revision N]      one entity from the store (no network)
    python -m wikibase_cache status <target>                       store contents, last runs (no network)
    python -m wikibase_cache scan <target>                         check stored data for secrets (no network)
    python -m wikibase_cache rebuild-index <target>                derive this machine's index again (no network)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import config as cfg
from .api import ApiError
from .config import AUTH_METHODS, Auth, Config, ConfigError, Target
from .store import LeakError, Store

TARGET_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.command == "setup":
            return setup(args)
        config = cfg.load()
        if args.command == "add-target":
            return add_target(config, args)
        if args.command == "targets":
            return show(config)
        target = config.target(args.target)
        root = config.target_dir(target.name)
        if args.command == "sync":
            return run_sync(config, target, root, args)
        if args.command in ("fetch", "expand", "sparql"):
            return run_fetch(config, target, args)
        store = Store(root, config.machine_id)
        if args.command == "get":
            entity = store.get(args.id, args.revision)
            if entity is None:
                print(f"{args.id} is not in the store of {target.name}.", file=sys.stderr)
                return 1
            print(json.dumps(entity, ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            return status(store, root)
        if args.command == "scan":
            return run_scan(target, root)
        store.rebuild_index()
        print(f"Index rebuilt: {store.index_path}")
        return 0
    except ConfigError as error:
        print(f"Configuration: {error}", file=sys.stderr)
        return 2
    except ApiError as error:
        print(f"Server: {error}", file=sys.stderr)
        return 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m wikibase_cache", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--operator-name")
    p.add_argument("--operator-contact")
    p.add_argument("--data-root")
    p.add_argument("--env-file", help="optional .env file with secrets, outside the repository and the data root")
    p.add_argument("--no-env-file", action="store_true", help="remove a configured .env file")
    p.add_argument("--yes", action="store_true", help="save without asking for confirmation")
    p = sub.add_parser("add-target")
    p.add_argument("name")
    p.add_argument("--api", required=True, help="Action API URL, e.g. https://www.wikidata.org/w/api.php")
    p.add_argument("--sparql", help="SPARQL endpoint, e.g. https://query.wikidata.org/sparql")
    p.add_argument("--languages", default="en", help="languages for basic_fetch, comma-separated (default: en)")
    p.add_argument("--auth", choices=AUTH_METHODS, default="none")
    p.add_argument("--token-env", help="oauth2: environment variable with the access token")
    p.add_argument("--username-env", help="botpassword: environment variable with User@BotName")
    p.add_argument("--password-env", help="botpassword: environment variable with the bot password")
    p.add_argument("--full-sync", action="store_true", help="allow listing and fetching every entity (small wikis)")
    p.add_argument("--yes", action="store_true")
    sub.add_parser("targets")
    p = sub.add_parser("fetch")
    p.add_argument("target")
    p.add_argument("ids", nargs="+")
    p.add_argument("--full", action="store_true")
    p.add_argument("--refresh", action="store_true", help="fetch again even if stored")
    p.add_argument("--offline", action="store_true", help="answer from the store only")
    p.add_argument("--max-requests", type=int)
    p.add_argument("--yes", action="store_true", help="do not ask before larger runs")
    p = sub.add_parser("expand")
    p.add_argument("target")
    p.add_argument("ids", nargs="+")
    p.add_argument("--rules", required=True, type=Path)
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--max-requests", type=int)
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("sparql")
    p.add_argument("target")
    p.add_argument("query", type=Path)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("sync")
    p.add_argument("target")
    p.add_argument("--kinds", help="comma-separated, default: all entity namespaces of the target")
    p.add_argument("--max-seconds", type=float)
    p.add_argument("--max-requests", type=int)
    p = sub.add_parser("get")
    p.add_argument("target")
    p.add_argument("id")
    p.add_argument("--revision", type=int)
    for name in ("status", "scan", "rebuild-index"):
        sub.add_parser(name).add_argument("target")
    return parser


def _ask(prompt: str, given: str | None, suggestion: str | None = None) -> str:
    if given:
        return given
    hint = f" [{suggestion}]" if suggestion else ""
    answer = input(f"{prompt}{hint}: ").strip()
    return answer or (suggestion or "")


def _confirm(summary: str, yes: bool) -> bool:
    print(summary)
    if yes:
        return True
    return input("Save? [y/N] ").strip().lower() in ("y", "yes")


def setup(args) -> int:
    try:
        existing = cfg.load()
    except ConfigError:
        existing = None
    print("Setup of wikibase-cache. Every request names you as the operator (User-Agent); fetched data goes to the\n"
          "data root, which can grow to gigabytes. Nothing is fetched or written before this is saved.\n"
          "Wikimedia recommends that automated clients include the word 'bot' in their name.")
    old_operator = existing.operator if existing else None
    name = _ask("Operator name (no spaces)", args.operator_name, old_operator.name if old_operator else None)
    contact = _ask("Operator contact (URL preferred)", args.operator_contact,
                   old_operator.contact if old_operator else None)
    operator = cfg.validate_operator(name, contact)
    print("Data root: an absolute folder outside this repository; one subfolder per target is created below it.\n"
          "Example: %LOCALAPPDATA%/wikibase-cache (Windows) or ~/.local/share/wikibase-cache (Linux, macOS).")
    root_text = _ask("Data root", args.data_root, str(existing.data_root) if existing else None)
    data_root = cfg.validate_data_root(root_text)
    env_file = existing.env_file if existing else None
    if args.no_env_file:
        env_file = None
    elif args.env_file:
        env_file = cfg.validate_env_file(args.env_file, data_root)
    config = Config(operator, data_root, existing.machine_id if existing else cfg.new_machine_id(),
                    existing.targets if existing else {}, env_file=env_file)
    exists = "exists" if data_root.exists() else "will be created"
    summary = (f"\nOperator:   {operator.name} ({operator.contact})\nData root:  {data_root} ({exists})\n"
               f"Machine ID: {config.machine_id}\nEnv file:   {env_file or 'none (secrets from environment variables)'}\n"
               f"Targets:    {', '.join(sorted(config.targets)) or 'none yet'}\n"
               f"File:       {config.path}")
    if not _confirm(summary, args.yes):
        print("Nothing saved.")
        return 1
    data_root.mkdir(parents=True, exist_ok=True)
    config.save()
    print(f"Saved {config.path.name}. Next: add-target.")
    return 0


def add_target(config: Config, args) -> int:
    from .api import Api

    if not TARGET_NAME.match(args.name):
        raise ConfigError("Target names use lowercase letters, digits, '-' and '_' (they become folder names).")
    auth = Auth(method=args.auth, token_env=args.token_env, username_env=args.username_env,
                password_env=args.password_env)
    if auth.method == "oauth2" and not auth.token_env:
        raise ConfigError("--auth oauth2 needs --token-env.")
    if auth.method == "botpassword" and not (auth.username_env and auth.password_env):
        raise ConfigError("--auth botpassword needs --username-env and --password-env.")
    auth.env_file_values = cfg.read_env_file(config.env_file) if config.env_file else {}
    languages = [code.strip() for code in args.languages.split(",") if code.strip()]
    target = Target(name=args.name, api=args.api, namespaces={}, auth=auth, full_sync=args.full_sync,
                    sparql=args.sparql, languages=languages)
    api = Api(target, config.operator)
    api.use_maxlag = False  # one or two requests while a person waits
    print(f"Asking {args.api} for its entity namespaces ...")
    target.namespaces = api.entity_namespaces()
    if not target.namespaces:
        raise ConfigError("The server reports no Wikibase entity namespaces; is this a Wikibase?")
    if auth.method != "none":
        info = api.userinfo()
        if info.get("anon"):
            raise ConfigError("The credentials were not accepted: the server treats the requests as anonymous.")
        auth.account = info.get("name")
    replaced = " (replaces the existing target)" if args.name in config.targets else ""
    summary = (f"\nTarget:     {args.name}{replaced}\nAPI:        {args.api}\n"
               f"Namespaces: {', '.join(f'{k} {v}' for k, v in target.namespaces.items())}\n"
               f"SPARQL:     {args.sparql or 'none'}\nLanguages:  {', '.join(languages)}\n"
               f"Login:      {auth.method}" + (f", account {auth.account}" if auth.account else "") +
               f"\nFull sync:  {'allowed' if target.full_sync else 'no'}\n"
               f"Data:       {config.data_root / args.name}")
    if not _confirm(summary, args.yes):
        print("Nothing saved.")
        return 1
    config.targets[args.name] = target
    config.save()
    print(f"Saved. {api.requests} requests made.")
    return 0


def show(config: Config) -> int:
    print(f"Operator:   {config.operator.name} ({config.operator.contact})")
    print(f"Data root:  {config.data_root}")
    print(f"Machine ID: {config.machine_id}")
    print(f"Env file:   {config.env_file or 'none'}")
    for name, target in sorted(config.targets.items()):
        login = target.auth.method + (f" ({target.auth.account})" if target.auth.account else "")
        print(f"  {name}: {target.api}, SPARQL {target.sparql or 'none'}, namespaces {target.namespaces}, "
              f"languages {','.join(target.languages)}, login {login}, full sync {'yes' if target.full_sync else 'no'}")
    return 0


def run_sync(config: Config, target: Target, root: Path, args) -> int:
    from .api import Api
    from .sync import sync

    api = Api(target, config.operator)
    store = Store(root, config.machine_id, secrets=api.secrets)
    kinds = args.kinds.split(",") if args.kinds else None
    print(f"Sync {target.name} into {root}")
    try:
        result = sync(api, store, kinds, args.max_seconds, args.max_requests)
    except LeakError as error:
        print(f"ABORTED: {error} Nothing of that event was written.", file=sys.stderr)
        return 3
    except PermissionError as error:
        print(f"ABORTED: {error}", file=sys.stderr)
        return 3
    state = "complete" if result.complete else f"interrupted ({result.reason}); run the same command to continue"
    print(f"{result.listed} listed, {result.fetched} fetched, {result.missing} missing, {result.unlisted} no longer "
          f"listed, {result.requests} requests: {state}")
    return 0 if result.complete else 4


def run_fetch(config: Config, target: Target, args) -> int:
    import yaml

    from .fetch import BudgetExceeded, Cache, NotConfirmed, Offline, Rules

    if getattr(args, "yes", False):
        confirm = lambda message: True  # noqa: E731
    else:
        confirm = lambda message: input(message + " [y/N] ").strip().lower() in ("y", "yes")  # noqa: E731
    cache = Cache(config, target, offline=getattr(args, "offline", False),
                  max_requests=getattr(args, "max_requests", None), confirm=confirm)
    try:
        with cache:
            if args.command == "fetch":
                mode = "full" if args.full else "basic"
                missing = len(cache.missing(args.ids, mode))
                found = cache.entities(args.ids, mode, refresh=args.refresh)
                print(f"{len(found)} of {len(set(args.ids))} entities available ({mode}); {missing} were missing, "
                      f"{cache.fetched} fetched, {cache.requests} requests")
            elif args.command == "expand":
                rules = Rules.from_dict(yaml.safe_load(args.rules.read_text(encoding="utf-8")) or {})
                reached = cache.expand(args.ids, rules, args.depth)
                full = sum(1 for m in reached.values() if m == "full")
                print(f"{len(reached)} entities reached ({full} full, {len(reached) - full} basic); "
                      f"{cache.fetched} fetched, {cache.requests} requests")
            else:
                result = cache.sparql(args.query.read_text(encoding="utf-8"), refresh=args.refresh)
                print(json.dumps(result, ensure_ascii=False, indent=2))
    except (BudgetExceeded, NotConfirmed, Offline) as error:
        print(f"Not fetched: {error}", file=sys.stderr)
        return 4
    except LeakError as error:
        print(f"ABORTED: {error} Nothing of that event was written.", file=sys.stderr)
        return 3
    return 0


def status(store: Store, root: Path) -> int:
    entities = store.index["entities"]
    print(f"Store: {root}")
    scopes: dict[str, int] = {}
    for entry in entities.values():
        scope = entry["latest"]["scope"] if entry.get("latest") else "none"
        scopes[scope] = scopes.get(scope, 0) + 1
    print(f"{len(entities)} entities (latest version: "
          f"{', '.join(f'{k} {v}' for k, v in sorted(scopes.items())) or 'none'}), "
          f"{len(store.index['sparql'])} SPARQL answers, {len(store.event_files())} event files (all machines)")
    for source in store.import_sources():
        files = source.files()
        size = sum(f.stat().st_size for f in files) // 1_000_000
        print(f"  import {source.folder.name}: {source.format}, {len(files)} files, {size} MB")
    finished = [e for e in store.iter_events() if e.get("type") == "run_finished"]
    for event in finished[-5:]:
        state = "complete" if event["complete"] else f"interrupted ({event['reason']})"
        print(f"  {event['time']}: {event['requests']} requests, {event['fetched']} fetched, {state}")
    return 0


def run_scan(target: Target, root: Path) -> int:
    from .scan import scan

    auth, secrets = target.auth, []
    for name in (auth.token_env, auth.password_env):
        if name:
            try:
                secrets.append(auth.secret(name))
            except ConfigError:
                print(f"{name} not set: scanning for echoed headers only, not for that secret.")
    findings = scan(root, secrets)
    if not findings:
        print(f"Clean: no secret, Bearer, Authorization or debuginfo in {root}")
        return 0
    for path, hits in findings.items():
        print(f"FOUND in {path}: {', '.join(f'{k} x{v}' for k, v in hits.items())}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
