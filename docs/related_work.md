# Related work

What we looked at before building this tool, and what we take from each. Checked on 2026-10-11; descriptions come from each project's own documentation or from search results, as marked.

**Status:** a first survey, made before any code was written. Each entry still has to be checked in depth before we rely on it.

## The gap

We want an interface in front of Wikidata and other Wikibase instances that you talk to in the same way as to Wikidata itself (entity lookups, SPARQL). It answers from a local, long-lived store first and fetches only what is missing, keeps every revision it has seen, and identifies its operator to the servers. We did not find a tool that combines a caching layer, a local mirror and revision awareness.

## Libraries for the Wikibase API

| Tool | Language | What it offers | Relation to this project |
|---|---|---|---|
| [Pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot) | Python | Full framework for reading and editing wikis, including Wikidata. Its data-site code calls `wbgetentities` with a per-request expiry, so responses can sit in its request cache (search result, not verified). | Its cache is tied to the framework, so not a base for reading here. For writing (a separate tool), an alternative to WikibaseIntegrator. |
| [WikibaseIntegrator](https://github.com/LeMyst/WikibaseIntegrator) | Python | Read and write entities through the Wikibase API; explicitly points to the Wikimedia User-Agent policy. Not for this tool, which only reads. A candidate for a separate writing tool (curation bot for a Wikibase we operate). |
| [wikidata](https://wikidata.readthedocs.io/) | Python | Client for fetching entities by ID; has a `wikidata.cache` module with cache policies (search result; whether it persists to disk is not verified). | Closest Python counterpart for reading; to be checked in detail. |
| [qwikidata](https://qwikidata.readthedocs.io/) | Python | Pythonic entity classes, linked-data interface, reading JSON dumps. No caching mentioned. | Useful for parsing entities and dumps. |
| [wikibase-api](https://github.com/samuelmeuli/wikibase-api/) | Python | Wrapper around the Wikibase API with authentication. No caching mentioned. | Reference only. |
| [Wikidata Toolkit](https://github.com/Wikidata/Wikidata-Toolkit) | Java | API access and processing of dump files. | Reference for dump processing. |

The list of programming tools that Wikidata maintains itself is [Wikidata:Tools/For programmers](https://www.wikidata.org/wiki/Wikidata:Tools/For_programmers).

## Caches and local mirrors

| Tool | What it offers | Relation to this project |
|---|---|---|
| [tidywikidatar](https://edjnet.r-universe.dev/tidywikidatar/doc/manual.html) (R) | Caches Wikidata queries explicitly to reduce load on Wikidata's servers; SQLite by default, configurable cache folder and other databases ([caching vignette](https://brieger.esalq.usp.br/CRAN/web/packages/tidywikidatar/vignettes/caching.html), search result). Client-side, not revision-aware. | Closest in intent; a model for configuration of the store. |
| [requests-cache](https://requests-cache.readthedocs.io/en/stable/) (Python) | Transparent caching of HTTP responses, several storage backends and expiry rules. Knows nothing about entities or revisions. | Possible lowest layer under our entity store. |
| [QLever](https://github.com/ad-freiburg/qlever) | SPARQL engine able to query all of Wikidata locally from a dump. | Possible later local SPARQL target, given a dump and suitable hardware. |
| [local-wikidata](https://github.com/ndbroadbent/local-wikidata), [wdqs-mini](https://github.com/StrahilPeykov/wdqs-mini) | Small self-hosted Wikidata mirrors (full or a bounded subset). | Shows the demand; not established. |
| [wikidata-entity-store](https://github.com/EdJoPaTo/wikidata-entity-store) | Loads and caches Wikidata entities (TypeScript, last update 2020). | Same idea, small and inactive. |
| [Wikibase-Cache](https://github.com/michal-josef-spacek/Wikibase-Cache) | Cache for Wikibase entities (Perl). | Same idea, different ecosystem. |
| Wikibase itself ([EntityRevisionCache](https://doc.wikimedia.org/Wikibase/REL1_42/php/classWikibase_1_1Lib_1_1Store_1_1EntityRevisionCache.html)) | Server-side cache of the latest revision of an entity, one hour by default; may return stale data. `Special:EntityData` is cached for an hour as well ([T68539](https://phabricator.wikimedia.org/T68539)). | Explains why a client cannot rely on server freshness either. |

## Our own predecessor

[speaker-mining](https://github.com/borgnetzwerk/speaker-mining), a project of ours, built an event-sourced Wikidata store: an append-only event log in chunks with checksums, a learning backoff, and projections, with the fetch modes `basic_fetch`, `full_fetch` and `fetch_decision` ([glossary](glossary.md)). This tool starts from that format and generalises it.

## What we take from this

- No existing tool covers the whole need, so we build a wrapper rather than starting from scratch.
- Our own core: event log and entity store with revisions, the fetch modes `basic_fetch`, `full_fetch` and `fetch_decision`, a budget per run and a clean abort, operator identification.
- Below it: [`requests`](https://requests.readthedocs.io/), optionally [`requests-cache`](https://requests-cache.readthedocs.io/en/stable/) for anything that is not an entity.
- Not part of this tool: for writing (only for the curation bot of a Wikibase we operate), [WikibaseIntegrator](https://github.com/LeMyst/WikibaseIntegrator), to be checked.
- For SPARQL: the public [Wikidata Query Service](https://query.wikidata.org/) with a corpus of documented queries, later optionally [QLever](https://github.com/ad-freiburg/qlever) on a local [dump](https://www.wikidata.org/wiki/Wikidata:Database_download).
