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

## Runtime diagnostics

The scan job allows 120 minutes. With `SSM_PROGRESS=1`, it writes timestamped phase, public SEC request/retry, issuer and candidate progress to stderr. Python output is unbuffered. The bundled runner also dumps the active Python stack every five minutes until the scan exits, so a network wait or parser stall is visible in Actions logs. These diagnostics never serialize request headers or secret values and are separate from validated result files.

Ownership form aliases share one accession identity within a run. Unlisted reporting persons beyond the ownership read budget are skipped before submissions enrichment, remain absent from the processed ledger, and count toward incomplete discovery coverage. Permanent HTTP 400/404 responses are not retried; throttling/access/server errors retain bounded retries. These runtime changes do not certify incomplete data or change investment gates.

## Discovery and result quality

The default configuration sets M&A acquirer/ownership read limits to `null`: review every relevant source returned by the configured SEC collection window. Explicit integer overrides still impose a visible budget (zero disables secondary reads). This removes the previous 80/100 count cutoff, but does not certify that SEC feed pagination or an upstream collection source covers every filing.

Unresolved tender sources are listed by accession/form/source/reason in `quality.json` and the report. They are removed from the processed ledger and retried when seen again. Tender proposal/press-release exhibits can supplement the primary filing. A discovered target receives a separate issuer-side merger completion review before microcap gating can conceal its common-share exit. Closing needs actual issuer common-share conversion evidence; a planned transaction, buyer asset purchase or note conversion does not prove that exit.

Repeated financial-note/MD&A records sharing an existing capital-event identity are one read-only record with evidence variants. Share/claim quantities are never added. Conflicting retirement extent or unresolved current evidence retains reconciliation requirements. Invariant violations or partial discovery always force `SAFE_TO_ACT=FALSE`; execution success and result quality are distinct. Inspect `quality_status`, coverage details and `validation_audit.json`.
