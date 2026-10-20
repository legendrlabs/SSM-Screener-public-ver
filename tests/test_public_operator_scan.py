"""Public operator workflow must be safe, reproducible, and visibly audited."""
from pathlib import Path
import json
import pytest

from scripts.verify_scan_outputs import REQUIRED, verify

ROOT = Path(__file__).resolve().parents[1]


def test_operator_workflow_manual_and_kst_cron_and_read_only():
    source = (ROOT / ".github/workflows/sec-scan.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "cron: '30 11 * * 1'" in source
    assert "cron: '30 11 * * 2-5'" in source
    assert "cron: '30 22 * * 1-5'" in source
    assert "contents: read" in source
    assert "secrets.SEC_USER_AGENT" in source
    assert "SSM_SEC_DISCOVERY_MODE: atom" in source
    assert "scripts/run_ssm.py scan" in source
    assert "scripts/scan_checkpoint.py" in source
    assert "incremental-state" in source
    assert "actions: read" in source
    assert "actions/upload-artifact@v4" in source
    assert "retention-days: 7" in source
    assert "persist-credentials: false" in source
    assert "git push" not in source and "git add " not in source
    assert "cancel-in-progress: false" in source


def sample_report(folder, **updates):
    folder.mkdir()
    q = {"SAFE_TO_ACT": False, "candidate_count": 2, "pass_count": 0,
         "watch_count": 1, "data_hold_count": 1, "reject_count": 0,
         "excluded_count": 0, "watch_reported_count": 1,
         "gate_bucket_mismatch_count": 0}
    q.update(updates)
    for name in REQUIRED:
        (folder / name).write_text("# Special Situation Microcap — latest\n"
                                   if name == "latest.md" else "", encoding="utf-8")
    (folder / "quality.json").write_text(json.dumps(q), encoding="utf-8")
    return folder


def test_good_data_hold_scan_is_valid_and_dated(tmp_path):
    result = verify(sample_report(tmp_path / "good"), run_id="1234", commit="abcd",
                    trigger="workflow_dispatch", days=7)
    assert result["scan_status"] == "SUCCESS"
    assert result["SAFE_TO_ACT"] is False
    assert result["watch_count"] == 1
    saved = json.loads((tmp_path / "good/run_metadata.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == "1234" and saved["days"] == 7


def test_inconsistent_counts_do_not_publish(tmp_path):
    folder = sample_report(tmp_path / "bad", candidate_count=9)
    with pytest.raises(ValueError, match="count total"):
        verify(folder, run_id="1", commit="abcd", trigger="schedule", days=7)
    assert not (folder / "run_metadata.json").exists()


def test_missing_report_cannot_be_marked_success(tmp_path):
    folder = sample_report(tmp_path / "missing")
    (folder / "event_ledger.csv").unlink()
    with pytest.raises(ValueError, match="missing event_ledger"):
        verify(folder, run_id="1", commit="abcd", trigger="schedule", days=7)
