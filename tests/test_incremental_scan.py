"""Incremental SEC scans must be accession-based and fail closed."""
from datetime import datetime, timedelta, timezone
import json
import io
import sys
import zipfile
from pathlib import Path
from urllib.request import Request

import pytest

from scripts import scan_checkpoint as checkpoint_module
from scripts.scan_checkpoint import plan, verify_checkpoint, SafeArtifactRedirect
from scripts.verify_scan_outputs import verify
from ssm import pipeline
from ssm.models import Candidate, Dilution


def test_unique_filing_id_includes_form_and_accession():
    one = {"cik": "000123", "form": "8-K", "accession": "0000000123-26-000001"}
    two = {**one, "accession": "0000000123-26-000002"}
    three = {**one, "form": "S-3"}
    assert pipeline._filing_key(one) != pipeline._filing_key(two)
    assert pipeline._filing_key(one) != pipeline._filing_key(three)


def test_full_then_incremental_filters_previously_scanned_accessions(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    old = {"cik": "123", "form": "8-K", "filed": today,
           "accession": "0000000123-26-000001", "items": "1.01"}
    new = {**old, "accession": "0000000123-26-000002"}
    class FakeSec:
        last_discovery_mode = "atom"
        def __init__(self):
            pass
        def recent_filings(self, days, forms):
            return [old, new]
        def enrich_filing(self, cik, raw):
            return raw

    meta = {"ticker": "DEMO", "cik": "123", "name": "Demo",
            "exchange": "Nasdaq", "security_type": "COMMON_EQUITY"}
    monkeypatch.setattr(pipeline, "SecClient", FakeSec)
    monkeypatch.setattr(pipeline, "_ticker_map", lambda sec: ({"123": [meta]}, {"DEMO": meta}))
    monkeypatch.setattr(pipeline, "resolve_security", lambda sec, m, f: m)
    monkeypatch.setattr(pipeline, "market_snapshots", lambda tickers: {})
    monkeypatch.setattr(pipeline, "build_candidate",
                        lambda sec, meta, filing, override, cfg, snapshot=None:
                        Candidate(ticker=meta["ticker"], cik=meta["cik"],
                                  gate_status="DATA_HOLD", bucket="DATA_HOLD",
                                  dilution=Dilution(confidence="low")))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"event_forms": ["8-K"], "exchanges": ["Nasdaq"], "material_8k_items": ["1.01"]}))
    full, details = pipeline.scan(7, str(cfg), str(tmp_path / "empty.csv"), str(tmp_path / "override.json"))
    assert len(full) == 1
    assert details["_scan_scope"] == "FULL"
    assert len(details["_seen_filings"]["entries"]) == 2
    # The new accession is not in the previous checkpoint; existing one is skipped.
    previous = {"schema_version": 1, "run_id": "111", "entries": {
        pipeline._filing_key(old): today
    }, "last_full_completed_at_utc": now.isoformat(), "last_full_lookback_days": 7}
    checkpoint = tmp_path / "seen.json"
    checkpoint.write_text(json.dumps(previous))
    delta, state = pipeline.scan(2, str(cfg), str(tmp_path / "empty.csv"),
                                 str(tmp_path / "override.json"), incremental_state_path=str(checkpoint))
    assert len(delta) == 1
    assert state["_scan_scope"] == "INCREMENTAL_DELTA"
    assert state["_incremental_source_run_id"] == "111"
    assert state["_new_filing_count"] == 1
    assert len(state["_seen_filings"]["entries"]) == 2
    # Replaying same input again must not create a new candidate.
    previous["entries"] = state["_seen_filings"]["entries"]
    checkpoint.write_text(json.dumps(previous))
    replay, state2 = pipeline.scan(2, str(cfg), str(tmp_path / "empty.csv"),
                                   str(tmp_path / "override.json"), incremental_state_path=str(checkpoint))
    assert not replay
    assert state2["_new_filing_count"] == 0


def test_fallback_without_valid_checkpoint_and_manual_full(tmp_path):
    assert plan("full", "", repo=None, token=None)["mode"] == "full"
    assert plan("auto", "30 11 * * 1", repo=None, token=None)["mode"] == "full"
    fallback = plan("incremental", "", repo=None, token=None)
    assert fallback["mode"] == "full"
    assert fallback["reason"] == "checkpoint_unavailable_or_stale"
    now = datetime.now(timezone.utc)
    meta = {"completed_at_utc": now.isoformat(), "last_full_completed_at_utc": now.isoformat()}
    chosen = plan("auto", "", now=now, checkpoint=("109", meta, {}))
    assert chosen["mode"] == "incremental"
    assert chosen["source_run_id"] == "109"
    assert chosen["days"] == 2
    stale = {**meta, "completed_at_utc": (now - timedelta(hours=40)).isoformat()}
    assert plan("auto", "", now=now, checkpoint=("109", stale, {}))["mode"] == "full"


def test_checkpoint_requires_matching_artifact_identity_and_full_baseline():
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    run = {"id": 100, "head_sha": "commitsha"}
    meta = {"run_id": "100", "source_commit": "commitsha", "scan_status": "SUCCESS",
            "completed_at_utc": stamp, "last_full_completed_at_utc": stamp,
            "last_full_lookback_days": 7}
    seen = {"schema_version": 1, "run_id": "100", "entries": {},
            "last_full_completed_at_utc": stamp, "last_full_lookback_days": 7}
    quality = {"SAFE_TO_ACT": False}
    assert verify_checkpoint(meta, seen, quality, run, now)[0] == now
    with pytest.raises(ValueError, match="identity"):
        verify_checkpoint({**meta, "run_id": "101"}, seen, quality, run, now)
    with pytest.raises(ValueError, match="seven days"):
        verify_checkpoint({**meta, "last_full_lookback_days": 1},
                          {**seen, "last_full_lookback_days": 1}, quality, run, now)


def test_delta_outputs_must_have_baseline_and_explicit_scope(tmp_path):
    q = {"SAFE_TO_ACT": False, "candidate_count": 0,
         "pass_count": 0, "watch_count": 0, "data_hold_count": 0,
         "reject_count": 0, "excluded_count": 0,
         "gate_bucket_mismatch_count": 0, "watch_reported_count": 0,
         "scan_scope": "INCREMENTAL_DELTA", "incremental_source_run_id": "prev"}
    for name in ("quality.json", "latest.md", "candidates.csv",
                 "dilution_check.csv", "event_ledger.csv", "validation_audit.json"):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "quality.json").write_text(json.dumps(q))
    (tmp_path / "latest.md").write_text("# Special Situation Microcap — latest\nINCREMENTAL DELTA ONLY")
    with pytest.raises(ValueError, match="seen_filings"):
        verify(tmp_path, run_id="next", commit="abc", trigger="schedule", days=2)
    seen = {"schema_version": 1, "run_id": "next", "entries": {},
            "last_full_completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "last_full_lookback_days": 7}
    (tmp_path / "seen_filings.json").write_text(json.dumps(seen))
    result = verify(tmp_path, run_id="next", commit="abc", trigger="schedule", days=2)
    assert result["scan_scope"] == "INCREMENTAL_DELTA"
    assert result["last_full_lookback_days"] == 7


def test_redirect_never_forwards_token_to_signed_artifact_host():
    handler = SafeArtifactRedirect()
    request = Request("https://api.github.com/repos/o/r/actions/artifacts/123/zip",
                      headers={"Authorization": "Bearer test-only", "Accept": "application/vnd.github+json"})
    signed = handler.redirect_request(request, None, 302, "Found", {},
                                      "https://example.blob.core.windows.net/signed?token=sample")
    assert signed.get_header("Authorization") is None
    assert signed.get_header("Accept") == "application/vnd.github+json"
    same_host = handler.redirect_request(request, None, 302, "Found", {},
                                         "https://api.github.com/other-api")
    assert same_host.get_header("Authorization") == "Bearer test-only"


def test_checkpoint_skips_broken_latest_artifact_and_verifies_older(monkeypatch):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    repo = "legendrlabs/SSM-Screener-public-ver"
    runs = [{"id": 202, "head_sha": "sha2", "conclusion": "success"},
            {"id": 201, "head_sha": "sha1", "conclusion": "success"}]
    meta = {"run_id": "201", "source_commit": "sha1", "scan_status": "SUCCESS",
            "completed_at_utc": stamp, "last_full_completed_at_utc": stamp,
            "last_full_lookback_days": 7}
    seen = {"schema_version": 1, "run_id": "201", "entries": {},
            "last_full_completed_at_utc": stamp, "last_full_lookback_days": 7}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in (("run_metadata.json", meta), ("seen_filings.json", seen),
                           ("quality.json", {"SAFE_TO_ACT": False})):
            z.writestr(name, json.dumps(data))
    def fake_api(url, token):
        if "/workflows/" in url:
            return json.dumps({"workflow_runs": runs}).encode()
        if "/runs/202/artifacts" in url:
            return json.dumps({"artifacts": [{"id": 302, "name": "ssm-sec-scan-202"}]}).encode()
        if "/runs/201/artifacts" in url:
            return json.dumps({"artifacts": [{"id": 301, "name": "ssm-sec-scan-201"}]}).encode()
        if "/artifacts/302/zip" in url:
            return b"not a zip"
        if "/artifacts/301/zip" in url:
            return archive.getvalue()
        raise AssertionError(url)
    monkeypatch.setattr(checkpoint_module, "api", fake_api)
    run_id, selected_meta, selected_seen = checkpoint_module.find_checkpoint(repo, "fake", now)
    assert run_id == 201
    assert selected_meta == meta and selected_seen == seen


def test_checkpoint_restore_calls_remote_lookup_only_once(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    meta = {"completed_at_utc": stamp, "last_full_completed_at_utc": stamp}
    seen = {"schema_version": 1, "entries": {"filing-1": "2026-10-23"}}
    calls = []
    def fake_checkpoint(repo, token, current):
        calls.append(repo)
        return 100, meta, seen
    monkeypatch.setattr(checkpoint_module, "find_checkpoint", fake_checkpoint)
    monkeypatch.setenv("GH_TOKEN", "test-only")
    monkeypatch.setattr(sys, "argv", ["scan_checkpoint.py", "--repo", "legendrlabs/SSM-Screener-public-ver",
                                      "--out", str(tmp_path)])
    checkpoint_module.main()
    assert calls == ["legendrlabs/SSM-Screener-public-ver"]
    planned = json.loads((tmp_path / "scan_plan.json").read_text())
    assert planned["mode"] == "incremental" and planned["source_run_id"] == "100"
    assert json.loads((tmp_path / "prior_seen_filings.json").read_text()) == seen
