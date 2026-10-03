---
name: special-situation-microcap
description: Run the bundled SSM Screener for U.S. stock special situations and dilution checks. Use for SSM 점검, 특수상황 스크리닝, SEC 8-K 분석, 합병 대가, 청산배당, or ticker dilution review. Fetch current SEC and market data and report fully diluted economics with PASS/WATCH/REJECT/DATA_HOLD gates.
---

# Special Situation Microcap Screener

## Purpose

Find U.S.-listed microcap special situations where market price may not yet reflect a verified structural change. This skill is a **screening and research-triage workflow**, not a trade recommendation engine.

## Run the bundled engine

Use the Python engine in this installed skill for scans and ticker checks. Treat the absolute directory containing this `SKILL.md` as `SKILL_DIR`; do not assume the chat working directory is the skill directory. This bundle includes `pyproject.toml`, `scripts/run_ssm.py`, `ssm/`, and empty user configurations.

1. Select an available Python 3.11+ interpreter in the execution environment. Use the same interpreter for setup and execution. Check that `requests`, `pandas`, and `yfinance` can be imported. If missing, install dependencies from this bundle with that interpreter: `python -m pip install "<SKILL_DIR>"`. Follow the host's installation permissions. This installs the CLI dependencies; it does not itself install a ChatGPT skill.
2. Before every user-requested `scan` or `check`, run `python "<SKILL_DIR>/scripts/run_ssm.py" version`. If `update_available=true`, tell the user the current and latest versions and ask in natural language whether to update before continuing. Do **not** require the literal reply `y` or `n`: treat any clear affirmative reply in the user's language such as `yes`, `y`, `ㅇㅇ`, `ㄱㄱ`, `해줘`, `진행`, or `go ahead` as approval, and clear refusals such as `no`, `아니`, `그냥 체크해`, or `업데이트는 나중에` as decline. Do not infer approval merely from the original scan/check request. On approval, run `python "<SKILL_DIR>/scripts/run_ssm.py" update`; after a successful update, rerun the originally requested scan/check so the updated code handles the request. On decline, continue the requested scan/check with the installed version. If the update fails, report the concrete error and current version; never claim the update succeeded. In non-interactive automation where user confirmation cannot be obtained, do not invent approval and do not block waiting for terminal input.
3. Before live SEC requests, check `SEC_USER_AGENT` without printing its value. If absent, ask the user once for a contact name and email for SEC access, and set it in the execution environment. Use ASCII characters. Never invent an email, embed contact details in source, or copy another user's contact. Preserve an existing configured value. Set `SSM_SEC_DISCOVERY_MODE=atom` for cloud execution.
4. For a whole-universe request, run `python "<SKILL_DIR>/scripts/run_ssm.py" scan --days 7 --out "<TASK_DIR>/ssm-output"`. For named tickers, run `python "<SKILL_DIR>/scripts/run_ssm.py" check GPRO LFCR --out "<TASK_DIR>/ssm-output"`, replacing the example symbols with the user's requested symbols. Set the requested scan window with `--days` when specified. `TASK_DIR` is the current writable task workspace. Do not write private results into this public repository.
5. Read the generated files from the chosen output directory in the order specified below. Report the actual run date, relevant filing dates and source links. Distinguish issuer-disclosed capital quantities from independently reconciled fully diluted calculations.
6. If setup, network access, SEC retrieval or the run fails, explain the concrete failure and report DATA_HOLD. Do not substitute guessed numbers, present a previous result as a fresh scan, or claim the engine ran when it did not. A zero-candidate successful run is NO CANDIDATE; an unavailable run is DATA_HOLD.

Check `python "<SKILL_DIR>/scripts/run_ssm.py" --help` to verify the entry point. Full SEC scans may take time; use the host's background execution/polling tools when available and keep the user informed.

When reviewing output differences or maintaining this engine, follow `docs/stabilization-policy.md`: classify practical impact first, fix material economics/security/lifecycle/candidate errors through general rules, and avoid ticker-specific overrides.

## Non-negotiables

1. Use current SEC filings and current market data. Never rely on remembered price, shares outstanding, float, or financing terms.
2. Primary-source hierarchy: SEC filing/exchange notice → issuer IR exhibit → market-data provider → reputable secondary news.
3. Never use basic market cap alone when material pre-funded warrants, warrants, converts, preferreds, merger consideration, earnouts, or SBC exist.
4. If fully diluted economics cannot be reconstructed with reasonable confidence, output `DATA_HOLD`.
5. For asset-backed theses, calculate `mark-to-market asset value / fully diluted market cap`.
6. Non-binding LOIs and announced-but-unclosed asset transfers are not current assets.
7. A large contract headline is not revenue. Distinguish signed TCV, deposits, deployed assets, go-live, recognized revenue, and gross margin.
8. If the move already occurred, separate pre-move evidence, remaining current thesis, and momentum/squeeze/low-float effects.
9. Maximum five live candidates. Do not fill the list artificially.
10. If no candidate passes, state `NO CANDIDATE`.

## Deterministic status

- `PASS` — hard gates passed; deeper-research candidate.
- `WATCH` — thesis exists but event proof, liquidity, or dilution remains incomplete.
- `REJECT` — structural issue overwhelms the current thesis.
- `DATA_HOLD` — material data cannot be verified.

`PASS` means research priority, not a buy signal.

## Event proof hierarchy

- 0: rumor / promotional language / thematic mention
- 1: strategic review / preliminary / non-binding LOI
- 2: binding contract / definitive agreement / SPA
- 3: closed / funded / asset received
- 4: operating / go-live / recognized revenue

For announced asset transfers, do not include the asset in NAV before level 3.

## Required calculations

Always attempt to produce:

- `BASIC_SHARES`
- `NEAR_FD_SHARES`
- `STRICT_FD_SHARES`
- `BASIC_MC`
- `NEAR_FD_MC`
- `STRICT_FD_MC`
- `FD_RATIO`
- `ATM_RATIO`
- `NAV_COVERAGE` where relevant
- `ADV20`
- `EVENT_PROOF`
- `NEXT_CATALYST`

If cap-table confidence is low, do not guess; emit `DATA_HOLD`.

## SEC discovery modes

- `atom`: use on GitHub-hosted/public environments; discover filings via the official SEC Atom feed, then verify with submissions/companyfacts and the primary filing document.
- `daily-index`: use on local/self-hosted environments when EDGAR master-index access is available.
- `auto`: try daily-index first and fall back to Atom on HTTP 403.

The evidence standard is unchanged. If filing text or dilution terms cannot be verified, keep the candidate at `DATA_HOLD`.

## 10-Q/10-K second pass

Event discovery does not replace financial review. For each candidate, resolve and read the latest 10-Q or 10-K primary document and inspect warrants, pre-funded warrants, converts, preferreds, ATM/equity lines, SBC/RSUs, going concern, related-party items, subsequent events, debt and equity notes.

If the latest 10-Q/10-K body cannot be reviewed, keep the candidate at `DATA_HOLD`. When the same instrument appears in both the event filing and the financial filing, do not blindly add the share equivalents; use conservative non-duplicative reconciliation.

## Runtime output order

When generated output files exist, read:

1. `output/quality.json`
2. `output/candidates.csv`
3. `output/dilution_check.csv`
4. `output/event_ledger.csv`
5. `output/latest.md`

If `SAFE_TO_ACT=false`, do not promote a ticker to PASS.

## Candidate review questions

For every surviving ticker answer:

1. What is the market currently treating this company as?
2. What is the company actually becoming?
3. What number may be missed?
4. Is that number large enough to matter?
5. Does dilution erase the apparent discount?
6. Would the thesis have existed three months earlier?
7. Does a reason remain at today's price?

## Final sections

- 오늘의 1순위
- 관찰만 할 종목
- 이미 늦은 종목
- 절대 건드리지 말 종목

These are research-priority buckets, not personalized investment instructions.
