"""Opt-in operator diagnostics, separate from result JSON and investment gates."""
from datetime import datetime, timezone
import json
import os
import sys


def progress(stage, **fields):
    if os.getenv("SSM_PROGRESS") == "1":
        print(json.dumps({"ssm_progress": stage,
                          "at": datetime.now(timezone.utc).isoformat(), **fields},
                         ensure_ascii=False, default=str), file=sys.stderr, flush=True)
