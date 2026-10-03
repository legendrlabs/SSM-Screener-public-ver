from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile

from .pipeline import scan
from .report import write_outputs
from .updater import maybe_update_notice, perform_update, version_status


def _restart_current_command() -> None:
    entrypoint = sys.argv[0]
    args = list(sys.argv[1:])
    if os.path.basename(entrypoint) == "cli.py":
        os.execv(sys.executable, [sys.executable, "-m", "ssm.cli", *args])
    else:
        os.execv(sys.executable, [sys.executable, entrypoint, *args])


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

    sub.add_parser("version")
    u = sub.add_parser("update")
    u.add_argument("--dry-run", action="store_true")

    a = p.parse_args()

    if a.cmd == "version":
        print(json.dumps(version_status(), ensure_ascii=False, indent=2))
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
