# Changelog

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versions: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- README with purpose, operator identification and data location.
- Operator template (`operator.example.yaml`); the local `operator.yaml` is ignored by Git.
- Related work: the tools we compared this project with (`docs/related_work.md`).
- Glossary of the terms used, including the fetch modes taken over from speaker-mining (`docs/glossary.md`).
- SPARQL corpus (`queries/`), every query tested with checksum and example output: properties of the instances of a class (podcast episode, podcast show, video recording; with a subclass variant), instance counts (with a ceiling for large classes), superclasses and subclass trees, a sample variant for large classes, classes, medium and form of the items carrying a property, classes of the items linking to a website.
- Licensing: MIT for code and queries, CC BY 4.0 for documentation, following the REUSE Specification; contribution guide.
