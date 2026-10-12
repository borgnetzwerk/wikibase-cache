# Glossary

The terms used in this repository, each with one meaning. Where a term comes from [speaker-mining](https://github.com/borgnetzwerk/speaker-mining), we keep its meaning and name, and link its origin; that project's [glossary](https://github.com/borgnetzwerk/speaker-mining/blob/main/documentation/Wikidata/archive/2026-04-26_investigation/07_glossary.md) and [naming decisions](https://github.com/borgnetzwerk/speaker-mining/blob/main/documentation/Wikidata/archive/2026-04-26_investigation/11_naming_decisions.md) record why each name was chosen and which earlier names it replaces.

Nothing described here is implemented yet; the terms fix the vocabulary before the code is written.

## Storage

**Event.** An immutable record of something that happened, for example a response received from a server. Events are only ever appended, never changed or removed.

**Event log.** The append-only files that hold all events. It is the permanent memory of the tool; everything else is derived from it. (speaker-mining: *event store*.)

**Entity store.** The local copy of entity documents (items, properties, lexemes) derived from the event log, keeping every revision seen.

**Revision.** A version of an entity as the server reported it, identified by the server's revision ID. The tool keeps all revisions it has seen, so a result can be reproduced later.

**Cache-first.** A request is answered from the entity store if a suitable answer exists; only a miss leads to a network request.

## Fetching

**`basic_fetch`.** A small fetch with a fixed payload: labels, descriptions and aliases in the configured languages (plus the language-independent default), and the claims *instance of* ([P31](https://www.wikidata.org/wiki/Property:P31)) and *subclass of* ([P279](https://www.wikidata.org/wiki/Property:P279)). Enough to know what an entity is, without everything it links to. Because the payload is fixed, many entities can be fetched in one batched request, which keeps the load on the server low. (speaker-mining; earlier name: *hydration*.)

**`full_fetch`.** Retrieves all claims of one entity (its outgoing statements), with their qualifiers and references. (speaker-mining; earlier name: *expansion*.) Claims of other entities that point to this one (incoming links) are not part of a `full_fetch`; they need a separate SPARQL query, for which no term is fixed yet.

**Fully fetched.** An entity for which a `full_fetch` has been performed at least once.

**`fetch_decision`.** The step that looks at the claims of a fully fetched entity and decides which of the referenced entities are fetched next, and how (`basic_fetch`, `full_fetch` or not at all). It only decides; it fetches nothing itself. The rules for this decision come from the project that uses the tool. The cycle reads `full_fetch` → `fetch_decision` → `full_fetch` → … (speaker-mining; earlier name: *expansion*.)

**Budget.** The maximum number of network requests a run may make. A budget of zero means the tool answers from the entity store only. (speaker-mining.)

## Queries

**Query corpus.** The documented SPARQL queries in [`queries/`](../queries/), one Markdown file per question, with the question, the endpoint and the query.

**Endpoint.** The address a query or request is sent to, for example the [Wikidata Query Service](https://query.wikidata.org/sparql) or a wiki's [Action API](https://www.mediawiki.org/wiki/API:Main_page).

## Identification

**Operator.** The person or organisation who runs an instance of the tool and is responsible for its requests. The operator is named in every request through the [User-Agent](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy); see the [README](../README.md#operator-identification-required).
