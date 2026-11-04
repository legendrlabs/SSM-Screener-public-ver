"""Offline regressions for issuer/target role and conservative tender economics.

The fixtures paraphrase SEC facts and contain no ticker-specific engine branches.
"""
from datetime import date
from ssm.ma_review import issuer_role, offer_spread_gate, variable_tender_terms
from ssm.ma_discovery import extract_terms
from ssm.models import Candidate
from ssm.gates import evaluate_gates

CFG = {"exchanges": ["Nasdaq", "NYSE"], "market_data_max_age_days": 3}

def test_asset_acquisition_issuer_is_buyer_not_merger_target():
    body = ("The Company acquired real and personal property and a manufacturing facility "
            "in Hamilton County, Iowa. The purchase price includes Series B preferred "
            "shares and a secured promissory note at 8 percent.")
    role, evidence = issuer_role(body, "Edible Garden AG Incorporated")
    assert role == "ASSET_BUYER"
    c = Candidate(ticker="GENERIC", event_type="ASSET_SALE_ACQUISITION",
                  event_terms={"ma_role":role, "asset_acquisition_financing_review_required": True})
    assert evaluate_gates(c, CFG)[0] == "DATA_HOLD"
    sec_style = ("The Company agreed to acquire from the Seller certain real and personal "
                 "property in Iowa. On October 30, 2026 the Company completed the acquisition "
                 "of the Property and issued preferred shares and a secured note.")
    assert issuer_role(sec_style, "Edible Garden AG Incorporated")[0] == "ASSET_BUYER"

def test_surviving_issuer_acquirer_completed_is_excluded():
    body = ("Isabella Bank Corporation completed its previously announced acquisition "
            "of Grand River Commerce, Inc. on November 2, 2026.")
    role, evidence = issuer_role(body, "Isabella Bank Corporation")
    assert role == "ACQUIRER"
    c = Candidate(ticker="GENERIC", event_type="MERGER_CASH_STOCK",
                  event_status="COMPLETED", event_terms={"ma_role": role},
                  security_type="COMMON_EQUITY")
    gate, why = evaluate_gates(c, CFG)
    assert gate == "EXCLUDED" and "acquirer" in why[0]

def test_fixed_cash_target_above_price_is_not_profitable_arbitrage():
    role, evidence = issuer_role("The Company will be acquired by Parent "
                                 "for a cash consideration to its stockholders.")
    assert role == "TARGET"
    candidate = Candidate(ticker="ANY", security_type="COMMON_EQUITY",
                          event_type="MERGER_CASH", event_status="SIGNED",
                          price=14.30, price_as_of=date.today().isoformat(),
                          event_terms={"ma_role": "TARGET", "cash_per_share_usd": 14.25,
                                       "cash_per_share_status": "FIXED",
                                       "consideration_type": "CASH"})
    result = offer_spread_gate(candidate.event_terms, candidate.price,
                               event_type=candidate.event_type,
                               event_status=candidate.event_status,
                               price_as_of=candidate.price_as_of,
                               today=date(2026, 11, 5))
    assert result[0] == "REJECT" and result[2] < 0
    assert evaluate_gates(candidate, CFG)[0] == "REJECT"

def test_positive_spread_is_a_hold_not_an_approval():
    terms = {"ma_role": "TARGET", "cash_per_share_usd": 14.25,
             "cash_per_share_status": "FIXED", "consideration_type": "CASH"}
    result = offer_spread_gate(terms, 13.70, event_type="MERGER_CASH", event_status="SIGNED")
    assert result[0] == "DATA_HOLD"
    assert result[2] > 0
    candidate = Candidate(ticker="ANY", event_type="MERGER_CASH", event_status="SIGNED",
                          price=13.7, event_terms=terms)
    assert evaluate_gates(candidate, CFG)[0] == "DATA_HOLD"

def test_cvat_style_aggregate_tender_is_unpriced_until_final_record_date():
    filing = ("The Tender Offer Agreement provides for a cash tender offer for all shares. "
              "At a net aggregate price of $35,000,000 less outstanding liabilities "
              "divided by the total number of common shares outstanding at the record date. "
              "The Record Date is December 24, 2026. A final offer price will be announced later.")
    terms = extract_terms(filing, "SC TO-T")
    assert terms["consideration_type"] == "VARIABLE_AGGREGATE_CASH"
    assert terms["cash_per_share_usd"] is None
    assert terms["aggregate_cash_ceiling_usd"] == 35000000
    assert terms["variable_offer_review_required"] is True
    assert terms["formula_record_date"] == "December 24, 2026"
    c = Candidate(ticker="EXAMPLE", event_type="MERGER_UNVERIFIED", price=0.08,
                  event_terms={**terms, "ma_role": "TARGET"})
    assert evaluate_gates(c, CFG)[0] == "DATA_HOLD"

def test_fundamental_unknowns_cannot_be_bypassed_by_cash_price_or_cvr():
    terms = {"ma_role": "TARGET", "cash_per_share_usd": 16,
             "cash_per_share_status": "FIXED", "consideration_type": "CASH",
             "cvr": "PRESENT_VALUE_UNVERIFIED"}
    assert offer_spread_gate(terms, 12, event_type="MERGER_CASH_CVR",
                             event_status="SIGNED")[0] == "DATA_HOLD"
    assert offer_spread_gate({**terms, "cvr":"UNVERIFIED"}, 12,
                             event_type="MERGER_CASH", event_status="COMPLETED")[0] == "EXCLUDED"

def test_cash_price_from_par_value_is_still_not_accepted():
    filing = ("The Company announced a tender offer for its common shares "
              "with $0.0001 per share par value. Consideration has not been determined.")
    parsed = extract_terms(filing, "SC TO-T")
    assert parsed["cash_per_share_usd"] is None
