"""Source-backed M&A *discovery*, deliberately separate from investment gates.

Never substitute acquirer capitalization for the target or grant a PASS here.
Only uniquely resolved listed-company identities are attached to a source.
"""
from __future__ import annotations
import html
import re
from .models import Candidate

TENDER_FORMS = frozenset({
    "SC TO-C", "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A",
})
LEGAL = re.compile(r"\b(?:corporation|corp\.?|inc\.?|incorporated|holdings|ltd\.?|limited|company|co\.?)$", re.I)


def normalized(value):
    value = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    tokens = value.split()
    while tokens and tokens[-1] in {"corporation", "corp", "inc", "incorporated",
                                    "limited", "ltd", "company", "co"}:
        tokens.pop()
    return " ".join(tokens)


def plain_text(body):
    # SEC filings are often HTML; keep block breaks for tender-offer cover headings.
    s = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", body)
    s = re.sub(r"(?i)</?(?:p|div|br|tr|h[1-6]|td)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s).replace("\u00a0", " ")


def name_index(by_ticker):
    """Map exact legal name or unambiguous issuer stem, never fuzzy substrings."""
    index = {}
    ambiguous = set()
    for meta in by_ticker.values():
        name = normalized(meta.get("name", ""))
        if not name or len(name) < 6:
            continue
        keys = {name}
        if len(name.split()) == 1:  # e.g. 'Ultralife' for 'Ultralife Corporation'
            keys.add(name)
        for key in keys:
            cik = str(int(meta["cik"]))
            if key in index and str(int(index[key]["cik"])) != cik:
                ambiguous.add(key)
            else:
                index[key] = meta
    return {k: v for k, v in index.items() if k not in ambiguous}


def _named_target_candidates(text, form):
    candidates = []
    if form in TENDER_FORMS:
        # The legal cover of a Schedule TO / 14D9 identifies the *subject*.
        for pattern in (
            r"([A-Z][A-Z0-9 &.,'-]{5,110})\s*\(\s*Name of Subject Company\s*\)",
            r"\b(?:shares|common stock)\s+of\s+([A-Z][A-Za-z0-9&.,' -]{5,110}?)(?:\s*,\s*a\s+\w+\s+corporation|\s*\()",
        ):
            candidates.extend(m.group(1).strip() for m in re.finditer(pattern, text, re.I))
    # Only operative acquisition clauses, not incidental company mentions.
    pattern = (r"\b(?:to acquire|acquisition of|acquire all (?:of )?(?:the )?(?:outstanding )?"
               r"shares of|tender offer to (?:acquire|purchase) (?:all )?(?:of )?(?:the )?"
               r"(?:outstanding )?(?:common )?(?:shares|stock) of)\s+"
               r"([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,7})")
    for match in re.finditer(pattern, text, re.I):
        candidate = re.split(r"\s+(?:by|for|from|through|pursuant|at|in|under|which|whose)\b", match.group(1), maxsplit=1, flags=re.I)[0]
        candidates.append(candidate.strip(" ,."))
    return candidates


def _match_target(text, form, index, filer_cik):
    for raw in _named_target_candidates(text, form):
        # Use the shortest high-specificity legal name or title. Never fuzzy-match
        # only a company-name fragment within another company's legal name.
        tokens = raw.split()
        for n in range(len(tokens), 0, -1):
            key = normalized(" ".join(tokens[:n]))
            meta = index.get(key)
            if meta and str(int(meta["cik"])) != str(int(filer_cik)):
                return meta, raw, "exact_unique_sec_exchange_issuer_name"
            if meta and form in TENDER_FORMS:
                return meta, raw, "tender_subject_sec_exchange_issuer_name"
    return None, None, None


def extract_terms(text, form):
    """Conservative transaction facts: unknown is never represented as absent."""
    t = re.sub(r"\s+", " ", text)
    lower = t.lower()
    is_merger = "merger agreement" in lower or "agreement and plan of merger" in lower
    is_tender = "tender offer" in lower or "schedule to" in lower
    if not (is_merger or is_tender):
        return None
    terms = {"consideration_type": "UNVERIFIED", "cash_per_share_usd": None,
             "financing_condition": "UNVERIFIED", "regulatory_approval": "UNVERIFIED",
             "minimum_tender": "UNVERIFIED", "cvr": "UNVERIFIED",
             "earnout": "UNVERIFIED",
             "expected_closing": "UNVERIFIED", "preferred_convertibles_warrants": "UNVERIFIED",
             "fd_review_required": True,
             "terms_source": "SEC primary text; terms not independently reconciled"}
    # Reject nominal/par-value clauses even if a nearby unrelated sentence says cash.
    # Price and cash entitlement must be in the same bounded clause.
    for m in re.finditer(r"\$\s*(\d{1,5}(?:\.\d+)?)\s+per\s+(?:common\s+)?share\b", t, re.I):
        clause_start = max(t.rfind(".", 0, m.start()), t.rfind(";", 0, m.start()), t.rfind(":", 0, m.start()))
        clause_end_candidates = [p for p in (t.find(".", m.end()), t.find(";", m.end())) if p >= 0]
        clause_end = min(clause_end_candidates) if clause_end_candidates else len(t)
        context = t[max(clause_start + 1, m.start() - 180):min(clause_end, m.end() + 180)]
        if re.search(r"\b(?:par value|stated value|nominal value)\b", context, re.I):
            continue
        if re.search(r"\b(?:in cash|payable in cash|cash tender offer)\b", context, re.I):
            terms.update(cash_per_share_usd=float(m.group(1)), consideration_type="CASH")
            break
    if re.search(r"\b(?:stock|share)\s+(?:consideration|exchange ratio)\b", t, re.I):
        terms["consideration_type"] = "CASH_AND_STOCK_UNVERIFIED" if terms["cash_per_share_usd"] else "STOCK_UNVERIFIED"
    quarter = re.search(r"\b(?:expected|anticipated) to close (?:in|during) (?:the )?"
                        r"(first|second|third|fourth) quarter of (?:calendar |fiscal )?(?:year )?(20\d\d)", t, re.I)
    if quarter:
        terms["expected_closing"] = {
            "first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"
        }[quarter.group(1).lower()] + " " + quarter.group(2)
    if re.search(r"\b(?:preferred stock|convertible (?:notes?|securities|debentures)|warrants?)\b", t, re.I):
        terms["preferred_convertibles_warrants"] = "MENTIONED_REQUIRES_REVIEW"
    if re.search(r"\b(?:contingent value rights?|CVR)\b", t, re.I):
        terms["cvr"] = "PRESENT_VALUE_UNVERIFIED"
    if re.search(r"\bearn[- ]?out\b", t, re.I):
        terms["earnout"] = "PRESENT_VALUE_UNVERIFIED"
    if re.search(r"\bnot subject to (?:a |any )?financing (?:condition|contingency)\b", t, re.I):
        terms["financing_condition"] = "NONE_DISCLOSED"
    if re.search(r"\b(?:regulatory (?:clearance|approval)|antitrust)\b", t, re.I):
        terms["regulatory_approval"] = "REQUIRED_OR_REFERENCED"
    if re.search(r"\b(?:minimum (?:tender|condition)|majority of (?:the )?outstanding shares)\b", t, re.I):
        terms["minimum_tender"] = "CONDITION_REFERENCED"
    closed = re.search(r"\b(?:merger|acquisition|tender offer)\b.{0,65}\b(?:has been completed|was consummated|has closed)\b", t, re.I)
    cancelled = re.search(r"\b(?:merger agreement|tender offer)\b.{0,65}\b(?:was terminated|has been terminated|was withdrawn)\b", t, re.I)
    signed = (re.search(r"\bentered into\s+(?:an?\s+)?(?:agreement and plan of merger|merger agreement)\b", t, re.I)
              or re.search(r"\bdefinitive agreement to acquire\b", t, re.I))
    # A historical termination reference is not evidence that the *current*
    # tender has ended. Conflicting lifecycle language is never certified.
    active_tender = bool(re.search(
        r"\\b(?:offer (?:is|remains) open|offer (?:will|is scheduled to) expire|"
        r"expiration date (?:is|of)|offer has commenced|tender offer is ongoing|"
        r"offer is currently outstanding)\\b", t, re.I))
    status_conflict = bool(cancelled and active_tender)
    terms["lifecycle_conflict_requires_review"] = status_conflict
    terms["deal_status"] = ("UNVERIFIED" if status_conflict else
                            "TERMINATED" if cancelled else "COMPLETED" if closed
                            else "SIGNED" if signed else "ANNOUNCED")
    return terms


def discover(sec, filing, index, *, text=None):
    form = filing.get("form", "")
    if form not in TENDER_FORMS | {"8-K", "8-K/A"}:
        return None
    if text is None:
        text = sec.submission_text(filing["filename"])
    readable = plain_text(text)
    terms = extract_terms(readable, form)
    if terms is None:
        return None
    target, matched_name, identity = _match_target(readable, form, index, filing["cik"])
    if target is None:
        return None
    acc = filing.get("accession")
    source = ("https://www.sec.gov/Archives/" + filing["filename"].lstrip("/")
              if filing.get("filename") else filing.get("index_url"))
    if not source or not acc:
        return None
    out = Candidate(ticker=target["ticker"], name=target["name"],
                    cik=str(int(target["cik"])), exchange=target["exchange"],
                    security_type="UNKNOWN", event_review_complete=False)
    out.latest_event_date = filing.get("filed")
    out.latest_event_form = form
    out.latest_event_accession = acc
    out.event_status = terms["deal_status"]
    out.event_proof = 2 if terms["deal_status"] == "SIGNED" else 1
    out.event_type = "M_AND_A_DISCOVERY"
    out.event_summary = "Source-linked tender/merger counterparty; independent target diligence required"
    out.event_sources = [source]
    out.event_terms = {**terms, "subject_company_name_as_matched": matched_name,
                       "subject_cik": str(int(target["cik"])),
                       "filing_cik": str(int(filing["cik"])),
                       "discovery_accession": acc, "counterparty_identification": identity,
                       "source_form": form}
    out.discovery_status = "M&A_DISCOVERY_REVIEW_REQUIRED"
    out.gate_status = out.bucket = "DATA_HOLD"
    out.data_warnings = [
        "M&A target discovered from third-party filing; separate target SEC filing, "
        "market price, FD, tender conditions and lifecycle must be reconciled before PASS."
    ]
    return out
