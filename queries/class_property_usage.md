---
question: "Which properties do instances of a class carry in Wikidata, and how often?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-11
parameters:
  class: "the class item, set in the VALUES line"
runs:
  - class: Q61855877
    label: podcast episode
    date: 2026-10-12
    instances: 17678
    result_rows: 100
    result_checksum: "sha256:1206cf8ddf60b187f8ecbdd388757732e6df446b2eca9c7022cc1fbcf2d3a691"
    runtime: "about 2 s"
  - class: Q24634210
    label: podcast show
    date: 2026-10-12
    instances: 9857
    result_rows: 100
    result_checksum: "sha256:a772c658c654e5f574d86ca588056e90cccc5755e760e35b38dd8be39f960f86"
    runtime: "about 11 s"
  - class: Q34508
    label: video recording
    date: 2026-10-12
    instances: 178
    result_rows: 100
    result_checksum: "sha256:1ca62034cab2e04c01b13db3e78cf4af0a83874e95fd3f3f48c9c69f02d2a8f0"
    runtime: "about 1 s"
related:
  - class_instance_count.md
  - https://www.wikidata.org/wiki/Q61855877
  - https://www.wikidata.org/wiki/Q24634210
  - https://www.wikidata.org/wiki/Q34508
---

# Which properties do instances of a class carry?

Counts, for all items that are a direct instance (*instance of*, [P31](https://www.wikidata.org/wiki/Property:P31)) of one class, how many of them use each property. Shows how Wikidata models a kind of thing in practice, before we model it ourselves. To use it for another class, change the class in the `VALUES` line; check the number of instances first with [class_instance_count.md](class_instance_count.md).

```sparql
SELECT ?property ?propertyLabel ?instances WHERE {
  {
    SELECT ?direct (COUNT(DISTINCT ?item) AS ?instances) WHERE {
      VALUES ?class { wd:Q61855877 }
      ?item wdt:P31 ?class ;
            ?direct [] .
    }
    GROUP BY ?direct
  }
  ?property wikibase:directClaim ?direct .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?instances)
LIMIT 100
```

## Example output

The first 12 of 100 rows per run, as property and number of instances using it.

- **[podcast episode](https://www.wikidata.org/wiki/Q61855877)** (17,678 instances): P31 17678, P179 *part of the series* 17558, P407 *language of work or name* 17163, P577 *publication date* 16474, P1476 *title* 15056, P437 *distribution format* 14032, P6216 *copyright status* 13072, P275 *copyright license* 13035, P371 *presenter* 12516, P2047 *duration* 10138, P5030 *talk show guest* 7394, P495 *country of origin* 7328.
- **[podcast show](https://www.wikidata.org/wiki/Q24634210)** (9,857 instances): P31 9857, P437 *distribution format* 9263, P1113 *number of episodes* 7379, P407 *language of work or name* 6389, P136 *genre* 6307, P5842 *Apple Podcasts podcast ID* 6192, P1019 *web feed URL* 6030, P10286 *logo URL* 5916, P5916 *Spotify show/podcast ID* 5793, P444 *review score* 5474, P856 *official website* 5462, P7998 *Podchaser podcast ID* 5299.
- **[video recording](https://www.wikidata.org/wiki/Q34508)** (178 instances): P31 178, P577 *publication date* 103, P1476 *title* 77, P1651 *YouTube video ID* 49, P921 *main subject* 45, P2047 *duration* 37, P136 *genre* 35, P407 *language of work or name* 33, P495 *country of origin* 32, P175 *performer* 25, P170 *creator* 25, P345 *IMDb ID* 24.

## Variant: including subclasses

Replace the `VALUES` line with a walk down the subclass tree, so that instances of every subclass count as well:

```sparql
SELECT ?property ?propertyLabel ?instances WHERE {
  {
    SELECT ?direct (COUNT(DISTINCT ?item) AS ?instances) WHERE {
      ?class wdt:P279* wd:Q34508 .
      ?item wdt:P31 ?class ;
            ?direct [] .
    }
    GROUP BY ?direct
  }
  ?property wikibase:directClaim ?direct .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?instances)
LIMIT 100
```

Run on 2026-10-12 for [video recording](https://www.wikidata.org/wiki/Q34508): 100 rows, `sha256:8f30cd30d0e587575a6fed2f83e1705d413dc47969b4f50c3a28caa542a67ad9`, about 19 s. 1,646 instances instead of 178, almost all from the subclass [video work (Q110879246)](https://www.wikidata.org/wiki/Q110879246), and a different profile: P31 1646, P437 *distribution format* 1450, P577 *publication date* 1427, P407 *language of work or name* 1338, P123 *publisher* 769, P953 *work available at URL* 754, P1476 *title* 714, P1651 *YouTube video ID* 711, P2047 *duration* 592, P921 *main subject* 138, P495 *country of origin* 126, P136 *genre* 120.

Look at the subclass tree first ([subclass_tree_instances.md](subclass_tree_instances.md)): a large tree makes the variant expensive, and a tree that mixes techniques, formats and works makes its result hard to read.

## Notes

- The main query counts direct instances only; the variant above includes subclasses.
- The query aggregates in a subquery first and adds labels only to the result rows. A first version that joined the properties and labels before grouping exceeded the 60-second limit of the [Wikidata Query Service](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual) (HTTP 504) for podcast episodes.
- Classes with hundreds of thousands of instances or more (for example [organization](https://www.wikidata.org/wiki/Q43229) with about 530,000 direct instances) are likely to exceed the limit; use a sample or a dump instead.
- Few instances do not mean few things of that kind: video recording has 178 direct instances, because Wikidata models videos by their content type instead (see [items_with_property_by_class.md](items_with_property_by_class.md)).
- Counts change as Wikidata is edited; each checksum identifies the result of its run.
