"""Conservative M&A economic and party-role review, never trading approval.

Only explicit source language is classified. Asset buyers, surviving acquirers,
and merger targets have different payoffs and must not share arbitrage gates.
"""
from __future__ import annotations
import re
from datetime import date

def issuer_role(text: str, issuer_name: str = "") -> tuple[str, str]:
    t = re.sub(r"\s+", " ", text)
    name = re.escape(issuer_name.strip()) if issuer_name else None
    issuer = r"(?:\bthe Company\b|\bwe\b|\bour company\b" + (r"|\b" + name + r"\b" if name else "") + r")"
    asset = (r".{0,160}\b(?:acquire|acquired|purchased|purchase of|"
             r"completed (?:the )?acquisition of|asset acquisition of)\b.{0,150}"
             r"\b(?:real (?:and personal )?property|facility|facilities|manufacturing plant|"
             r"equipment|land|production assets|assets|the Property)\b")
    buyer = (r".{0,120}\b(?:completed|consummated|closed)\s+(?:its|the|a|our)?\s*"
             r"(?:previously announced\s*)?(?:acquisition|merger)\s+(?:of|with)\b")
    target = r".{0,140}\b(?:will be acquired by|to be acquired by|has been acquired by|is being acquired by)\b"
    if re.search(issuer + asset, t, re.I):
        return "ASSET_BUYER", "issuer's acquisition of physical assets"
    if re.search(issuer + buyer, t, re.I):
        return "ACQUIRER", "issuer completed acquisition/merger of another company"
    if re.search(issuer + target, t, re.I):
        return "TARGET", "issuer to be acquired by a counterparty"
    if name and re.search(r"\b(?:merge with and into|merger of)\s+" + name + r"\b", t, re.I):
        return "TARGET", "merger sub being merged into issuer"
    return "UNVERIFIED", "issuer/target direction not explicit"

def variable_tender_terms(text: str) -> dict:
    t = re.sub(r"\s+", " ", str(text))
    gross = re.search(
        r"\b(?:net\s+)?aggregate (?:purchase )?price\s+of\s*\$?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(million|billion)?", t, re.I)
    deduction = re.search(r"\b(?:less|reduced by|minus)\b.{0,110}"
                          r"\b(?:liabilities|indebtedness|debt)\b", t, re.I)
    shares = re.search(r"\bdivided by\b.{0,140}\b(?:shares|common stock)\b", t, re.I)
    if not (gross and deduction and shares):
        return {}
    base = float(gross.group(1).replace(",", ""))
    unit = (gross.group(2) or "").lower()
    scale = {"million": 1000000, "billion": 1000000000, "": 1}[unit]
    result = {
        "consideration_type": "VARIABLE_AGGREGATE_CASH",
        "cash_per_share_usd": None,
        "cash_per_share_status": "UNFINALIZED_FORMULA",
        "aggregate_cash_ceiling_usd": base * scale,
        "net_cash_aggregate_formula": "aggregate cash less record-date liabilities",
        "per_share_denominator": "record-date shares outstanding; FD review required",
        "liabilities_as_of": "UNVERIFIED",
        "shares_as_of": "UNVERIFIED",
        "fd_review_required": True,
        "variable_offer_review_required": True,
    }
    rec = re.search(r"\brecord date\s+(?:of|is)\s+"
                    r"((?:January|February|March|April|May|June|July|August|"
                    r"September|October|November|December)\s+\d{1,2},?\s+20\d\d)", t, re.I)
    if rec:
        result["formula_record_date"] = rec.group(1)
    return result

def offer_spread_gate(terms: dict, price: float | None, *,
                      event_type: str = "", event_status: str = "",
                      price_as_of: str | None = None,
                      max_quote_age_days: int = 3, today: date | None = None):
    """Returns (status, reason, gross_spread_pct), or None when not a target merger."""
    if terms.get("ma_role") != "TARGET" or not ("MERGER" in event_type or event_type == "M_AND_A_DISCOVERY"):
        return None
    if event_status in {"TERMINAL", "COMPLETED", "CANCELLED", "TERMINATED"}:
        return ("EXCLUDED", "Transaction already completed/cancelled; no arbitrage entry.", None)
    if terms.get("variable_offer_review_required"):
        return ("DATA_HOLD", "Variable tender amount: debt, record-date shares, and FD unresolved.", None)
    fixed = terms.get("cash_per_share_usd")
    if (not isinstance(fixed, (int, float)) or fixed <= 0
            or terms.get("cash_per_share_status") not in {"FIXED", "FIXED_CONFIRMED"}
            or terms.get("consideration_type") not in {None, "CASH"}):
        return ("DATA_HOLD", "Fixed common-cash entitlement unverified.", None)
    if terms.get("cvr_conditional") or terms.get("cvr") not in {None, "UNVERIFIED", "ABSENT_VERIFIED"}:
        return ("DATA_HOLD", "CVR/additional consideration is not guaranteed cash.", None)
    if price is None or price <= 0:
        return ("DATA_HOLD", "Market price is unknown.", None)
    if price_as_of:
        try:
            days = ((today or date.today()) - date.fromisoformat(price_as_of[:10])).days
            if not 0 <= days <= max_quote_age_days:
                return ("DATA_HOLD", "Quote timestamp stale/future.", None)
        except (TypeError, ValueError):
            return ("DATA_HOLD", "Quote timestamp invalid.", None)
    spread = (fixed / price - 1.0) * 100
    if price >= fixed:
        return ("REJECT", f"Reverse/nonpositive gross cash spread: market {price:g} >= fixed consideration {fixed:g}.", spread)
    return ("DATA_HOLD", f"Gross spread {spread:.2f}% is indicative only; verify conditions, FD and settlement.", spread)
