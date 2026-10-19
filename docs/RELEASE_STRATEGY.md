# SSM Release Strategy — Public distribution only

## Canonical repository

`legendrlabs/SSM-Screener-public-ver` is the canonical **development and distribution** repository.
Since v1.1.6, the upstream repository **does not** run scheduled SEC/market scans, 
publish a central `quality.json` or provide user SEC contact identities.

Every recipient runs the SSM bundle in their own environment and provides their own
`SEC_USER_AGENT` (an identifiable name/organization and working email, not a login
or API key). A ChatGPT skill bundle and a Python CLI installation are different
installation paths; installing a CLI does not register a managed skill automatically.

## Public deliverables

Include:
- root `SKILL.md`, `scripts/run_ssm.py`, `ssm/`, `pyproject.toml`
- source, regression tests, deterministic gate criteria and example configuration
- installation/updating instructions and `docs/operations/user-sec-setup.md`
- immutable version tag and `release.json` manifest with pinned source commit and hashes

Exclude:
- individual `SEC_USER_AGENT` values, credentials, environment files and keys
- personal watchlists and overrides
- positions, private research, generated scan output and account records
- GitHub-hosted central scan and publication workflows

The public repository has only CI tests and release-publishing workflows. Installing
users may configure automation in a separate repository **they own**, using their
own GitHub Actions secrets. An upstream release never inherits the user's secret.

## Immutable publication

1. Make a version bump in `pyproject.toml` plus `ssm/__init__.py`.
2. Run the entire Python regression suite and Node release-publisher checks.
3. Review the release delta and merge to `main` (with the `pyproject.toml`
   version change in that main push).
4. The existing `.github/workflows/release.yml` validates the tested checkout,
   creates a new `vX.Y.Z` tag pinned to that exact commit, validates the
   generated `release.json` and publishes the corresponding immutable release.
5. Check GitHub's actual published Release, tag, and manifest. Do not claim a
   successful release merely because a PR merged or CI started.
6. Never rewrite previous version tags or overwrite historical release assets.
   A version already tagged at a different commit must not be republished.

User state preserved by updater:
`config/watchlist.csv`, `config/overrides.json`, `output/`, and
the existing process environment variable `SEC_USER_AGENT`.

## Versioning

Use SemVer. Patch versions may include documentation, installation,
operational and compatibility fixes without changing gate/scoring semantics.
Materially different gate or output contracts may require a minor/major version.
Unknown fully diluted economics must continue to be reported as `DATA_HOLD`.
