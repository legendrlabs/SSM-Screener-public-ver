# Public SSM scheduled operations (v1.1.5 engine)

This is an optional **public scan and reporting channel**, separate from the ChatGPT/Codex skill bundle.
The release version/tag and the skill's bundled engine remain unchanged by this workflow.
Source of truth for installing/updating the skill remains the immutable GitHub Release.

## Scheduled and manual execution

- The public repository's `.github/workflows/daily-scan.yml` runs Mon–Fri at **11:30 and 22:30 UTC**
  (respectively 20:30 KST Mon–Fri and 07:30 KST Tue–Sat).
- GitHub Actions schedules are best-effort: actual job starts may be delayed.
- A manual run is available from **Actions > SSM Daily Scan > Run workflow**, on `main`.
- To trigger via a code change without the Actions UI, commit a new harmless text file in
  `.scan-trigger/` on `main`. Other pushes do not trigger a scan.

## Configuration

1. Go to **Settings > Secrets and variables > Actions** in this public repository.
2. Add a repository secret named `SEC_USER_AGENT` with a **real ASCII contact name and
   reachable email address** for SEC EDGAR requests. Do not put this value in a repository file.
3. Ensure GitHub Actions is enabled, and that workflow `GITHUB_TOKEN` is allowed to write
   repository contents. Branch protections/rulesets may require exceptions or a different
   publication method. The workflow explicitly requests `contents: write`; the actual
   repository policy still controls whether pushing to `main` succeeds.
4. Verify the first scan and publication before depending on automated updates.

Do not copy secrets, old private `watchlist.csv`, old private overrides, the former
repo's `.scan-trigger` files, or old scan data into this public repository. Its default
watchlist and overrides are intentionally empty.

## Success requirements and public files

A scheduled scan is complete only if SEC/market acquisition and the engine succeed.
The workflow then uploads a run-scoped artifact and runs
`python scripts/publish_outputs.py` to publish this single synchronized snapshot to
`main` under `output/`:

- `quality.json` (includes `source_commit`, `workflow_run_id`, `generated_at`)
- `candidates.csv`
- `dilution_check.csv`
- `event_ledger.csv`
- `latest.md`
- `validation_audit.json` when produced

Publication checks that all five required files exist and blocks an older
source commit or older workflow run from overwriting newer published output.
Output-only commits do not retrigger the scan or the CI test suite.

**Important:** GitHub Actions `success` proves that execution and publication
steps completed, not that `SAFE_TO_ACT=true` or any ticker is actionable.
Read `quality.json` with each `latest.md`; do not infer availability from older
published output or claim that a live SEC scan was performed in ChatGPT.

## ChatGPT use without relying on skill attachment

Open the connected GitHub repository `legendrlabs/SSM-Screener-public-ver`, then
read `output/quality.json` and `output/latest.md` from the same source commit
and run. If either is absent, report DATA_HOLD/NO CURRENT SCAN rather than
substituting previous research. A managed ChatGPT skill attachment is a separate
integration, not a prerequisite for reading published GitHub scan results.
