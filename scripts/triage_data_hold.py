"""Reproducible, non-authoritative DATA_HOLD blocker triage.

Counts describe source warnings; they NEVER change gates or SAFE_TO_ACT.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

PATTERNS = {
    "security_class_unverified": ("listed security type is not verified",),
    "preferred_shares_unresolved": ("unresolved share quantity for preferred",),
    "ordinary_warrants_unresolved": ("unresolved share quantity for ordinary warrants",),
    "stock_awards_unresolved": ("unresolved outstanding stock awards",),
    "dilution_quantity_unresolved": (
        "material dilution language found but no reliable share quantity extracted",
    ),
    "fd_reconciliation": (
        "fd reconciliation", "fully diluted", "cap table confidence",
        "post-transaction fd", "share units require reconciliation",
    ),
}


def triage(path: Path) -> dict:
    counts = Counter()
    status_counts = Counter()
    held = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        needed = {"ticker", "gate_status", "security_type", "data_warnings"}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("Missing triage columns: " + ", ".join(sorted(needed - set(reader.fieldnames or []))))
        for row in reader:
            status = row["gate_status"]
            status_counts[status] += 1
            if status != "DATA_HOLD":
                continue
            warning = (row["data_warnings"] or "").lower()
            reasons = sorted(
                name for name, phrases in PATTERNS.items()
                if any(phrase in warning for phrase in phrases)
            )
            if row["security_type"] == "UNKNOWN":
                reasons = sorted(set(reasons + ["security_class_unverified"]))
            if not reasons:
                reasons = ["other_or_gate_only"]
            counts.update(reasons)
            held.append({
                "ticker": row["ticker"],
                "security_type": row["security_type"],
                "blockers": reasons,
            })
    if not status_counts:
        raise ValueError("Empty candidates.csv")
    if len(held) != status_counts["DATA_HOLD"]:
        raise ValueError("DATA_HOLD row count mismatch")
    return {
        "source": path.name,
        "total_candidates": sum(status_counts.values()),
        "gate_counts": dict(sorted(status_counts.items())),
        "data_hold_candidates": len(held),
        "blocker_counts_overlapping": dict(sorted(counts.items())),
        "note": "Blocker groups overlap; warning heuristics do not certify resolution or modify trading gates.",
        "held_candidates": held,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = triage(args.out / "candidates.csv")
    target = args.out / "data_hold_triage.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "held_candidates"}, indent=2))


if __name__ == "__main__":
    main()
