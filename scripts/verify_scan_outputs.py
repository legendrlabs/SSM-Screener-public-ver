"""Check SSM operator scan completeness without changing its trading gates.

Reports remain artifacts, not tracked files in the public skill-distribution
repository. An engine returning SAFE_TO_ACT=false is a valid scan.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

REQUIRED = (
    "quality.json",
    "latest.md",
    "candidates.csv",
    "dilution_check.csv",
    "event_ledger.csv",
    "validation_audit.json",
)
CATEGORIES = ("pass_count", "watch_count", "data_hold_count", "reject_count", "excluded_count")


def verify(out: Path, *, run_id: str, commit: str, trigger: str, days: int) -> dict:
    missing = [name for name in REQUIRED if not (out / name).is_file()]
    if missing:
        raise ValueError("Incomplete scan: missing " + ", ".join(missing))
    report = (out / "latest.md").read_text(encoding="utf-8")
    if not report.startswith("# Special Situation Microcap"):
        raise ValueError("Invalid or missing latest.md report heading")
    quality = json.loads((out / "quality.json").read_text(encoding="utf-8"))
    if type(quality.get("SAFE_TO_ACT")) is not bool:
        raise ValueError("SAFE_TO_ACT must be boolean")
    counts = [quality.get(k) for k in CATEGORIES + ("candidate_count",)]
    if any(type(v) is not int or v < 0 for v in counts):
        raise ValueError("Missing or invalid candidate counts")
    if sum(quality[k] for k in CATEGORIES) != quality["candidate_count"]:
        raise ValueError("Gate count total does not match candidate_count")
    if quality.get("gate_bucket_mismatch_count", 0) != 0:
        raise ValueError("Gate/bucket mismatch: scan needs review")
    if quality.get("watch_reported_count", quality["watch_count"]) != quality["watch_count"]:
        raise ValueError("WATCH report disagrees with quality.json")
    completed_at_utc = datetime.now(timezone.utc).isoformat()
    scope = quality.get("scan_scope", "FULL")
    if scope not in ("FULL", "INCREMENTAL_DELTA"):
        raise ValueError("Unsupported scan scope")
    seen_file = out / "seen_filings.json"
    if quality.get("scan_scope") and not seen_file.is_file():
        raise ValueError("Completed scan is missing seen_filings.json checkpoint")
    seen = json.loads(seen_file.read_text(encoding="utf-8")) if seen_file.is_file() else None
    if seen is not None:
        if seen.get("schema_version") != 1 or not isinstance(seen.get("entries"), dict):
            raise ValueError("Invalid seen-filing ledger")
        if seen.get("run_id") not in (None, str(run_id)):
            raise ValueError("Seen ledger run identity mismatch")
        if scope == "INCREMENTAL_DELTA":
            if not seen.get("last_full_completed_at_utc") or not quality.get("incremental_source_run_id"):
                raise ValueError("Incremental scan missing previous verified baseline")
            if "INCREMENTAL DELTA ONLY" not in report:
                raise ValueError("Delta report must identify incomplete market coverage")
            last_full = seen["last_full_completed_at_utc"]
        else:
            last_full = completed_at_utc
        seen["run_id"] = str(run_id)
        seen["last_full_completed_at_utc"] = last_full
        seen_file.write_text(json.dumps(seen, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    else:
        last_full = completed_at_utc
    metadata = {
        "scan_scope": scope,
        "last_full_completed_at_utc": last_full,
        "checkpoint_source_run_id": quality.get("incremental_source_run_id"),
        "new_filing_count": quality.get("new_filing_count"),
        "discovered_filing_count": quality.get("discovered_filing_count"),
        "scan_status": "SUCCESS",
        "run_id": str(run_id),
        "source_commit": commit,
        "trigger": trigger,
        "days": days,
        "completed_at_utc": completed_at_utc,
        "SAFE_TO_ACT": quality["SAFE_TO_ACT"],
        **{k: quality[k] for k in (*CATEGORIES, "candidate_count")},
    }
    (out / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--trigger", required=True)
    p.add_argument("--days", required=True, type=int)
    args = p.parse_args()
    summary = verify(args.out, run_id=args.run_id, commit=args.commit,
                     trigger=args.trigger, days=args.days)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## SSM verified SEC scan\n\n")
            f.write(f"- Run: `{summary['run_id']}` / source: `{summary['source_commit'][:12]}`\n")
            f.write(f"- Lookback: {summary['days']} days; trigger: {summary['trigger']}\n")
            f.write(f"- Scope: **{summary['scan_scope']}**; last full: {summary['last_full_completed_at_utc']}\n")
            if summary["scan_scope"] == "INCREMENTAL_DELTA":
                f.write("- **DELTA ONLY:** totals do not represent the whole active universe.\n")
            f.write(f"- SAFE_TO_ACT: **{summary['SAFE_TO_ACT']}**\n")
            f.write(f"- PASS: {summary['pass_count']}, WATCH: {summary['watch_count']}, "
                    f"DATA_HOLD: {summary['data_hold_count']}\n")
            f.write("- Download the 7-day run artifact for full source-linked results.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
