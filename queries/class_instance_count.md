---
question: "How many direct instances do these classes have in Wikidata?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  class: "one or more class items, set in the VALUES line"
last_run: 2026-10-12
result_rows: 5
result_checksum: "sha256:1e081392972773ed9112aff49e8be1fd2b2f74aa627901dfe752e5600367c7ce"
runtime: "about 2 s"
related:
  - class_property_usage.md
---

# How many direct instances does a class have?

Counts the direct instances (*instance of*, [P31](https://www.wikidata.org/wiki/Property:P31)) of each class in the `VALUES` line. Run it before [class_property_usage.md](class_property_usage.md): the number of instances shows whether a property analysis fits within the query time limit.

```sparql
SELECT ?class ?classLabel ?instances WHERE {
  {
    SELECT ?class (COUNT(?item) AS ?instances) WHERE {
      VALUES ?class { wd:Q24634210 wd:Q34508 wd:Q43229 wd:Q61855877 wd:Q34770 }
      ?item wdt:P31 ?class .
    }
    GROUP BY ?class
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?instances)
```

## Example output

Run on 2026-10-12:

| class | label | instances |
|---|---|---|
| Q43229 | organization | 530276 |
| Q61855877 | podcast episode | 17678 |
| Q24634210 | podcast show | 9857 |
| Q34770 | language | 9766 |
| Q34508 | video recording | 178 |

## Variant: with a ceiling, one class

Counts at most 100,001 instances of one class. A result of 100,001 means "at least 100,000"; `?capped` says so explicitly. Use it as the first step for any class whose size is unknown.

```sparql
SELECT (COUNT(?item) AS ?instances) (COUNT(?item) > 100000 AS ?capped) WHERE {
  {
    SELECT ?item WHERE {
      ?item wdt:P31 wd:Q5 .
    }
    LIMIT 100001
  }
}
```

Run on 2026-10-12 for [human (Q5)](https://www.wikidata.org/wiki/Q5): `instances` 100001, `capped` true; `sha256:e40a7f347a31d3bc56d4f8ce6fb235082b45b2494d8a866c8c73783ba368b375`, about 2 s.

The ceiling only works for one class per query. A `LIMIT` inside a subquery applies to the whole subquery, not to each class: with several classes in a `VALUES` line, the first large class takes up the whole ceiling and the others drop out of the result (tried on 2026-10-12 with six classes; only Q5 came back).

## Notes

- A class with millions of instances makes the uncapped query exceed the 60-second limit, even when it is only one of several classes in the list: with [human (Q5)](https://www.wikidata.org/wiki/Q5) added, the main query timed out (HTTP 504). Count such classes with the ceiling variant.
- Classes without a class item in Wikidata cannot be counted this way.
