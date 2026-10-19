# SSM public distribution unification

Approved scope: use `legendrlabs/SSM-Screener-public-ver` as the integration and distribution target. Bring the source engine's current evidence/lifecycle safeguards into the existing public installation/update interface. Version: 1.1.5. No allocation or automatic trading changes.

Pinned inputs:
- Public distribution: b3381656a93d364d316a05f9de3dacd1e8fd7a2d (v1.1.4).
- Source engine: a9b76231b1ba1bee93b0c31306651d61a182f7e7.

Preserve public-only updater, immutable release policy, skill runner, user-file exclusions, and the public financial-retirement ordering/unknown-share fix. Source engine tests and public tests must coexist; do not discard assertions merely to get a green suite. Keep public empty watchlist/overrides and do not copy source output, scan triggers or personal settings.

## Plan and execution record

- [x] Establish both baselines after installing declared dependencies.
- [x] Import source regression tests first and observe missing safeguards fail against v1.1.4.
- [x] Integrate source engine modules except public CLI/version/updater and public-only financial-retirement fix. Retain both sides' regression assertions.
- [x] Run combined suite. Fix only material compatibility problems with a reproduced failing test.
- [x] Set project/module/docs version 1.1.5; verify CLI, skill runner, managed-file manifest and old-version update with preserved user state.
- [x] Add tested-main version-bump release path because connector cannot create tags/releases; keep existing tag/manual paths and immutable source/tag checks. Published release assets must not be silently replaced.
- [ ] Fresh independent code review, full verification, GitHub PR/CI, merge and verify v1.1.5 release/manifest.

This work uses a new isolated checkout and a feature branch. This document records the user's already-approved integration direction; it is not an architectural redesign. Full live-universe rescanning and a claim of zero SEC parsing errors are outside this integration verification.

## Decisions

- Keep the public financial-retirement ordering and `shares=None` representation, which source main does not contain. This avoids regressing existing public behavior.
- Keep the public distribution scan workflow read-only/manual and preserve user configs; do not copy original repo's scheduling/output commits automatically.

## Evidence so far

- Original public baseline: 247 tests passed; original source baseline: 279 tests passed.
- Before integration, the new source WATCH regression fails against public v1.1.4 with REJECT instead of C_SPECULATIVE.
- Combined engine first run: 314 passed, 2 failed because retirement-only public None was interpreted as missing issuance quantity. The generalized fix excludes issuance_type=NONE from that reason while preserving all other uncertainty reasons. Combined engine then: 316 passed.
- Release identity/version tests first failed (resolver absent, module version 1.1.1 vs project 1.1.4); implementation then passed all 8. Publication orchestration tests: 6 passed.
- Root release.json was an outdated static generated copy. It is no longer version-controlled; immutable assets are generated from the exact tested release commit.

- Pre-review verification: 324 Python tests and 6 Node publication tests passed. Wheel build succeeded. A real v1.1.4 checkout archive was used as an installed skill bundle; its old updater accepted the new local manifest, validated all managed hashes, preserved watchlist/overrides/output/SEC_USER_AGENT, and loaded the new engine from a fresh interpreter. This fixture uses local transport for the not-yet-published release; it is not a live SEC scan.
