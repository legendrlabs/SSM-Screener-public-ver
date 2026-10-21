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
    metadata = {
        "scan_status": "SUCCESS",
        "scan_mode": "full",
        "last_full_run_id": str(run_id),
        "last_full_completed_at_utc": None,
        "run_id": str(run_id),
        "source_commit": commit,
        "trigger": trigger,
        "days": days,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "SAFE_TO_ACT": quality["SAFE_TO_ACT"],
        **{k: quality[k] for k in (*CATEGORIES, "candidate_count")},
    }
    metadata["last_full_completed_at_utc"] = metadata["completed_at_utc"]
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
            f.write(f"- SAFE_TO_ACT: **{summary['SAFE_TO_ACT']}**\n")
            f.write(f"- PASS: {summary['pass_count']}, WATCH: {summary['watch_count']}, "
                    f"DATA_HOLD: {summary['data_hold_count']}\n")
            f.write("- Download the 7-day run artifact for full source-linked results.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
