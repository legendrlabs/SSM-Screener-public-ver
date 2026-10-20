"""Delta plans never silently rely on stale or missing baseline coverage."""
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from scripts.plan_incremental_scan import plan_scan, write_watchlist

NOW = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)


def baseline(tmp_path, *, when=None, run_id="123", gate="WATCH"):
    root = tmp_path / "previous"
    root.mkdir()
    stamp = (when or (NOW - timedelta(hours=12))).isoformat()
    (root / "run_metadata.json").write_text(json.dumps({
        "run_id": run_id, "scan_status": "SUCCESS",
        "completed_at_utc": stamp, "scan_mode": "full"}))
    (root / "quality.json").write_text(json.dumps({
        "candidate_count": 1, "SAFE_TO_ACT": False}))
    with (root / "candidates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "gate_status"])
        w.writeheader()
        w.writerow({"ticker": "ABCD", "gate_status": gate})
    return root


def plan(root, **kwargs):
    return plan_scan(root, expected_run_id="123", requested_mode="auto",
                     requested_days=7, trigger="workflow_dispatch", now=NOW, **kwargs)


def test_recent_success_uses_overlapping_delta_and_anchor(tmp_path):
    result = plan(baseline(tmp_path))
    assert result["mode"] == "incremental"
    assert result["days"] == 3
    assert result["last_full_run_id"] == "123"


def test_missing_or_mismatched_or_corrupt_baseline_is_full(tmp_path):
    assert plan(tmp_path)["mode"] == "full"
    root = baseline(tmp_path)
    assert plan_scan(root, expected_run_id="999", requested_mode="auto",
                     requested_days=7, trigger="workflow_dispatch", now=NOW)["mode"] == "full"
    (root / "quality.json").write_text("{}")
    assert plan(root)["mode"] == "full"


def test_expired_gap_falls_back_full(tmp_path):
    root = baseline(tmp_path, when=NOW - timedelta(days=6))
    assert plan(root)["mode"] == "full"


def test_operator_full_and_short_window(tmp_path):
    root = baseline(tmp_path)
    assert plan_scan(root, expected_run_id="123", requested_mode="full",
                     requested_days=14, trigger="workflow_dispatch", now=NOW)["days"] == 14
    assert plan_scan(root, expected_run_id="123", requested_mode="auto",
                     requested_days=1, trigger="workflow_dispatch", now=NOW)["mode"] == "full"


def test_weekly_full_for_monday_evening_kst(tmp_path):
    root = baseline(tmp_path)
    monday = datetime(2026, 10, 26, 11, 30, tzinfo=timezone.utc)
    result = plan_scan(root, expected_run_id="123", requested_mode="auto",
                       requested_days=7, trigger="schedule", now=monday)
    assert result["reason"] == "weekly_full"


def test_watchlist_deduplicates_prior_pass_watch_and_operator(tmp_path):
    root = baseline(tmp_path)
    original = tmp_path / "watch.csv"
    original.write_text("ticker,reason\nABCD,operator\nEFGH,operator\n")
    output = tmp_path / "merged.csv"
    write_watchlist(root, original, output, "incremental")
    with output.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["ticker"] for r in rows] == ["ABCD", "EFGH"]
    assert rows[0]["reason"] == "prior_pass_watch_refresh"


def test_rolling_incremental_keeps_original_full_anchor(tmp_path):
    root = baseline(tmp_path)
    meta_path = root / "run_metadata.json"
    meta = json.loads(meta_path.read_text())
    meta.update(scan_mode="incremental", last_full_run_id="50",
                last_full_completed_at_utc=(NOW - timedelta(days=6)).isoformat())
    meta_path.write_text(json.dumps(meta))
    assert plan(root)["mode"] == "incremental"
    meta["last_full_completed_at_utc"] = (NOW - timedelta(days=8)).isoformat()
    meta_path.write_text(json.dumps(meta))
    assert plan(root)["mode"] == "full"
