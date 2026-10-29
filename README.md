# wikibase-cache

An interface to Wikidata and other Wikibase instances that does not burden their servers: it answers from a long-lived local store first and fetches only what is missing, so results can be reused for years and by many projects.

**Status:** early. Implemented: setup, cache-first `basic_fetch`, `full_fetch`, `fetch_decision`/`expand` and SPARQL for any Wikibase including Wikidata, a complete sync for small wikis, and archives of other tools read in place (speaker-mining), cache-first search, and a local endpoint that answers like `api.php` for entities and search (`serve`). Not yet: incoming links, class hierarchies and the other analyses speaker-mining builds on top of its fetches.

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
python -m wikibase_cache add-target wikidata --api https://www.wikidata.org/w/api.php --sparql https://query.wikidata.org/sparql --languages de,en,mul
python -m wikibase_cache add-target mywiki --api https://mywiki.example.org/w/api.php --auth oauth2 --token-env MYWIKI_TOKEN --full-sync
python -m wikibase_cache add-target otherwiki --api https://otherwiki.example.org/w/api.php --auth botpassword --username-env OTHERWIKI_USER --password-env OTHERWIKI_PASSWORD
```

`add-target` asks the server which namespaces hold items, properties and lexemes and, with credentials, which account they belong to, and shows both before saving. Login methods:

- `none`: read without login.
- `oauth2`: an access token of an [OAuth 2.0 owner-only consumer](https://www.mediawiki.org/wiki/OAuth/Owner-only_consumers), read from the named environment variable.
- `botpassword`: a [bot password](https://www.mediawiki.org/wiki/Manual:Bot_passwords) (`User@BotName` and password), read from the two named environment variables.

The configuration holds only the names of the environment variables, never the secrets. If setting environment variables is inconvenient (Linux, macOS, containers, several wikis), `setup --env-file PATH` names a `.env` file (`NAME=value` lines) to read them from. The file must lie outside this repository, where it could be committed, and outside the data root, which a sync service may share; a variable set in the environment takes precedence over the file. Before each run the tool checks that the credentials still belong to the account recorded at `add-target`.

Everything you set up lands in `config.local.yaml` (never committed); [config.example.yaml](config.example.yaml) shows its form. `python -m wikibase_cache targets` shows the current configuration.

The User-Agent of every request reads:

```
<operator name> (<operator contact>) wikibase-cache/<version>+<commit> (https://github.com/borgnetzwerk/wikibase-cache) python-requests/<version>
```

## Usage

```
python -m wikibase_cache fetch <target> Q1 Q5     # basic_fetch, cache-first (network only for what is missing)
python -m wikibase_cache fetch <target> Q5 --full # full_fetch, cache-first
python -m wikibase_cache expand <target> Q5 --rules rules.yaml --depth 2
python -m wikibase_cache sparql <target> query.rq # SPARQL, cache-first, prints the JSON result
python -m wikibase_cache sync <target>            # small wikis: fetch every entity that is missing or changed
python -m wikibase_cache serve <target>           # local /w/api.php on 127.0.0.1:8792 for tools that speak the API
python -m wikibase_cache get <target> Q5          # one entity from the store, as JSON (no network)
python -m wikibase_cache status <target>          # what the store holds, last runs
python -m wikibase_cache scan <target>            # check the stored data for secrets and echoed headers
python -m pytest tests                            # offline tests
```

From Python:

```python
from wikibase_cache.fetch import Cache, Rules
with Cache.open("wikidata", confirm=lambda message: True) as cache:
    items = cache.basic_fetch(["Q42", "Q1"])        # {id: entity}
    douglas = cache.full_fetch(["Q42"])["Q42"]
    rows = cache.sparql("SELECT ?x WHERE { ?x wdt:P31 wd:Q5 } LIMIT 3")
```

**Fetch modes** (from [speaker-mining](https://github.com/borgnetzwerk/speaker-mining), see the [glossary](docs/glossary.md)):

- `basic_fetch` keeps labels, descriptions and aliases in the target's languages and, of the claims, only *instance of* (P31) and *subclass of* (P279). It is answered by any stored version of the entity.
- `full_fetch` keeps the whole entity document as the server sent it, including all claims, sitelinks and the revision ID. It is answered only by a stored full version.
- Both are batched, 50 entities per request, and fetch nothing that is already stored unless `--refresh` is given.
- `fetch_decision` decides which entities a fully fetched entity points to are fetched next: a rules file maps properties to `basic`, `full` or `skip` (`follow: {P31: basic, P50: full}`, `default: skip`). `expand` applies it level by level from the seeds.
- `sparql` stores each answer with the query; the same query on the same endpoint is answered from the store.
- `search` (wbsearchentities) stores the result of each search with its parameters; the same search is answered from the store.
- `serve` answers `wbgetentities` (as `full_fetch`) and `wbsearchentities` (as `search`) like the target's `api.php`, so an existing tool only needs its API URL changed. It listens on 127.0.0.1 only, handles one request at a time with the same pacing, budget (`--max-requests`) and User-Agent as any other run, and refuses all other actions. `--offline` never asks the target; `GET /shutdown` ends it and closes the run.

**Budget and confirmation.** Every run has a request budget (`run_max_requests`, default 200, or `--max-requests`). A run that needs more requests than `confirm_requests` (default 100) asks first; `--yes` skips the question. `--offline` answers from the store only and reports what is missing.

**Large wikis are never listed in full.** On Wikidata, use `fetch`, `expand` and `sparql`. The server's `maxlag` is respected: when Wikidata's replication lags, runs wait with growing pauses and give up cleanly after a few attempts; try again later.

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
- `imports/<name>/`: an archive of another tool, read in place and never changed, so the data exists only once. `source.yaml` names its format and files (`format: speaker-mining-v3`, `files: ["chunks/*.jsonl"]`, plus description and origin). Imported versions count like fetched ones (`import-full` answers `full_fetch`, `import-basic` answers `basic_fetch`) but may lack a revision ID; the archived languages and parts are those of the original tool. Indexing a large import takes a minute once per machine.
- `index/<machine>.json`: this machine's index: for each entity, all stored versions with their place in the files, the latest one and the latest full one; and the stored SPARQL answers. Derived from the event log and the imports; `rebuild-index` recreates it.

**Several machines can share one data root** through a sync service such as Nextcloud or Syncthing. No file is ever written by two machines: event files carry the machine ID that the setup generated, each machine keeps its own index, and a file is complete before it gets its final name (other machines ignore `.partial` files). When a machine opens the store, it reads the event files of other machines that it does not know yet, so an entity one machine has fetched is not fetched again by another once the sync service has delivered the file. If two machines fetch the same revision before that, both events are kept and the revision counts once.

## License

Code and queries: MIT ([LICENSE](LICENSE)). Documentation: CC BY 4.0 ([LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt)). The license of each file is declared in [REUSE.toml](REUSE.toml), following the [REUSE Specification](https://reuse.software/spec-3.3/). Copyright: BorgNetzWerk e.V. (BNW). How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md).
