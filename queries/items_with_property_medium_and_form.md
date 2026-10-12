---
question: "Which medium and which form of work do the items carrying a given property have?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  property: "the property, in the wdt: line (here P1651, YouTube video ID)"
last_run: 2026-10-12
result_rows: 243
result_checksum: "sha256:4a5b4a305fa31536a5b59a61edc41db24cb90ec21eaf7b018084259f1e197f83"
runtime: "about 3 s"
related:
  - items_with_property_by_class.md
  - https://www.wikidata.org/wiki/Property:P437
  - https://www.wikidata.org/wiki/Property:P7937
---

# Which medium and form do the items with a property have?

For all items that carry a property, counts the values of [distribution format (P437)](https://www.wikidata.org/wiki/Property:P437) and [form of creative work (P7937)](https://www.wikidata.org/wiki/Property:P7937). Complements [items_with_property_by_class.md](items_with_property_by_class.md): the class says what kind of work an item is, these two properties say how it is distributed and what form it has. Run here with [YouTube video ID (P1651)](https://www.wikidata.org/wiki/Property:P1651); to use it for another property, change `wdt:P1651`.

```sparql
SELECT ?property ?value ?valueLabel ?items WHERE {
  {
    SELECT ?property ?value (COUNT(DISTINCT ?item) AS ?items) WHERE {
      VALUES (?property ?p) { (wd:P437 wdt:P437) (wd:P7937 wdt:P7937) }
      ?item wdt:P1651 [] ;
            ?p ?value .
    }
    GROUP BY ?property ?value
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY ?property DESC(?items)
```

## Example output

Run on 2026-10-12. *distribution format*, selected values of 159 (the other 84 rows are values of *form of creative work*):

| value | label | items |
|---|---|---|
| Q15982450 | music streaming | 6059 |
| Q723685 | video on demand | 5094 |
| Q6473564 | music download | 3568 |
| Q269415 | digital distribution | 1266 |
| Q34467 | compact disc | 1179 |
| Q3276244 | video podcast | 988 |
| Q63412991 | YouTube video | 788 |
| Q24633474 | audio podcast | 732 |
| Q47770 | Blu-ray Disc | 389 |
| Q47544021 | theatrical release | 302 |
| Q5294 | DVD | 142 |
| Q20899 | podcast | 24 |
| Q110888775 | Vimeo video | 8 |

*form of creative work*, the most frequent: song 8519, feature film 367, instrumental music 238, studio album 128.

## Notes

- The medium and the channel of distribution are a value of *distribution format*, not a class: [YouTube video (Q63412991)](https://www.wikidata.org/wiki/Q63412991) has 788 items as a distribution format but only 2 direct instances as a class (2026-10-12).
- Podcasts use the same property: *video podcast* and *audio podcast* distinguish the medium of a podcast episode.
- *form of creative work* describes the kind of work (song, feature film), not the medium.
