# wikibase-cache

An interface to Wikidata and other Wikibase instances that does not burden their servers: it answers from a long-lived local store first and fetches only what is missing, so results can be reused for years and by many projects.

**Status:** being set up. Nothing here fetches anything yet.

## What it is meant to do

- Talk to it like to Wikidata (entity lookups through the [Wikibase API](https://www.wikidata.org/wiki/Wikidata:Data_access), SPARQL through the [Wikidata Query Service](https://query.wikidata.org/)); it answers from the local store and fetches only on a miss (*cache-first*).
- Keep every revision it has seen, in an append-only event log, so results stay reproducible.
- Offer the fetch modes of our predecessor [speaker-mining](https://github.com/borgnetzwerk/speaker-mining) alongside raw queries: `basic_fetch` (labels, descriptions, aliases, *instance of* and *subclass of*, batched for many entities), `full_fetch` (all claims of one entity) and `fetch_decision` (which referenced entities to fetch next, by rules the calling project sets).
- Keep a corpus of documented SPARQL queries in [`queries/`](queries/), one Markdown file per question.
- Follow the [Wikimedia rules for automated access](#rules-this-tool-follows-and-where-they-come-from) by default: requests in series and batched ([API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)), gzip and backoff on 429 and 503 ([Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)), [`maxlag`](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter), and an informative User-Agent ([User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)).
- Read only. Writing to a Wikibase is a separate tool.
- Optionally authenticate per target ([OAuth](https://www.mediawiki.org/wiki/OAuth/For_Developers) consumer token), for wikis that require login to read.

Terms: [docs/glossary.md](docs/glossary.md). Background and the tools we compared it with: [docs/related_work.md](docs/related_work.md).

## Operator identification (required)

Whoever runs this tool is responsible for its requests and must say so in every request. Copy `operator.example.yaml` to `operator.yaml` and enter your own name and contact (preferably a URL). `operator.yaml` is never committed. Without it, the tool refuses to start. The User-Agent then reads:

```
<your name> (<your contact>) BNWikibaseCacheBot/<version>+<commit> (https://github.com/borgnetzwerk/wikibase-cache) python-requests/<version>
```

## Rules this tool follows, and where they come from

- [Wikimedia Foundation User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy): identify the client and give a contact; never a generic or browser User-Agent.
- [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy): consider dumps before live requests, gzip, respect 429 and `Retry-After`, limits for concurrency and request rate.
- [Wikimedia APIs/Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits): limits per client type; a compliant User-Agent without login gets 200 requests per minute.
- [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette): requests in series, batching, `maxlag`, backoff.
- [Wikidata Query Service user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual): 60-second limit per query, processing-time and error limits per client; the service is moving to a new backend in 2026/27.
- [Wikidata:Mass-editing policy](https://www.wikidata.org/wiki/Wikidata:Mass-editing_policy): applies as soon as anyone writes to Wikidata at scale (this tool does not write).

## Where the data lives

Fetched data is kept outside this repository, so the repository does not change when you fetch. Where exactly is set per machine in a local configuration file, which is not defined yet; like `operator.yaml`, it will never be committed.

## License

Code and queries: MIT ([LICENSE](LICENSE)). Documentation: CC BY 4.0 ([LICENSES/CC-BY-4.0.txt](LICENSES/CC-BY-4.0.txt)). The license of each file is declared in [REUSE.toml](REUSE.toml), following the [REUSE Specification](https://reuse.software/spec-3.3/). Copyright: BorgNetzWerk e.V. (BNW). How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md).
