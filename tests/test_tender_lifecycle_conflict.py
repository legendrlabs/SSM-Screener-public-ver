"""Regression tests: historical termination must not close an active tender."""
from ssm.ma_discovery import extract_terms


def test_active_tender_with_historical_termination_is_unverified():
    text = ("Schedule TO. The tender offer has commenced. The offer is scheduled to expire "
            "on November 16, 2026. A prior merger agreement was terminated.")
    terms = extract_terms(text, "SC TO-T")
    assert terms["deal_status"] == "UNVERIFIED"
    assert terms["lifecycle_conflict_requires_review"] is True


def test_unambiguous_terminated_merger_still_terminated():
    terms = extract_terms("The merger agreement has been terminated.", "8-K")
    assert terms["deal_status"] == "TERMINATED"
    assert terms["lifecycle_conflict_requires_review"] is False


def test_unambiguous_active_tender_not_terminated():
    terms = extract_terms("Schedule TO. The offer is scheduled to expire November 16, 2026.", "SC TO-T")
    assert terms["deal_status"] == "ANNOUNCED"
    assert terms["lifecycle_conflict_requires_review"] is False
