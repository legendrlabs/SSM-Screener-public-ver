"""Regression checks for tender lifecycle ambiguity and false termination."""
from ssm.ma_discovery import extract_terms


def test_historical_termination_does_not_close_active_tender():
    text = (
        "The prior merger agreement was terminated. "
        "A new tender offer is ongoing and the offer is scheduled to expire "
        "on November 16, 2026."
    )
    result = extract_terms(text, "SC 14D9/A")
    assert result["deal_status"] == "UNVERIFIED"
    assert result["lifecycle_conflict_requires_review"] is True


def test_terminated_tender_without_active_indication():
    result = extract_terms("The tender offer was withdrawn.", "SC TO-T/A")
    assert result["deal_status"] == "TERMINATED"
    assert result["lifecycle_conflict_requires_review"] is False


def test_active_tender_without_termination():
    result = extract_terms(
        "The tender offer has commenced and the offer remains open.",
        "SC TO-T"
    )
    assert result["deal_status"] == "ANNOUNCED"
    assert result["lifecycle_conflict_requires_review"] is False
