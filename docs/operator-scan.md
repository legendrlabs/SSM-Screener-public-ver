# Main scan operation

The operator workflow `.github/workflows/sec-scan.yml` runs on GitHub using the existing `SEC_USER_AGENT` Actions secret.

| Trigger | Mode | Lookback |
| --- | --- | --- |
| Daily 07:37 Asia/Seoul (`37 22 * * *` UTC) | Full | 7 days |
| Daily 20:37 Asia/Seoul (`37 11 * * *` UTC) | Incremental, or full when checkpoint verification fails | Checkpoint-derived; fallback full 7 days |
| Change `config/scan-request.json` on `main` | Full | 7 days |
| Actions Run workflow | Selected full/incremental | Selected manual full lookback |

To request a scan through the repository connector, update the request ID and reason in `config/scan-request.json` on `main`. Only this path triggers a push scan; ordinary source commits and changes on other branches do not. The contents are an audit note, never shell commands or workflow inputs. Verify a new `push` run of the SEC workflow for that commit before claiming the scan started. Requests are subject to GitHub workflow enablement, runner availability and concurrency. GitHub may delay scheduled runs; the times above are trigger targets, not completion deadlines.

A single concurrency group serializes all scan triggers. The runtime token retains read-only contents/actions permissions. Scans upload validated same-run artifacts and do not commit scan results. Existing checkpoint validation, financial gates and SAFE_TO_ACT remain unchanged.
