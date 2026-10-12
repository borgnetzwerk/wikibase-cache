---
question: "Where do these classes sit in Wikidata: what are their superclasses, two levels up?"
endpoint: https://query.wikidata.org/sparql
status: tested
created: 2026-10-12
parameters:
  class: "one or more class items, set in the VALUES line"
last_run: 2026-10-12
result_rows: 33
result_checksum: "sha256:400b0b3caa590b3d1be0255bc112214eb99ed6d9383dc54d091f9dbed6c032a8"
runtime: "under 1 s"
related:
  - subclass_tree_instances.md
  - class_property_usage.md
  - https://www.wikidata.org/wiki/Q2431196
---

# Where does a class sit?

Lists, for each class in the `VALUES` line, its direct superclasses (*subclass of*, [P279](https://www.wikidata.org/wiki/Property:P279)) and their superclasses. Shows whether a class sits where we expect it, and which classes several of them share. Run it together with [subclass_tree_instances.md](subclass_tree_instances.md): one looks up, the other down.

```sparql
SELECT ?class ?classLabel ?parent ?parentLabel ?grandparent ?grandparentLabel WHERE {
  VALUES ?class { wd:Q34508 wd:Q110879246 wd:Q11424 wd:Q21191270 wd:Q1464125 wd:Q193977 }
  ?class wdt:P279 ?parent .
  OPTIONAL { ?parent wdt:P279 ?grandparent . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
```

## Example output

Run on 2026-10-12 for six video-like classes, summarised (one row per class and direct superclass; the second level in brackets where it matters):

| class | direct superclasses |
|---|---|
| [video recording](https://www.wikidata.org/wiki/Q34508) | technique, imaging method |
| [video work](https://www.wikidata.org/wiki/Q110879246) | video recording, visual work |
| [film](https://www.wikidata.org/wiki/Q11424) | audiovisual work, visual artwork, moving image |
| [television series episode](https://www.wikidata.org/wiki/Q21191270) | audiovisual work, television program, episode |
| [web series episode](https://www.wikidata.org/wiki/Q1464125) | episode (broadcasting program) |
| [music video](https://www.wikidata.org/wiki/Q193977) | audiovisual work, short film (film), musical work |

[audiovisual work (Q2431196)](https://www.wikidata.org/wiki/Q2431196) itself is a subclass of video and/or audio work, time-based visual work, visual work, creative work and intangible good.

## Notes

- Film, television series episode and music video share audiovisual work as a direct superclass; video recording does not, because it is a technique. A class that is used for the medium of a work is a different kind of class from one used for the work itself.
- Two levels are usually enough to see where a class sits; going up with `wdt:P279*` reaches very general classes (entity, object) that every class shares.
