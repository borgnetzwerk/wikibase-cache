# Changelog

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versions: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- README with purpose, operator identification and data location.
- Operator template (`operator.example.yaml`); the local `operator.yaml` is ignored by Git.
- Related work: the tools we compared this project with (`docs/related_work.md`).
- Glossary of the terms used, including the fetch modes taken over from speaker-mining (`docs/glossary.md`).
- SPARQL corpus (`queries/`), every query tested with checksum and example output: properties of the instances of a class (podcast episode, podcast show, video recording; with a subclass variant), instance counts (with a ceiling for large classes), superclasses and subclass trees, a sample variant for large classes, classes, medium and form of the items carrying a property, classes of the items linking to a website.
- Licensing: MIT for code and queries, CC BY 4.0 for documentation, following the REUSE Specification; contribution guide.
- Required setup (`setup`, `add-target`): operator, data root and targets are asked for, shown and saved to `config.local.yaml` (never committed); the server reports entity namespaces and the account of the credentials. Nothing is fetched or written before the setup.
- Login per target: none, OAuth 2.0 access token or bot password, secrets only from environment variables.
- `sync` for small wikis: lists every entity with its revision and fetches only what is missing or changed, in runs that end cleanly on a time or request budget, Ctrl+C or a STOP file; stops before fetching if the wiki exceeds `full_sync_max_entities`. `get`, `status`, `scan`, `rebuild-index` and `targets` work without network access.
- Local store below the data root: append-only event files, written once and named by machine, plus one derived index per machine, so several machines can share the data root through a sync service.
- Protection against leaked credentials: only entity documents are stored, never whole responses; an event containing a secret, a `Bearer` or `Authorization` header or `debuginfo` is refused.
- Offline tests against an in-memory Wikibase that echoes request headers like a misconfigured real instance (`tests/`).

- Cache-first fetch modes for any target, Wikidata included: `basic_fetch` (labels, descriptions, aliases, P31, P279), `full_fetch` (the whole entity with revision), `fetch_decision` with rules from the calling project and `expand` over several levels; SPARQL answers stored per query. Every run has a request budget and asks before more than `confirm_requests` requests; `--offline` answers from the store only.
- Imports: archives of other tools read in place without copying (`imports/<name>/source.yaml`), first format speaker-mining event store v3.
- `reset` for a Wikibase that was set up anew: the whole store of the target goes into a checked ZIP archive below `_archives/`, the old folder moves next to it and full-sync targets are synced afresh; nothing is deleted. Three questions in a terminal (confirm, a random sum, the target name), with no option to skip them.
- Optional `.env` file for secrets, named in the setup; refused inside the repository or the data root; environment variables take precedence.

### Changed

- The User-Agent names the tool `wikibase-cache` after its repository; the operator, who is the client making the requests, comes first.
- Backoff waits the longer of the server's `Retry-After` and a growing pause, so a lagging Wikidata is not given up on after a few seconds; `add-target` asks without `maxlag`, as a person waits for it.
- PHP notices in front of a JSON answer are detected and cut off for every target, with a warning; no setting needed.

### Removed

- `operator.example.yaml` and `operator.yaml`: the operator is now part of the setup.
