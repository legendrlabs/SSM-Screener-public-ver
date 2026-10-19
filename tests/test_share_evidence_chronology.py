"""Chronology must be explicit before calculating current share value."""
from ssm.providers.sec import latest_fact_record
from ssm.pipeline import _common_shares
from ssm.models import Candidate, Dilution


def facts(rows):
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {
        "units": {"shares": rows}
    }}}}


def test_amended_filing_for_old_period_cannot_replace_new_share_balance():
    entries = [
        {"val": 3_038_140, "end": "2026-08-25", "filed": "2026-08-26", "form": "8-K"},
        {"val": 1_861_303, "end": "2026-06-30", "filed": "2026-10-14", "form": "10-Q/A"},
    ]
    evidence = latest_fact_record(facts(entries), "EntityCommonStockSharesOutstanding")
    common, row = _common_shares(facts(entries))
    assert evidence["end"] == "2026-08-25"
    assert common == 3_038_140
    assert row["val"] == 3_038_140


def test_dated_share_evidence_missing_remains_unresolved():
    assert _common_shares({}) == (0.0, None)
    assert latest_fact_record({}, "EntityCommonStockSharesOutstanding") is None


def test_post_baseline_capital_action_invalidates_basic_market_cap():
    c = Candidate("ISSUER", price=0.42, dilution=Dilution(common_shares=1_000_000, confidence="low"))
    assert c.basic_market_cap() == 420_000
    c.event_terms["common_share_baseline_stale"] = True
    assert c.basic_market_cap() is None
    assert c.near_fd_market_cap() is None
    assert c.to_dict()["basic_market_cap"] is None


def test_closed_warrant_exercise_creates_reconciliation_evidence_not_fd_count():
    from ssm.capital_evidence import completed_warrant_exercise_evidence
    closed = (
        "The Holder agreed to exercise existing warrants to purchase 4,074,359 shares "
        "of the Company's common stock for cash. "
        "The Inducement Transaction closed on September 21, 2026. "
        "The Company also agreed to issue Reload Warrants for 8,148,718 shares."
    )
    pending = closed.replace(
        "The Inducement Transaction closed on September 21, 2026.",
        "The Inducement Transaction is expected to close on September 21, 2026."
    )
    assert completed_warrant_exercise_evidence(closed)
    assert not completed_warrant_exercise_evidence(pending)
    assert not completed_warrant_exercise_evidence(
        "The Company agreed to issue replacement warrants subject to shareholder approval."
    )
