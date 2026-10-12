---
question: "Which classes do the items that link to a given website belong to?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  website: "the domain, in the geuquery line (here media.ccc.de)"
last_run: 2026-10-12
result_rows: 49
result_checksum: "sha256:6b37342e0ef47d7349eb1def7158abdf09e6b13e52b289587a8baa66bcaf9e35"
runtime: "about 1 s"
related:
  - items_with_property_by_class.md
  - https://www.mediawiki.org/wiki/API:Exturlusage
  - https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual/MWAPI
---

# Which classes do the items linking to a website belong to?

For a website that has no identifier property of its own in Wikidata, finds the items that link to it anywhere in their statements and counts their classes. It asks the wiki's own [external link search (exturlusage)](https://www.mediawiki.org/wiki/API:Exturlusage) from inside SPARQL, through the [MWAPI service](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual/MWAPI). Run here with [media.ccc.de](https://media.ccc.de/), to see how recordings of talks are represented; to use it for another website, change `geuquery`.

```sparql
SELECT ?class ?classLabel (COUNT(DISTINCT ?item) AS ?items) WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                    wikibase:api "Generator" ;
                    mwapi:generator "exturlusage" ;
                    mwapi:geuquery "media.ccc.de" ;
                    mwapi:geunamespace "0" ;
                    mwapi:geulimit "max" .
    ?item wikibase:apiOutputItem mwapi:title .
  }
  OPTIONAL { ?item wdt:P31 ?class . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?class ?classLabel
ORDER BY DESC(?items)
```

## Example output

Run on 2026-10-12, the first 10 of 49 rows (an item with several classes counts once per class):

| class | label | items |
|---|---|---|
| Q27968055 | recurring event edition | 34 |
| Q5 | human | 23 |
| Q108095628 | conference edition | 7 |
| Q15900647 | convention series | 4 |
| Q113880369 | hacker convention | 3 |
| Q56220509 | annual conference | 3 |
| Q37807168 | WikidataCon | 3 |
| Q7935096 | virtual event | 3 |
| Q111290948 | presentation in WikidataCon 2019 | 3 |
| Q11483816 | annual event | 2 |

## Notes

- Items that link to media.ccc.de are mostly event editions and people; single talks are rare (*lecture* 2, *presentation in WikidataCon 2019* 3). Recordings of talks are usually not items of their own, but a link on the event or the speaker.
- The link search covers the statements of items (namespace 0), not their labels or descriptions.
- The MWAPI service follows the API's continuation only up to a limit; for a website with very many links, check whether the result is complete.
