"""Regression tests for SEC M&A discovery cash consideration."""
from ssm.ma_discovery import extract_terms


def test_par_value_is_not_merger_cash():
    text = ("Agreement and Plan of Merger. Common stock, $0.10 per share par value. "
            "Each outstanding share will receive $16.00 per share in cash.")
    terms = extract_terms(text, "8-K")
    assert terms["cash_per_share_usd"] == 16.0
    assert terms["consideration_type"] == "CASH"


def test_par_value_with_nearby_cash_does_not_create_price():
    text = ("Merger agreement. Common stock, $0.10 per share par value. "
            "The consideration will be paid in cash subject to closing conditions.")
    assert extract_terms(text, "8-K")["cash_per_share_usd"] is None


def test_unknown_price_stays_unverified():
    terms = extract_terms("Agreement and Plan of Merger; cash terms to be determined.", "8-K")
    assert terms["cash_per_share_usd"] is None
    assert terms["fd_review_required"] is True
