"""Plan a conservative SEC delta scan from a verified prior Actions artifact.

Artifacts are ephemeral: missing, expired, corrupt or discontinuous state always
falls back to a full scan. No prior report is ever treated as a fresh gate.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


def utc_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def full_plan(days, reason):
    return {"mode": "full", "days": days, "reason": reason,
            "baseline_run_id": None, "baseline_completed_at_utc": None,
            "last_full_run_id": None, "last_full_completed_at_utc": None}


def plan_scan(baseline: Path, *, expected_run_id: str, requested_mode: str,
              requested_days: int, trigger: str, now: datetime | None = None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if requested_days not in (1, 3, 7, 14, 30):
        raise ValueError("Unsupported SEC lookback")
    if requested_mode not in ("auto", "full"):
        raise ValueError("Unsupported scan mode")
    if requested_mode == "full":
        return full_plan(requested_days, "operator_full")
    # Force a weekly complete audit on the Monday evening KST schedule.
    kst = now.astimezone(ZoneInfo("Asia/Seoul"))
    if trigger == "schedule" and kst.weekday() == 0 and kst.hour >= 20:
        return full_plan(requested_days, "weekly_full")
    if requested_days < 3:
        return full_plan(requested_days, "short_manual_lookback")
    try:
        meta = json.loads((baseline / "run_metadata.json").read_text(encoding="utf-8"))
        quality = json.loads((baseline / "quality.json").read_text(encoding="utf-8"))
        if (not expected_run_id or meta["run_id"] != str(expected_run_id)
                or meta["scan_status"] != "SUCCESS"
                or type(quality["candidate_count"]) is not int
                or type(quality["SAFE_TO_ACT"]) is not bool):
            raise ValueError("Untrusted baseline")
        completed = utc_time(meta["completed_at_utc"])
        age = now - completed
        if not timedelta(0) < age <= timedelta(days=5):
            raise ValueError("Baseline outside continuous overlap window")
        last_full_time = meta.get("last_full_completed_at_utc")
        last_full_run = meta.get("last_full_run_id")
        if meta.get("scan_mode", "full") == "full":
            last_full_time = meta["completed_at_utc"]
            last_full_run = meta["run_id"]
        if not last_full_time or not last_full_run:
            raise ValueError("No trusted full-scan anchor")
        if now - utc_time(last_full_time) >= timedelta(days=7):
            raise ValueError("Full-scan anchor expired")
        with (baseline / "candidates.csv").open(encoding="utf-8-sig", newline="") as f:
            candidates = list(csv.DictReader(f))
        if len(candidates) != quality["candidate_count"]:
            raise ValueError("Baseline candidate count mismatch")
        # Two calendar days of overlap, never less than three days total.
        days = max(3, min(7, math.ceil(age.total_seconds() / 86400) + 2))
        return {"mode": "incremental", "days": days, "reason": "continuous_overlap",
                "baseline_run_id": meta["run_id"],
                "baseline_completed_at_utc": meta["completed_at_utc"],
                "last_full_run_id": str(last_full_run),
                "last_full_completed_at_utc": last_full_time}
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return full_plan(requested_days, "missing_or_invalid_baseline")


def write_watchlist(baseline: Path, original: Path, output: Path, mode: str):
    tickers = {}
    if original.is_file():
        with original.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ticker = (row.get("ticker") or "").strip().upper()
                if ticker:
                    tickers[ticker] = "operator"
    if mode == "incremental":
        with (baseline / "candidates.csv").open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("gate_status") in ("PASS", "WATCH"):
                    ticker = (row.get("ticker") or "").strip().upper()
                    if ticker:
                        tickers[ticker] = "prior_pass_watch_refresh"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "reason"])
        for ticker in sorted(tickers):
            writer.writerow([ticker, tickers[ticker]])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--expected-run-id", default="")
    p.add_argument("--requested-mode", choices=("auto", "full"), default="auto")
    p.add_argument("--requested-days", type=int, default=7)
    p.add_argument("--trigger", default="workflow_dispatch")
    p.add_argument("--original-watchlist", type=Path, default=Path("config/watchlist.csv"))
    p.add_argument("--watchlist", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--github-output", type=Path)
    args = p.parse_args()
    plan = plan_scan(args.baseline, expected_run_id=args.expected_run_id,
                     requested_mode=args.requested_mode, requested_days=args.requested_days,
                     trigger=args.trigger)
    write_watchlist(args.baseline, args.original_watchlist, args.watchlist, plan["mode"])
    args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as f:
            f.write(f"mode={plan['mode']}\ndays={plan['days']}\n")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
