# Contributing

Thank you for your interest in wikibase-cache! This tool reads from Wikidata and other Wikibase instances and keeps what it has read, so that the same data does not have to be fetched twice.

## Ways of contributing

**Do you have a question?** Open an [issue](https://github.com/borgnetzwerk/wikibase-cache/issues).

**Did you find a bug or something unclear in the documentation?** Open an issue, or fix it directly in a pull request.

**Do you want to add a SPARQL query to the corpus?** Add one Markdown file to `queries/`, following the existing ones: a header with the question and the endpoint, the query in a `sparql` code block, a short explanation. Only queries that have been run belong in the corpus: run yours once and fill in `last_run`, `result_rows`, `result_checksum` (SHA-256 of the raw response) and `runtime`, and add an excerpt of the result under *Example output*. The full result is not committed.

**Do you want to propose a larger change?** Open an issue first, so it can be discussed.

## Running it yourself

Run `python -m wikibase_cache setup` and enter your own name and contact (see the README, Setup). You are responsible for the requests you make; every request identifies you. Keep within the rules of the services you query (see the README and [docs/related_work.md](docs/related_work.md)).

## Submitting a change

1. Create a branch for your change.
2. Never commit `config.local.yaml`, tokens, passwords or fetched data.
3. Open a pull request that explains what you changed and why.

## License

By contributing, you agree that your contributions are licensed under the licenses of this repository: MIT for code and queries, CC BY 4.0 for documentation (see [REUSE.toml](REUSE.toml)).
