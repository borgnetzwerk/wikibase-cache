---
question: "Which classes do the items carrying a given property belong to?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  property: "the property, in the wdt: line (here P1651, YouTube video ID)"
last_run: 2026-10-12
result_rows: 30
result_checksum: "sha256:d4f2c589fc185f7ad4b8e305b1728a5c4ee4d423f791d8360c55855e70ee900a"
runtime: "about 2 s"
related:
  - class_property_usage.md
  - https://www.wikidata.org/wiki/Property:P1651
---

# Which classes do the items with a property belong to?

Starts from a property instead of a class: for all items that carry it, counts the classes they are an instance of. Useful when a kind of thing has no single class in Wikidata. Run here with [YouTube video ID (P1651)](https://www.wikidata.org/wiki/Property:P1651), to find out how Wikidata models videos; to use it for another property, change `wdt:P1651`.

```sparql
SELECT ?class ?classLabel ?items WHERE {
  {
    SELECT ?class (COUNT(DISTINCT ?item) AS ?items) WHERE {
      ?item wdt:P1651 [] ;
            wdt:P31 ?class .
    }
    GROUP BY ?class
    ORDER BY DESC(?items)
    LIMIT 30
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?items)
```

## Example output

Run on 2026-10-12, the first 15 of 30 rows:

| class | label | items |
|---|---|---|
| Q134556 | single | 25382 |
| Q11424 | film | 12101 |
| Q105543609 | musical work/composition | 9242 |
| Q110039749 | Saturday Night Live sketch | 6637 |
| Q7366 | song | 4077 |
| Q21191270 | television series episode | 2652 |
| Q61855877 | podcast episode | 2601 |
| Q55850593 | music track with vocals | 2103 |
| Q5 | human | 1574 |
| Q1983062 | episode | 1547 |
| Q1464125 | web series episode | 1361 |
| Q193977 | music video | 1297 |
| Q7889 | video game | 1048 |
| Q7302866 | audio track | 923 |
| Q24862 | short film | 893 |

## Notes

- Items with a YouTube video ID are classified by their content (single, film, episode, music video), not as videos. Most of the video-like classes sit below [audiovisual work (Q2431196)](https://www.wikidata.org/wiki/Q2431196) (see [superclasses_two_levels.md](superclasses_two_levels.md)); the medium is given by *distribution format* (see [items_with_property_medium_and_form.md](items_with_property_medium_and_form.md)). [video recording (Q34508)](https://www.wikidata.org/wiki/Q34508) has 178 direct instances, its subclass [video work (Q110879246)](https://www.wikidata.org/wiki/Q110879246) 1,460 (2026-10-12).
- Some items carry the YouTube ID of a related video rather than being one (for example humans or video games).
