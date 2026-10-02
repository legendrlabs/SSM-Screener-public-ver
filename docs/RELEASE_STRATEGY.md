# Release Strategy

## Private canonical repository

`SSM-Screener` remains the canonical private research repository. It may contain:

- active research watchlists
- manual dilution overrides
- experimental parsers
- unpublished scoring changes
- internal output snapshots

## Public distribution

Do **not** make one branch of this repository public: GitHub visibility is repository-level.
When the project is stable, publish a separate public repository generated from a sanitized release branch/tag.

Recommended flow:

```text
private main
  -> private develop / feature branches
  -> release/public-staging
  -> sanitize / tests / docs
  -> mirror to separate public repository
```

Public artifacts should exclude:

- personal watchlists and positions
- local/manual overrides tied to private research
- secrets, API keys, `.env` files
- generated output snapshots not intended as examples
- private thesis notes

Public artifacts should include:

- `SKILL.md`
- source package
- tests
- example configs
- deterministic gate documentation
- sample fixture data
- security/data-source notes
- changelog and tagged releases

## Versioning

Use SemVer:

- `0.x`: research/beta; schemas and gates may change
- `1.0`: stable CLI, output schema, and gate semantics
- patch: bug fixes/parser corrections
- minor: new data sources/gates/events
- major: incompatible output or scoring semantics
