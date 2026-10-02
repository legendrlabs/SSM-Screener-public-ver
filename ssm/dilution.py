from __future__ import annotations
import re
from typing import Dict, Tuple
from .models import Dilution
from .financial_review import visible_filing_text
from .capital_evidence import preferred_signal_text, outstanding_warrant_units, capital_clauses, pending_stock_consideration, unresolved_stock_awards

NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|m|k)?"

def _to_num(raw, unit):
    try:
        n = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
    u = (unit or "").lower()
    if u in ("million", "m"):
        n *= 1_000_000
    elif u in ("thousand", "k"):
        n *= 1_000
    return n

def _first(patterns, text):
    for p in patterns:
        m = re.search(p, text, re.I | re.S)
        if not m:
            continue
        value = _to_num(m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None)
        if value > 0:
            return value
    return 0.0

def heuristic_extract_dilution(text: str, common_shares: float = 0.0, *, event_context: bool = False) -> Tuple[Dilution, list[str]]:
    t = visible_filing_text(text)
    preferred_text = preferred_signal_text(t)
    clauses = capital_clauses(text)
    def scope(pattern):
        return ' ; '.join(clause for clause in clauses if re.search(pattern, clause, re.I))
    d = Dilution(common_shares=common_shares, source="heuristic filing-text parser", confidence="low")
    warnings = []
    d.pre_funded_shares = _first([
        rf"pre[- ]funded warrants?\s+outstanding\s+(?:was|were|is|are|of|:)\s*{NUM}",
        rf"{NUM}\s+pre[- ]funded warrants?\s+(?:were|are)\s+outstanding",
        rf"pre[- ]funded warrants?.{{0,220}}?(?:purchase|acquire|representing|exercisable for|underlying).{{0,120}}?(?:up to\s+|an aggregate of\s+)?{NUM}\s+shares",
        rf"{NUM}\s+shares.{{0,160}}?pre[- ]funded warrants?",
        rf"{NUM}\s+pre[- ]funded warrants?.{{0,220}}?each.{{0,80}}?(?:one|1)\s+share",
    ], scope(r'pre[- ]funded'))
    # Mask the pre-funded label rather than removing the sentence: the same
    # sentence may also describe a distinct ordinary-warrant tranche.
    ordinary = re.sub(r'pre[- ]funded\s+warrants?', '_PRE_FUNDED_', t, flags=re.I)
    gap = r'(?:(?!_PRE_FUNDED_|;|\.\s).)'
    d.warrants_itm_shares = _first([
        rf"warrants?{gap}{{0,220}}?(?:purchase|acquire|exercisable for|underlying){gap}{{0,120}}?(?:up to\s+|an aggregate of\s+)?{NUM}\s+shares",
        rf"{NUM}\s+shares\s+(?:of common stock\s+)?(?:underlying|issuable upon exercise of)\s+(?:the\s+)?(?:new |common |series [a-z0-9-]+ )?warrants?",
    ], ordinary)
    d.converts_shares = _first([
        rf"convertible (?:notes?|debentures?).{{0,220}}?convertible into.{{0,120}}?{NUM}\s+shares",
        rf"{NUM}\s+shares.{{0,160}}?convertible (?:notes?|debentures?)",
    ], scope(r'convertible (?:notes?|debentures?)'))
    d.preferred_shares_equiv = _first([
        rf"preferred (?:stock|shares).{{0,220}}?convertible into.{{0,120}}?{NUM}\s+shares"
    ], preferred_text)
    d.sbc_rsus_shares = _first([
        rf"(?:restricted stock units?|rsus).{{0,160}}?(?:representing|covering|for)?.{{0,80}}?{NUM}\s+shares"
    ], scope(r'restricted stock units?|\brsus\b'))
    units = outstanding_warrant_units(text)
    if units:
        d.warrant_units_as_of, d.pre_funded_warrants_outstanding, d.ordinary_warrants_outstanding = units
        # Historical offering quantities elsewhere are not the table's current
        # share equivalents. Keep units distinct until exercise/reset terms are verified.
        d.pre_funded_shares = d.warrants_itm_shares = 0.0
        warnings.append('Outstanding warrant units reconciled; common-share equivalents and exercise/reset terms remain unresolved.')
    material = bool(re.search(
        r"pre[- ]funded|\bwarrants?\b|convertible (?:notes?|debentures?|preferred)|\batm\b|at-the-market|equity line",
        t,
        re.I,
    ) or re.search(r'preferred (?:stock|shares)', preferred_text, re.I))
    extracted = sum([
        d.pre_funded_shares,
        d.warrants_itm_shares,
        d.converts_shares,
        d.preferred_shares_equiv,
        d.sbc_rsus_shares,
    ])
    if material and extracted == 0:
        warnings.append("Material dilution language found but no reliable share quantity extracted.")
    checks = [
        (r'pre[- ]funded', d.pre_funded_shares, 'pre-funded warrants'),
        (r'\bwarrants?\b', d.warrants_itm_shares, 'ordinary warrants'),
        (r'convertible (?:notes?|debentures?)', d.converts_shares, 'convertible debt'),
        (r'preferred (?:stock|shares)', d.preferred_shares_equiv, 'preferred shares'),
    ]
    for pattern, quantity, label in checks:
        check_text = ordinary if label == 'ordinary warrants' else preferred_text if label == 'preferred shares' else t
        if re.search(pattern, check_text, re.I) and quantity <= 0:
            warnings.append(f'Unresolved share quantity for {label}.')
    share_terms = r'\bshares\b|\bcommon stock\b|\bequity\b'
    transaction = re.search(r'merger agreement|merger consideration|reverse merger|business combination agreement|(?:completed|consummated|entered into)\s+(?:the\s+|a\s+)?(?:merger|business combination)|earn[- ]?out', t, re.I)
    current_earnouts = scope(r'earn[- ]?out')
    current_earnouts = (re.search(share_terms, current_earnouts, re.I)
                        and re.search(r'outstanding|remaining|contingent|payable|will issue', current_earnouts, re.I))
    if (event_context and transaction) or current_earnouts:
        # Historical consideration may already be in common shares, while
        # contingent earnouts may be incremental. Neither is proven by a raw
        # issued-share count; require reconciliation before certifying FD.
        warnings.append('Unresolved incremental share obligations for merger consideration or earnout.')
    if event_context:
        if re.search(r'\b(?:issued|issue|issuance of|grant(?:ed)?)\s+(?:(?:\d[\d,.]*|new|additional|the|common stock)\s+){0,4}warrants?\b', t, re.I):
            warnings.append('New event warrant tranche requires reconciliation against the outstanding financial baseline.')
        pending, amount = pending_stock_consideration(text)
        if pending:
            d.pending_stock_consideration_usd = amount
            warnings.append('Pending stock consideration; incremental share issuance is not reconciled.')
    if unresolved_stock_awards(text, clauses):
        warnings.append('Unresolved outstanding stock awards; options, vesting and share equivalents require reconciliation.')
    if not warnings and common_shares > 0:
        d.confidence = "medium"
    return d, warnings

def apply_override(d: Dilution, override: Dict) -> Dilution:
    if not override:
        return d
    fields = set(Dilution.__dataclass_fields__)
    for k, v in override.items():
        if k in fields and k not in {"source", "confidence"}:
            setattr(d, k, float(v) if isinstance(v, (int, float)) else v)
    if override.get("source"):
        d.source = override["source"]
    if override.get("confidence"):
        d.confidence = override["confidence"]
    return d
