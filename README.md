# wikibase-cache

An interface to Wikidata and other Wikibase instances that does not burden their servers: it answers from a long-lived local store first and fetches only what is missing, so results can be reused for years and by many projects.

**Status:** early. Small Wikibase instances can be synced completely (with or without login) and read from the local store. Targeted fetches for large wikis such as Wikidata, SPARQL, `basic_fetch`, `full_fetch` and `fetch_decision` are not implemented yet.

## Setup (required)

Nothing is fetched or written before you have set the tool up. Requires Python 3.11 or later with `requests` and `PyYAML` ([requirements.txt](requirements.txt)); run all commands from the repository root.

```
python -m wikibase_cache setup
```

asks for, and shows you before saving:

- **Operator name and contact.** Whoever runs this tool is responsible for its requests and is named first in every request's User-Agent. Use a URL as contact if you can. Wikimedia recommends that automated clients include "bot" in their name.
- **Data root.** An absolute folder outside this repository, where all fetched data goes; it can grow to gigabytes. One subfolder per target is created below it. Common choices: `%LOCALAPPDATA%/wikibase-cache` on Windows, `~/.local/share/wikibase-cache` on Linux and macOS, or a folder of a sync service shared by several machines (see [Where the data lives](#where-the-data-lives)).

Then add each wiki you want to read:

```
python -m wikibase_cache add-target wikidata --api https://www.wikidata.org/w/api.php
python -m wikibase_cache add-target mywiki --api https://mywiki.example.org/w/api.php --auth oauth2 --token-env MYWIKI_TOKEN --full-sync
python -m wikibase_cache add-target otherwiki --api https://otherwiki.example.org/w/api.php --auth botpassword --username-env OTHERWIKI_USER --password-env OTHERWIKI_PASSWORD
```

`add-target` asks the server which namespaces hold items, properties and lexemes and, with credentials, which account they belong to, and shows both before saving. Login methods:

- `none`: read without login.
- `oauth2`: an access token of an [OAuth 2.0 owner-only consumer](https://www.mediawiki.org/wiki/OAuth/Owner-only_consumers), read from the named environment variable.
- `botpassword`: a [bot password](https://www.mediawiki.org/wiki/Manual:Bot_passwords) (`User@BotName` and password), read from the two named environment variables.

Secrets are never stored in a file; the configuration holds only the names of the environment variables. Before each run the tool checks that the credentials still belong to the account recorded at `add-target`.

Everything you set up lands in `config.local.yaml` (never committed); [config.example.yaml](config.example.yaml) shows its form. `python -m wikibase_cache targets` shows the current configuration.

The User-Agent of every request reads:

```
<operator name> (<operator contact>) wikibase-cache/<version>+<commit> (https://github.com/borgnetzwerk/wikibase-cache) python-requests/<version>
```

## Usage

```
python -m wikibase_cache sync <target>            # fetch what is missing or changed (network)
python -m wikibase_cache get <target> Q5          # one entity from the store, as JSON (no network)
python -m wikibase_cache status <target>          # what the store holds, last runs
python -m wikibase_cache scan <target>            # check the stored data for secrets and echoed headers
python -m pytest tests                            # offline tests
```

From Python: `from wikibase_cache import open_store; open_store("mywiki").get("Q5")`.

**How `sync` works.** It is meant for small wikis and only allowed for targets added with `--full-sync`. It first lists every entity with its current revision ID (one request per page of up to 500 entities), then fetches, in batches of 50, only the entities that are missing from the store or whose revision has changed. A second run on an unchanged wiki therefore makes only the listing requests. If the listing exceeds `full_sync_max_entities` (default 50,000), the run stops before fetching anything. Each run ends cleanly after its time or request budget (`run_max_seconds`, `run_max_requests`, or `--max-seconds`, `--max-requests`), on Ctrl+C, or when a non-empty file named `STOP` exists in the target's data folder; running the same command again continues where it stopped.

**Secrets never reach the disk.** Some instances repeat the request headers, including credentials, in the `debuginfo` part of every response. The tool stores entity documents only, never whole responses, and refuses to write any event that contains a secret, `Bearer `, `Authorization:` or `debuginfo`. `scan` checks the stored files for the same markers afterwards.

## What it is meant to do

- Talk to it like to Wikidata (entity lookups through the [Wikibase API](https://www.wikidata.org/wiki/Wikidata:Data_access), SPARQL through the [Wikidata Query Service](https://query.wikidata.org/)); it answers from the local store and fetches only on a miss (*cache-first*).
- Keep every revision it has seen, in an append-only event log, so results stay reproducible.
- Offer the fetch modes of our predecessor [speaker-mining](https://github.com/borgnetzwerk/speaker-mining) alongside raw queries: `basic_fetch` (labels, descriptions, aliases, *instance of* and *subclass of*, batched for many entities), `full_fetch` (all claims of one entity) and `fetch_decision` (which referenced entities to fetch next, by rules the calling project sets).
- Keep a corpus of documented SPARQL queries in [`queries/`](queries/), one Markdown file per question.
- Follow the [Wikimedia rules for automated access](#rules-this-tool-follows-and-where-they-come-from) by default: requests in series and batched ([API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)), gzip and backoff on 429 and 503 ([Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)), [`maxlag`](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter), and an informative User-Agent ([User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)).
- Read only. Writing to a Wikibase is a separate tool.

Terms: [docs/glossary.md](docs/glossary.md). Background and the tools we compared it with: [docs/related_work.md](docs/related_work.md).

## Rules this tool follows, and where they come from

- [Wikimedia Foundation User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy): identify the client and give a contact; never a generic or browser User-Agent.
- [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy): consider dumps before live requests, gzip, respect 429 and `Retry-After`, limits for concurrency and request rate.
- [Wikimedia APIs/Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits): limits per client type; a compliant User-Agent without login gets 200 requests per minute.
- [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette): requests in series, batching, `maxlag`, backoff.
- [Wikidata Query Service user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual): 60-second limit per query, processing-time and error limits per client; the service is moving to a new backend in 2026/27.
- [Wikidata:Mass-editing policy](https://www.wikidata.org/wiki/Wikidata:Mass-editing_policy): applies as soon as anyone writes to Wikidata at scale (this tool does not write).

## Where the data lives

Fetched data is kept below the data root you chose in the setup, outside this repository, so the repository does not change when you fetch. Each target has its own folder there:

- `events/<date>_<machine>_<number>.jsonl`: the event log, one file per run, one event per line. While a run is in progress, its file carries the suffix `.partial`; when the run ends it is renamed and never changed again. Events: `run_started`, `entity_revision` (the entity document exactly as the server sent it, with its revision ID), `entity_missing`, `entity_unlisted` (no longer listed on the server; the last revision stays readable), `run_finished`. Every event has a UTC time and the ID of its run.
- `index/<machine>.json`: this machine's index: for each entity, its latest revision and where that event is. Derived from the event log; `rebuild-index` recreates it.

**Several machines can share one data root** through a sync service such as Nextcloud or Syncthing. No file is ever written by two machines: event files carry the machine ID that the setup generated, each machine keeps its own index, and a file is complete before it gets its final name (other machines ignore `.partial` files). When a machine opens the store, it reads the event files of other machines that it does not know yet, so an entity one machine has fetched is not fetched again by another once the sync service has delivered the file. If two machines fetch the same revision before that, both events are kept and the revision counts once.

## License

Code and queries: MIT ([LICENSE](LICENSE)). Documentation: CC BY 4.0 ([LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt)). The license of each file is declared in [REUSE.toml](REUSE.toml), following the [REUSE Specification](https://reuse.software/spec-3.3/). Copyright: BorgNetzWerk e.V. (BNW). How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md).
