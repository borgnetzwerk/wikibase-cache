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

## Notes

- A class with millions of instances makes the whole query exceed the 60-second limit, even when it is only one of several classes in the list: with [human (Q5)](https://www.wikidata.org/wiki/Q5) added, this query timed out (HTTP 504). Leave out classes that are known to be very large.
- Classes without a class item in Wikidata cannot be counted this way.
