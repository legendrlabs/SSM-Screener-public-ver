# Immutable Release Updater Design

## Context

SSM v1.1.2 introduced `ssm version` and `ssm update`, but its trust model still depends on the moving `main` branch. The updater currently reads `main/pyproject.toml` for the latest version and downloads `main.zip` separately. Those two reads are not cryptographically or immutably tied to the same source state.

The goal of this change is to make release metadata and update payload selection immutable and self-consistent, while preserving the existing user-owned-file and rollback semantics.

## Goals

- Generate release metadata automatically from the release source, never by manual editing.
- Derive release version from `pyproject.toml` and release source identity from the exact source commit/tag used to build the release.
- Make the updater resolve one release manifest first, then download only the immutable source identified by that manifest.
- Verify manifest/version/source identity and managed-file hashes before modifying the installed bundle.
- Preserve `config/watchlist.csv`, `config/overrides.json`, `output/`, and `SEC_USER_AGENT` exactly as the current updater does.
- Preserve the existing rollback behavior for failures during file replacement.
- Avoid hardcoding any concrete release version string in updater production code.
- Add CI regressions for metadata mismatch, source mismatch, successful old-to-new updates, rollback, and user-file preservation.

## Non-goals

- Signing releases with GPG/Sigstore in this iteration.
- Replacing GitHub Releases with a separate package registry.
- Automatically force-updating users without an explicit `ssm update` action.
- Managing or migrating user-owned configuration files.

## Chosen Architecture

GitHub Releases become the publication boundary. The updater may use a moving endpoint only to discover the latest `release.json`; after reading that manifest, all source retrieval is pinned to an immutable commit SHA or tag declared by the manifest.

A release/build script generates `release.json` from `pyproject.toml`, release tag, and current source commit. The release workflow validates that the tag version matches `[project].version`, generates hashes for updater-managed files, and publishes the manifest as a GitHub Release asset.

The updater fetches the latest manifest, validates it, constructs an archive URL from the manifest's immutable `source_commit` (or validated immutable tag), downloads that archive, validates its source/version/hash contents, and only then enters the existing bundle replacement transaction.

## Release Manifest

`release.json` is generated, not hand-maintained. It is not a source-of-truth file committed and edited as part of normal development.

Canonical shape:

```json
{
  "schema_version": 1,
  "version": "<project version>",
  "tag": "v<project version>",
  "source_commit": "<40-character lowercase git SHA>",
  "managed_files": {
    "ssm/cli.py": "sha256:<hex>",
    "ssm/updater.py": "sha256:<hex>"
  }
}
```

### Manifest invariants

- `schema_version` must be a supported integer schema value.
- `version` must equal `[project].version` from the source used to build the release.
- `tag` must correspond to `version` under the repository's release naming convention (`v{version}`).
- `source_commit` must be a full 40-character hexadecimal commit SHA.
- Every `managed_files` entry must use a repository-relative normalized path and a `sha256:` digest.
- User-owned paths must never appear in `managed_files`.

The updater must not contain a literal current release version such as `1.1.3`; it compares the installed version to the manifest-provided version generically.

## Managed File Set

The release builder computes SHA-256 hashes for files that the updater is allowed to replace. The exact managed-file set is derived from repository contents with explicit exclusions rather than manually copied into `release.json`.

Excluded user-owned state:

- `config/watchlist.csv`
- `config/overrides.json`
- everything under `output/`
- `.git/`
- environment variables, including `SEC_USER_AGENT`

The builder may include source, scripts, package metadata, documentation, and bundled default configuration that are part of the distributed application. Paths excluded by updater preservation policy must also be excluded from the manifest.

## Release Build Flow

1. Checkout the exact release source commit.
2. Read `[project].version` from `pyproject.toml`.
3. Read the release tag supplied by the workflow.
4. Validate `tag == v{project.version}`.
5. Resolve the exact source commit (`git rev-parse HEAD`).
6. Enumerate managed files using the same preservation/exclusion rules as the updater.
7. Compute SHA-256 for each managed file.
8. Write `release.json` into the build workspace/artifact area.
9. Validate the generated manifest against `pyproject.toml` and the source commit.
10. Publish `release.json` as a GitHub Release asset for that tag.

A failed invariant aborts release publication.

## Updater Discovery Flow

`ssm version` and `ssm update` use the release manifest as the only latest-release metadata source.

1. Fetch latest release metadata/asset endpoint.
2. Download `release.json`.
3. Parse and validate schema.
4. Compare installed version to `manifest.version`.
5. If no newer version exists, stop without downloading an archive.
6. If newer, construct an immutable archive URL from `manifest.source_commit`.
7. Download and extract to a temporary directory.
8. Validate archive provenance and contents.
9. Only after all checks pass, apply update using existing preservation and rollback behavior.

The updater must not independently fetch `main/pyproject.toml`, `main.zip`, or any other moving source payload after the manifest is resolved.

## Archive Verification

Before any installed file is touched, the extracted archive must satisfy all of the following:

- archive root is structurally valid;
- `pyproject.toml` exists;
- archive project version equals `manifest.version`;
- the archive URL/source requested was exactly `manifest.source_commit`;
- extracted release source identity is consistent with the manifest source identifier where GitHub archive naming/metadata makes that observable;
- every path in `manifest.managed_files` exists in the archive;
- every managed-file SHA-256 equals the manifest digest;
- no manifest managed path is a preserved/user-owned path.

Any verification failure raises a validation error before `apply_bundle_update` runs. The installed tree remains unchanged.

### Source commit mismatch

Tests must explicitly model a manifest that claims commit A while the downloaded/extracted source represents commit B. The updater must reject the payload before application.

Because GitHub source ZIPs do not contain a `.git` directory, source identity is anchored by the archive URL selected from `manifest.source_commit` and by content hashes generated at release time. Test fixtures must preserve a separately supplied downloaded-source identity so the updater can assert `downloaded_source_commit == manifest.source_commit` before applying the archive.

## Update Application and Rollback

The current transactional copy model remains in place:

- copy incoming managed files into the installation;
- backup overwritten files before replacement;
- track newly created files;
- on any copy error, remove created files and restore overwritten files from backup;
- do not alter preserved user-owned paths.

Manifest verification is an earlier gate; rollback protects only the mutation phase after verification passes.

## Install Modes

### Bundle/skill installation

Use immutable release manifest + immutable commit archive + pre-apply validation + transactional bundle replacement.

### Git checkout installation

A Git installation must not perform an unpinned `git pull` as the updater's trust decision. It should fetch/checkout the immutable `source_commit` declared by the manifest, then reinstall editable/package metadata as required. Local modifications that prevent a safe checkout must cause update failure rather than forced overwrite.

### Pip installation

Pip installation should be pointed at the immutable archive URL derived from `source_commit`, not `main.zip`. Manifest and archive validation should occur before invoking pip where practical; the selected pip source must still be immutable.

## CI and Release Validation

The normal test workflow must run updater unit/integration regressions. The release workflow must additionally validate release metadata generation.

Required regression tests:

1. **manifest version mismatch**
   - manifest version differs from archive/project version;
   - update is rejected;
   - installed files remain unchanged.

2. **archive/source_commit mismatch**
   - manifest source commit differs from downloaded-source identity;
   - update is rejected before apply.

3. **old-version → new-version**
   - installed version is lower than manifest version;
   - immutable archive validates;
   - managed files update successfully.

4. **update failure → rollback**
   - failure occurs during file replacement after successful verification;
   - overwritten files are restored and newly created files are removed.

5. **user files preserved**
   - incoming archive contains watchlist/overrides/output data;
   - installed user copies remain unchanged.

Additional release invariant tests:

- generated `release.json.version == pyproject project.version`;
- generated `release.json.source_commit == supplied/current release source commit`;
- tag/version mismatch fails release-manifest generation;
- managed-file hash mismatch fails archive validation;
- preserved paths cannot enter the managed-file manifest.

## Failure Semantics

All metadata and payload verification errors are fail-closed:

- `ssm version` may report that the update check failed, without changing installed state.
- `ssm update` returns/raises a clear validation failure and performs no mutation if manifest or archive verification fails.
- no fallback to `main`, `main.zip`, or an unverified archive is permitted.
- network errors do not alter the installation.

## Compatibility

v1.1.2 clients do not understand the new release manifest flow and cannot be retroactively changed. Users must receive one updater version containing this implementation through the existing v1.1.2 mechanism. From that version onward, all subsequent updates use immutable release metadata.

The release process therefore has a one-time bootstrap transition: publish the first immutable-release-aware version through the current mechanism, then rely on GitHub Release manifests for later versions.

## Security Properties

This design prevents version metadata and payload content from being selected from different moving `main` states. A manifest resolves one immutable source commit, and managed-file hashes bind the payload contents used by the updater to the release metadata.

This is integrity pinning, not publisher-signature verification. A compromised GitHub repository/release publisher could still publish a malicious manifest and matching archive; signing is intentionally outside this iteration.

## Acceptance Criteria

- No production updater code contains a concrete current release version string.
- No production updater path reads both a moving `main` version file and a moving `main` archive.
- `release.json` is generated automatically from project version + source commit/tag.
- CI/release checks enforce manifest/project version equality.
- Archive download is pinned to manifest source identity.
- Manifest/source/version/hashes are validated before mutation.
- Any pre-apply verification failure leaves the installation untouched.
- Mutation-phase failure restores the prior managed files.
- watchlist, overrides, output, and SEC identity remain user-owned and preserved.
- Required regressions pass in CI.
