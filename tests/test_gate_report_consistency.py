"""Gate/priority consistency and post-merger data-quality regression tests.

Real-ticker examples may be regression fixtures only; no ticker-specific logic.
"""
import csv
import json

from ssm.models import Candidate, Dilution
from ssm.scoring import bucket_candidate
from ssm.report import write_outputs


def candidate(ticker, gate, score, *, event_type="OTHER", event_status="SIGNED"):
    row = Candidate(
        ticker=ticker, gate_status=gate, priority_score=score,
        event_type=event_type, event_status=event_status,
        dilution=Dilution(common_shares=1_000_000, confidence="low"),
    )
    row.bucket = bucket_candidate(row)
    return row


def test_low_score_watch_is_never_classified_as_reject():
    for score in (0, 10, 24, 25, 39, 40, 90):
        item = candidate("LOW", "WATCH", score)
        assert item.bucket == ("B_WATCH" if score >= 40 else "C_SPECULATIVE")


def test_low_score_pass_keeps_pass_gate_without_action_bucket():
    for score in (0, 24, 39, 59):
        item = candidate("PASS", "PASS", score)
        assert item.bucket != "REJECT"
        assert item.bucket != "A_RESEARCH_NOW"
    assert candidate("PASS", "PASS", 60).bucket == "A_RESEARCH_NOW"


def test_qa_watch_count_matches_report_even_when_score_below_25(tmp_path):
    watch_high = candidate("FIRST", "WATCH", 59, event_type="LIQUIDATION_DISTRIBUTION")
    watch_low = candidate("SECOND", "WATCH", 3)
    stale_cap = candidate("THIRD", "DATA_HOLD", 60)
    write_outputs([watch_high, watch_low, stale_cap], {"max_candidates": 5}, tmp_path)
    quality = json.loads((tmp_path / "quality.json").read_text())
    latest = (tmp_path / "latest.md").read_text()
    assert quality["watch_count"] == quality["watch_reported_count"] == 2
    assert quality["gate_bucket_mismatch_count"] == 0
    watch_section = latest.split("## B/C — WATCH", 1)[1].split("## DATA HOLD", 1)[0]
    assert "**FIRST**" in watch_section and "**SECOND**" in watch_section
    assert "**THIRD**" not in watch_section
    assert quality["SAFE_TO_ACT"] is False


def test_completed_merger_is_visible_without_false_fd_certification(tmp_path):
    merger = candidate("CLOSE", "DATA_HOLD", 52,
                       event_type="MERGER_UNVERIFIED", event_status="COMPLETED")
    merger.common_shares_source = "SEC companyfacts as of 2026-06-30"
    merger.data_warnings = ["Post-transaction stock and convertibles require reconciliation."]
    write_outputs([merger], {"max_candidates": 5}, tmp_path)
    latest = (tmp_path / "latest.md").read_text()
    quality = json.loads((tmp_path / "quality.json").read_text())
    assert "COMPLETED MERGERS — FD RECONCILIATION PENDING (1)" in latest
    assert "SEC companyfacts as of 2026-06-30" in latest
    assert quality["completed_merger_fd_hold_count"] == 1
    assert quality["pass_count"] == 0
    d = next(csv.DictReader((tmp_path / "dilution_check.csv").open(encoding="utf-8-sig")))
    assert d["strict_fd_shares"] == ""


def test_cash_stock_merger_and_warrant_issuer_remain_data_hold(tmp_path):
    cash_stock = candidate("CASHSTOCK", "DATA_HOLD", 40, event_type="MERGER_CASH_STOCK")
    cash_stock.event_terms = {
        "cash_per_share_usd": 1.14,
        "stock_exchange_ratio": 0.1,
        "cash_adjustment_direction": "DOWNWARD",
    }
    warrants = candidate("RELOAD", "DATA_HOLD", 40)
    warrants.dilution.pre_funded_warrants_outstanding = 2_005_900
    warrants.dilution.ordinary_warrants_outstanding = 2_469_230
    write_outputs([cash_stock, warrants], {"max_candidates": 5}, tmp_path)
    q = json.loads((tmp_path / "quality.json").read_text())
    assert q["pass_count"] == 0 and q["data_hold_count"] == 2
    assert q["SAFE_TO_ACT"] is False


def test_generic_preliminary_other_is_not_promoted_to_watch():
    from datetime import date
    from ssm.gates import evaluate_gates
    c = Candidate(
        ticker="GENERIC", exchange="Nasdaq", price=3, adv20_usd=500_000,
        event_type="OTHER", event_status="PRELIMINARY", event_proof=1,
        latest_event_date=date.today().isoformat(),
        latest_financial_filing_date=date.today().isoformat(),
        financial_review_complete=True,
        dilution=Dilution(common_shares=10_000_000, confidence="medium"),
    )
    cfg={"exchanges":["Nasdaq"],"market_cap_min":1,"market_cap_max":500_000_000,
         "market_cap_expand_max":1_000_000_000,"event_max_age_days":90,
         "financial_filing_max_age_days":210,"adv20_watch_min":50_000,
         "adv20_pass_min":250_000}
    status, reasons = evaluate_gates(c, cfg)
    assert status == "REJECT"
    assert any("structural" in x for x in reasons)
    c.event_type = "MERGER_UNVERIFIED"
    assert evaluate_gates(c, cfg)[0] == "WATCH"
