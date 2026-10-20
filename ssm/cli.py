from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile

# Keep this module importable using only the Python standard library.
# The scanner, market providers and their optional dependencies are loaded only
# after argument parsing selects scan/check. Thin wrappers keep test injection
# points stable for bundled and console-script entrypoints.
def scan(*args, **kwargs):
    from .pipeline import scan as run_scan
    return run_scan(*args, **kwargs)


def write_outputs(*args, **kwargs):
    from .report import write_outputs as writer
    return writer(*args, **kwargs)


def version_status():
    from .updater import version_status as status
    return status()


def maybe_update_notice():
    from .updater import maybe_update_notice as notice
    return notice()


def perform_update(dry_run=False):
    from .updater import perform_update as update
    return update(dry_run)


def _restart_current_command() -> None:
    entrypoint = sys.argv[0]
    args = list(sys.argv[1:])
    if os.path.basename(entrypoint) == "run_ssm.py":
        command = [sys.executable, entrypoint, *args]
    else:
        command = [sys.executable, "-m", "ssm.cli", *args]
    os.execv(sys.executable, command)


def main():
    p = argparse.ArgumentParser(prog="ssm")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--config", default="config/default.json")
    s.add_argument("--watchlist", default="config/watchlist.csv")
    s.add_argument("--overrides", default="config/overrides.json")
    s.add_argument("--out", default="output")

    c = sub.add_parser("check")
    c.add_argument("tickers", nargs="+")
    c.add_argument("--days", type=int, default=60)
    c.add_argument("--config", default="config/default.json")
    c.add_argument("--overrides", default="config/overrides.json")
    c.add_argument("--out", default="output")

    v = sub.add_parser("version")
    v.add_argument("--offline", action="store_true", help="show local version without network access")
    u = sub.add_parser("update")
    u.add_argument("--dry-run", action="store_true")

    a = p.parse_args()

    if a.cmd == "version":
        if a.offline:
            from .updater import current_version
            status = {
                "current": current_version(), "latest": None,
                "update_available": None, "check_error": "OFFLINE_CHECK_SKIPPED"
            }
        else:
            status = version_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    if a.cmd == "update":
        print(json.dumps(perform_update(a.dry_run), ensure_ascii=False, indent=2))
        return

    if maybe_update_notice():
        _restart_current_command()
        return

    if a.cmd == "scan":
        candidates, cfg = scan(a.days, a.config, a.watchlist, a.overrides)
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ticker", "reason"])
            [w.writerow([t.upper(), "manual check"]) for t in a.tickers]
            tmp = f.name
        try:
            candidates, cfg = scan(a.days, a.config, tmp, a.overrides)
            wanted = {t.upper() for t in a.tickers}
            candidates = [x for x in candidates if x.ticker in wanted]
        finally:
            os.unlink(tmp)

    write_outputs(candidates, cfg, a.out)
    print(
        json.dumps(
            {
                "count": len(candidates),
                "A": [c.ticker for c in candidates if c.bucket == "A_RESEARCH_NOW"],
                "WATCH": [c.ticker for c in candidates if c.bucket in ("B_WATCH", "C_SPECULATIVE")],
                "DATA_HOLD": [c.ticker for c in candidates if c.bucket == "DATA_HOLD"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
