# Immutable Release Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the moving-`main` updater trust model with an auto-generated release manifest that pins one immutable source commit and verifies managed-file hashes before any installation mutation.

**Architecture:** Add one shared release-policy module used by both the release builder and updater so managed-file inclusion/exclusion cannot drift. A release workflow generates `release.json` from `pyproject.toml`, tag, source commit, and SHA-256 hashes, while the updater first resolves that manifest and then downloads only the archive pinned by `source_commit`, validates it fully, and reuses the existing transactional apply/rollback logic.

**Tech Stack:** Python 3.11, `tomllib`, `hashlib`, `requests`, `zipfile`, `pytest`, GitHub Actions / GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-10-03-immutable-release-updater-design.md`

## Global Constraints

- `release.json` is generated automatically; it is never manually maintained as release source-of-truth.
- Release `version` comes from `[project].version` in `pyproject.toml`.
- Release source identity is a full immutable 40-character commit SHA plus tag `v{version}`.
- Production updater code must not hardcode any concrete current release version string.
- After manifest resolution, updater must not fetch `main/pyproject.toml`, `main.zip`, or any other moving source payload.
- `config/watchlist.csv`, `config/overrides.json`, `output/`, and `SEC_USER_AGENT` remain user-owned and preserved.
- Any manifest/archive verification failure occurs before mutation and leaves the installed tree unchanged.
- Any mutation-phase failure restores overwritten files and removes newly created files.
- Git installation mode must not use an unpinned `git pull` as its update trust decision.

## Review Focus

- Malformed or unsupported manifest schema must fail closed before archive download/apply; Task 2 tests this.
- Path traversal or non-normalized managed-file entries must be rejected; Task 1/2 tests this.
- A manifest that includes preserved paths must be rejected even if its hashes are valid; Task 1/2 tests this.
- Git checkout with local modifications must not force-reset user work; Task 4 tests safe failure.
- Network failure after manifest resolution but before archive completion must leave installation unchanged; Task 3 tests this.

---

### Task 1: Shared release policy and deterministic manifest builder

**Files:**
- Create: `ssm/release_policy.py`
- Create: `scripts/build_release_manifest.py`
- Create: `tests/test_release_manifest.py`
- Modify: `pyproject.toml` only when the release version is intentionally bumped for the bootstrap release.

**Interfaces:**
- Produces: `project_version(root: Path) -> str`
- Produces: `is_preserved_path(relative: Path) -> bool`
- Produces: `iter_managed_files(root: Path) -> list[Path]`
- Produces: `sha256_file(path: Path) -> str`
- Produces: `build_manifest(root: Path, tag: str, source_commit: str) -> dict`
- Produces CLI: `python scripts/build_release_manifest.py --tag <tag> --source-commit <sha> --out <path>`

- [ ] **Step 1: Write failing manifest-generation tests**

Add tests named:
- `test_manifest_version_matches_pyproject`
- `test_manifest_rejects_tag_version_mismatch`
- `test_manifest_records_supplied_source_commit`
- `test_manifest_excludes_user_owned_paths`
- `test_manifest_hashes_managed_files`
- `test_managed_paths_are_normalized_and_safe`

Assertions must establish `schema_version == 1`, `tag == f"v{version}"`, a full 40-char lowercase SHA, `sha256:<64 hex>` digests, and absence of watchlist/overrides/output entries.

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_release_manifest.py -q`
Expected: FAIL because `ssm.release_policy` and manifest builder interfaces do not exist.

- [ ] **Step 3: Implement shared policy and manifest builder**

Use `tomllib` for `[project].version`, `hashlib.sha256` for digests, normalized `Path` validation, and one shared preserved-path policy. `scripts/build_release_manifest.py` must only serialize the result of `build_manifest`; it must not duplicate updater exclusion logic.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_release_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: generate immutable release manifests`

---

### Task 2: Manifest parsing and fail-closed archive verification

**Files:**
- Modify: `ssm/updater.py`
- Test: `tests/test_self_update.py`

**Interfaces:**
- Consumes: shared policy functions from Task 1.
- Produces: `fetch_release_manifest(timeout: float = 2.0) -> dict`
- Produces: `validate_manifest(manifest: dict) -> dict`
- Produces: `immutable_archive_url(source_commit: str) -> str`
- Produces: `validate_archive(incoming_root: Path, manifest: dict, downloaded_source_commit: str) -> None`

- [ ] **Step 1: Write failing updater trust-model tests**

Add tests named:
- `test_manifest_version_mismatch_rejected_before_apply`
- `test_archive_source_commit_mismatch_rejected_before_apply`
- `test_managed_file_hash_mismatch_rejected_before_apply`
- `test_manifest_with_preserved_path_rejected`
- `test_invalid_manifest_schema_fails_closed`
- `test_immutable_archive_url_uses_manifest_commit_not_main`

Each rejection test must snapshot installed files and assert no mutation occurred.

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_self_update.py -q`
Expected: FAIL because updater still reads moving `main` metadata/archive and lacks manifest/archive validation.

- [ ] **Step 3: Replace moving-main discovery with release-manifest discovery**

`version_status()` must derive latest version from the validated manifest. Remove production use of `REMOTE_PYPROJECT` and `main.zip`. The latest-release moving endpoint may only return/discover `release.json`; all payload retrieval after that uses the manifest's immutable `source_commit`.

- [ ] **Step 4: Implement pre-apply archive validation**

Validate archive `pyproject.toml` version, downloaded source identity, every manifest managed-file hash, required file presence, safe normalized paths, and preserved-path exclusion before any call to `apply_bundle_update`.

- [ ] **Step 5: Run GREEN updater tests**

Run: `pytest tests/test_self_update.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat: pin updater to immutable release manifests`

---

### Task 3: End-to-end bundle update transaction using validated immutable payloads

**Files:**
- Modify: `ssm/updater.py`
- Test: `tests/test_self_update.py`

**Interfaces:**
- Consumes: `validate_manifest`, `immutable_archive_url`, `validate_archive` from Task 2.
- Produces: `_download_bundle(source_commit: str, timeout: float = 30.0) -> tuple[TemporaryDirectory, Path, str]`
- Maintains: `apply_bundle_update(installed_root: Path, incoming_root: Path) -> dict`
- Maintains: `perform_update(dry_run: bool = False) -> dict`

- [ ] **Step 1: Write failing old→new and failure-safety tests**

Add tests named:
- `test_old_version_updates_to_manifest_version`
- `test_network_failure_after_manifest_resolution_does_not_mutate_installation`
- `test_bundle_update_rolls_back_overwritten_and_created_files_on_failure`
- `test_bundle_update_preserves_watchlist_overrides_and_output`

The old→new test must use different synthetic versions without embedding the repository's live version in production code.

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_self_update.py -q`
Expected: FAIL on immutable-download/update orchestration assertions.

- [ ] **Step 3: Wire validated immutable download into `perform_update`**

Flow: fetch manifest → validate manifest → compare versions → immutable archive download → validate archive → mutate. Preserve existing dry-run semantics and explicit preserved-path reporting.

- [ ] **Step 4: Keep rollback and user-file semantics unchanged**

Refactor only as needed to share `is_preserved_path`; do not weaken backup/restore behavior.

- [ ] **Step 5: Run GREEN tests**

Run: `pytest tests/test_self_update.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `test: cover immutable updater transaction safety`

---

### Task 4: Immutable behavior for Git and pip install modes

**Files:**
- Modify: `ssm/updater.py`
- Test: `tests/test_self_update.py`

**Interfaces:**
- Produces: `_update_git_checkout(root: Path, source_commit: str) -> None`
- Produces: `_update_pip_install(archive_url: str) -> None`

- [ ] **Step 1: Write failing install-mode tests**

Add tests named:
- `test_git_update_fetches_and_checks_out_manifest_commit_without_unpinned_pull`
- `test_git_update_with_local_changes_fails_without_force_reset`
- `test_pip_update_uses_commit_pinned_archive_url`

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_self_update.py -q`
Expected: FAIL because current Git mode uses `git pull --ff-only` and pip mode uses moving `main.zip`.

- [ ] **Step 3: Implement immutable Git update**

Fetch the declared commit from origin and update only when the checkout can move safely without overwriting local modifications. Do not call `reset --hard`; local-change conflicts must raise and preserve the checkout.

- [ ] **Step 4: Implement immutable pip update**

Invoke pip only with the already selected commit-pinned archive URL. Pre-validation remains the updater's trust gate.

- [ ] **Step 5: Run GREEN tests**

Run: `pytest tests/test_self_update.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat: make git and pip updates immutable`

---

### Task 5: CI invariants and GitHub Release publication workflow

**Files:**
- Modify: `.github/workflows/tests.yml`
- Create: `.github/workflows/release.yml`
- Test: `tests/test_release_manifest.py`

**Interfaces:**
- Release trigger: tag `v*` or explicit `workflow_dispatch` with an existing immutable tag/ref.
- Release artifact: `release.json` attached to the GitHub Release for the validated tag.

- [ ] **Step 1: Add CI-level invariant test**

Add/retain a test that generates a manifest from the checked-out source and asserts `manifest["version"] == project_version(root)` and source/tag consistency. This is the required CI invariant, not a manually committed `release.json` comparison.

- [ ] **Step 2: Update normal Tests workflow**

Keep full `pytest -q`; add no manually maintained metadata file. The test suite itself enforces manifest/project invariants.

- [ ] **Step 3: Create release workflow**

Workflow sequence: checkout full source → setup Python → install package/dev dependencies → determine tag and `GITHUB_SHA` → run full tests → run manifest builder → revalidate generated manifest → create/publish GitHub Release if needed → upload `release.json` asset. Tag/version mismatch must fail before publication.

- [ ] **Step 4: Validate workflow syntax and tests**

Run locally where possible: `pytest -q`
Expected: all tests PASS. Review YAML for least required `contents: write` permission only in release job.

- [ ] **Step 5: Commit**

Commit message: `ci: publish verified immutable release metadata`

---

### Task 6: Bootstrap release version, docs, and final verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `UPDATING.md`
- Modify: `README.md` only if it currently documents the obsolete moving-main behavior.

**Interfaces:**
- The new release version is chosen once at release time from normal semantic-version progression; updater production logic remains version-agnostic.

- [ ] **Step 1: Bump project version for the first immutable-release-aware bootstrap release**

Update `[project].version` and matching changelog heading only. Do not introduce that literal version into updater logic or tests whose purpose is generic version comparison.

- [ ] **Step 2: Document bootstrap semantics**

Explain that v1.1.2 users can use their existing updater once to reach the first immutable-manifest-aware release; all later updates use release manifests and commit-pinned archives.

- [ ] **Step 3: Run full fresh verification**

Run: `pytest -q`
Expected: 0 failures.

- [ ] **Step 4: Inspect changed files for private/user state**

Verify the PR contains no real `config/watchlist.csv`, private overrides, `output/`, credentials, or manually maintained `release.json`.

- [ ] **Step 5: Open PR and require green CI before merge**

PR body must summarize trust-model change, bootstrap behavior, preserved paths, and required regression coverage.

- [ ] **Step 6: Merge and verify `main` again**

After merge, confirm the `main` test workflow is green. Then create/push the release tag so `release.yml` publishes the generated `release.json`, and verify the Release asset declares the same version/source commit as the tagged release.
