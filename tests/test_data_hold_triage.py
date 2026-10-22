"""DATA_HOLD diagnostic must not alter scan gate decisions."""
import csv
from scripts.triage_data_hold import triage


def test_triage_overlapping_blockers_and_counts(tmp_path):
    path = tmp_path / "candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "gate_status", "security_type", "data_warnings"])
        w.writeheader()
        w.writerow({"ticker": "AAA", "gate_status": "DATA_HOLD", "security_type": "UNKNOWN",
                    "data_warnings": "Unresolved share quantity for preferred shares."})
        w.writerow({"ticker": "BBB", "gate_status": "DATA_HOLD", "security_type": "COMMON_EQUITY",
                    "data_warnings": "Material dilution language found but no reliable share quantity extracted."})
        w.writerow({"ticker": "CCC", "gate_status": "REJECT", "security_type": "COMMON_EQUITY",
                    "data_warnings": ""})
    result = triage(path)
    assert result["total_candidates"] == 3
    assert result["data_hold_candidates"] == 2
    assert result["blocker_counts_overlapping"]["security_class_unverified"] == 1
    assert result["blocker_counts_overlapping"]["preferred_shares_unresolved"] == 1
    assert result["blocker_counts_overlapping"]["dilution_quantity_unresolved"] == 1
    assert result["gate_counts"]["REJECT"] == 1


def test_triage_rejects_missing_columns(tmp_path):
    path = tmp_path / "candidates.csv"
    path.write_text("ticker,gate_status\\nA,DATA_HOLD\\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="Missing triage columns"):
        triage(path)
