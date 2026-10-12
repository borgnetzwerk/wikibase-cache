---
question: "What does the subclass tree of a class look like, and where are its instances?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  class: "the root class, in the P279* line (here Q34508, video recording)"
last_run: 2026-10-12
result_rows: 44
result_checksum: "sha256:2cadc64e09084c9ba7541d756b4d92f74bbe9716fe6ac95aaa6715bde3a58d33"
runtime: "under 1 s"
related:
  - class_property_usage.md
  - https://www.wikidata.org/wiki/Q34508
---

# What does a subclass tree look like?

Lists the class and all of its subclasses (*subclass of*, [P279](https://www.wikidata.org/wiki/Property:P279), any depth), each with its direct superclasses and the number of its direct instances. Shows whether the subclass variant of [class_property_usage.md](class_property_usage.md) is worth running, and what it would include. To use it for another class, change `wd:Q34508`.

```sparql
SELECT ?subclass ?subclassLabel ?parent ?parentLabel ?instances WHERE {
  {
    SELECT ?subclass (COUNT(?item) AS ?instances) WHERE {
      ?subclass wdt:P279* wd:Q34508 .
      OPTIONAL { ?item wdt:P31 ?subclass . }
    }
    GROUP BY ?subclass
  }
  OPTIONAL { ?subclass wdt:P279 ?parent . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?instances)
```

## Example output

Run on 2026-10-12 for [video recording](https://www.wikidata.org/wiki/Q34508): 30 classes (the root and 29 subclasses); a class with several superclasses appears once per superclass. The classes with instances:

| subclass | label | instances | superclasses |
|---|---|---|---|
| Q110879246 | video work | 1460 | video recording, visual work |
| Q34508 | video recording | 178 | technique, imaging method |
| Q9082479 | television report | 5 | television program, video recording, reportage, broadcast journalism |
| Q28060362 | high-dynamic-range video | 2 | video recording |
| Q186563 | time-lapse | 1 | photography, video recording |
| Q108751637 | analog video recording | 1 | video recording |

The other 24 have no direct instances. They mix techniques (slow motion, hyperlapse), formats (high-definition video, VR180, vertical video, videocassette, VHS tape) and single works entered as subclasses (for example TEDxDeExtinction).

## Notes

- Counting with `OPTIONAL` keeps classes without instances in the list (count 0).
- For a class with a large tree (thousands of subclasses), restrict the depth first, for example with `wdt:P279/wdt:P279?` instead of `wdt:P279*`.
