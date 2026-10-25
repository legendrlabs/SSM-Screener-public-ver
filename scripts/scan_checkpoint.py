"""Select an authenticated, fresh, same-repository SSM scan checkpoint.

Missing, expired, corrupt, or unverifiable checkpoints trigger a full scan.
Do not treat a past full result as a fresh scan or publish saved contacts.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from urllib.parse import urlsplit
import zipfile

WORKFLOW = "sec-scan.yml"
REQUIRED = {"run_metadata.json", "quality.json", "seen_filings.json"}


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def choose_mode(requested, schedule):
    if requested == "full" or schedule == "30 11 * * 1":
        return "full"
    return "auto"


def verify_checkpoint(meta, seen, quality, run, now):
    if meta.get("scan_status") != "SUCCESS" or meta.get("run_id") != str(run["id"]):
        raise ValueError("Invalid run identity or completion status")
    if meta.get("source_commit") != run["head_sha"]:
        raise ValueError("Checkpoint source commit mismatch")
    if type(quality.get("SAFE_TO_ACT")) is not bool:
        raise ValueError("Checkpoint quality missing SAFE_TO_ACT")
    if seen.get("schema_version") != 1 or not isinstance(seen.get("entries"), dict):
        raise ValueError("No compatible seen-filing ledger")
    if seen.get("run_id") != str(run["id"]):
        raise ValueError("Seen ledger run identity mismatch")
    completed = utc(meta["completed_at_utc"])
    last_full = utc(meta["last_full_completed_at_utc"])
    if (now - completed).total_seconds() < 0 or (now - completed).total_seconds() > 36 * 3600:
        raise ValueError("Last successful checkpoint too old or dated in future")
    if (now - last_full).total_seconds() < 0 or (now - last_full).total_seconds() > 7 * 86400:
        raise ValueError("Full baseline too old")
    if seen.get("last_full_completed_at_utc") != meta.get("last_full_completed_at_utc"):
        raise ValueError("Checkpoint baseline identity mismatch")
    if type(meta.get("last_full_lookback_days")) is not int or meta["last_full_lookback_days"] < 7:
        raise ValueError("Full checkpoint does not cover at least seven days")
    if seen.get("last_full_lookback_days") != meta["last_full_lookback_days"]:
        raise ValueError("Checkpoint baseline lookback mismatch")
    return completed, last_full


class SafeArtifactRedirect(urllib.request.HTTPRedirectHandler):
    """Do not send GITHUB_TOKEN to signed artifact download hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urlsplit(req.full_url).hostname != urlsplit(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


def api(url, token):
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                      "User-Agent": "SSM-operator-checkpoint/1"})
    try:
        with urllib.request.build_opener(SafeArtifactRedirect()).open(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # Only log GitHub API stage and numeric status; never log signed URLs or credentials.
        path = urlsplit(url).path
        stage = ("artifact_download" if "/actions/artifacts/" in path else
                 "run_artifacts" if "/actions/runs/" in path else "workflow_runs")
        print(json.dumps({"checkpoint_api_stage": stage, "http_status": exc.code}))
        raise


def find_checkpoint(repo, token, now):
    runs = json.loads(api(
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
        "?status=success&branch=main&per_page=10", token))
    for run in runs.get("workflow_runs", []):
        # Only completed scans from this canonical repository/main may be reused.
        if run.get("conclusion") != "success" or (run.get("head_repository") or {}).get("full_name", repo) != repo:
            continue
        run_id = run["id"]
        try:
            arts = json.loads(api(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=30", token))
            art = next((a for a in arts.get("artifacts", [])
                        if a.get("name") == f"ssm-sec-scan-{run_id}" and not a.get("expired")), None)
            if art is None:
                print(json.dumps({"checkpoint_skip_run_id": run_id, "reason": "artifact_missing_or_expired"}))
                continue
            raw = api(f"https://api.github.com/repos/{repo}/actions/artifacts/{art['id']}/zip", token)
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if not REQUIRED.issubset(z.namelist()):
                    raise ValueError("Missing checkpoint files")
                meta = json.loads(z.read("run_metadata.json"))
                seen = json.loads(z.read("seen_filings.json"))
                quality = json.loads(z.read("quality.json"))
            verify_checkpoint(meta, seen, quality, run, now)
            return run_id, meta, seen
        except (ValueError, OSError, KeyError, TypeError, UnicodeError,
                urllib.error.URLError, zipfile.BadZipFile) as exc:
            # Skip a broken artifact, not all older verified checkpoints.
            failure = {"checkpoint_skip_run_id": run_id, "reason": type(exc).__name__}
            if isinstance(exc, urllib.error.HTTPError):
                failure["http_status"] = exc.code
            print(json.dumps(failure))
    raise ValueError("No verified recent scan artifact")


def plan(requested, schedule, *, repo=None, token=None, now=None, checkpoint=None):
    now = now or datetime.now(timezone.utc)
    if choose_mode(requested, schedule) == "full":
        return {"mode": "full", "days": 7, "reason": "manual_or_weekly_full", "source_run_id": None}
    try:
        if checkpoint is not None:
            run_id, meta, seen = checkpoint
        else:
            if not repo or not token:
                raise ValueError("Checkpoint API configuration unavailable")
            run_id, meta, seen = find_checkpoint(repo, token, now)
        # A bounded overlap covers late discovery near UTC/KST filing boundaries.
        completed = utc(meta["completed_at_utc"])
        gap_days = (now - completed).total_seconds() / 86400
        if not 0 <= gap_days <= 1.5:
            raise ValueError("Checkpoint age outside incremental window")
        days = max(2, min(3, int(gap_days) + 2))
        return {"mode": "incremental", "days": days, "reason": "recent_verified_checkpoint",
                "source_run_id": str(run_id)}
    except (ValueError, OSError, KeyError, TypeError, urllib.error.URLError, zipfile.BadZipFile,
            json.JSONDecodeError) as exc:
        return {"mode": "full", "days": 7, "reason": "checkpoint_unavailable_or_stale",
                "source_run_id": None, "fallback_type": type(exc).__name__}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--requested", choices=["full", "incremental", "auto"], default="auto")
    p.add_argument("--schedule", default="")
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    mode = choose_mode(args.requested, args.schedule)
    if mode == "full":
        result = plan(mode, args.schedule, now=now)
    else:
        try:
            if not os.environ.get("GH_TOKEN"):
                raise ValueError("Checkpoint API configuration unavailable")
            # Select once: avoid downloading the same ZIP twice or racing a new run.
            checkpoint = find_checkpoint(args.repo, os.environ["GH_TOKEN"], now)
            result = plan(mode, args.schedule, now=now, checkpoint=checkpoint)
            if result["mode"] == "incremental":
                _, _, seen = checkpoint
                (args.out / "prior_seen_filings.json").write_text(
                    json.dumps(seen), encoding="utf-8")
        except (ValueError, OSError, KeyError, TypeError, UnicodeError,
                urllib.error.URLError, zipfile.BadZipFile) as exc:
            result = {"mode": "full", "days": 7, "reason": "checkpoint_unavailable_or_stale",
                      "source_run_id": None, "fallback_type": type(exc).__name__}
            if isinstance(exc, urllib.error.HTTPError):
                result["fallback_http_status"] = exc.code
    (args.out / "scan_plan.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
