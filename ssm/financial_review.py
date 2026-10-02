from __future__ import annotations
import re
import html
from .models import Dilution

NOTE_PATTERNS = {
    "WARRANTS": r"\bwarrants?\b",
    "PRE_FUNDED": r"pre[- ]funded",
    "CONVERTIBLES": r"convertible (?:notes?|debentures?|preferred)",
    "PREFERRED": r"preferred stock|preferred shares",
    "ATM_EQUITY_LINE": r"at-the-market|\bATM\b|equity line|SEPA|ELOC",
    "STOCK_COMP": r"stock-based compensation|share-based compensation|restricted stock units?|\bRSUs\b",
    "GOING_CONCERN": r"going concern|substantial doubt",
    "RELATED_PARTY": r"related party|related-party",
    "SUBSEQUENT_EVENTS": r"subsequent events?",
    "COMMITMENTS_CONTINGENCIES": r"commitments? and contingencies|contingencies",
    "DEBT": r"notes? payable|credit facility|term loan|debt",
    "STOCKHOLDERS_EQUITY": r"stockholders['’]? equity|shareholders['’]? equity",
}

DILUTION_FIELDS = [
    "pre_funded_shares",
    "options_itm_shares",
    "warrants_itm_shares",
    "warrants_otm_shares",
    "converts_shares",
    "preferred_shares_equiv",
    "merger_consideration_shares",
    "sbc_rsus_shares",
    "atm_remaining_usd",
    "warrant_exercise_cash_usd",
]

def financial_note_hits(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", text or "")
    return [label for label, pattern in NOTE_PATTERNS.items() if re.search(pattern, t, re.I)]

def conservative_merge_dilution(current: Dilution, financial: Dilution) -> Dilution:
    """
    Merge event-filing and 10-Q/10-K cap-table evidence conservatively.

    Share-equivalent categories use max(), not addition, because the same
    instrument is often disclosed in both filings. This may overstate stale
    instruments, but avoids double counting while preserving a conservative
    screening bias.
    """
    out = Dilution(
        common_shares=max(current.common_shares, financial.common_shares),
        source=" + ".join(x for x in [current.source, financial.source] if x),
        confidence="low" if "low" in {current.confidence, financial.confidence} else "medium",
    )
    if current.confidence == financial.confidence == "high":
        out.confidence = "high"
    for field in DILUTION_FIELDS:
        setattr(out, field, max(float(getattr(current, field, 0) or 0), float(getattr(financial, field, 0) or 0)))
    consideration = [d.pending_stock_consideration_usd for d in (current, financial) if d.pending_stock_consideration_usd is not None]
    out.pending_stock_consideration_usd = max(consideration) if consideration else None
    unit_evidence = [d for d in (current, financial) if d.warrant_units_as_of]
    if unit_evidence:
        latest_date = max(d.warrant_units_as_of for d in unit_evidence)
        latest = [d for d in unit_evidence if d.warrant_units_as_of == latest_date]
        counts = {(d.pre_funded_warrants_outstanding, d.ordinary_warrants_outstanding) for d in latest}
        if len(counts) == 1:
            out.warrant_units_as_of = latest_date
            out.pre_funded_warrants_outstanding, out.ordinary_warrants_outstanding = counts.pop()
        else:
            out.confidence = 'low'
            out.source += ' (conflicting outstanding warrant units)'
    return out


def visible_filing_text(text: str) -> str:
    # Inline-XBRL headers contain hidden facts, contexts and even entire note
    # narratives. They are not the human-readable cover or financing terms.
    plain = re.sub(r'<(ix:header|ix:hidden|script|style)\b[^>]*>.*?</\1\s*>',
                   ' ', text or '', flags=re.I | re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    return re.sub(r'\s+', ' ', html.unescape(plain)).strip()


def _cover_plain_text(text: str, max_chars: int = 60000) -> str:
    plain = visible_filing_text(text)
    plain = re.sub(r"\s+", " ", plain).strip()
    head = plain[:max_chars]
    for marker in (
        r"\bPART\s+I\b",
        r"\bITEM\s+1[\.:]\s",
        r"\bPART\s+II\b",
    ):
        m = re.search(marker, head, re.I)
        if m:
            head = head[:m.start()]
            break
    return head

def cover_page_common_shares(text: str) -> float:
    """Resolve cover-page shares only; never scan notes/MD&A for this fallback."""
    plain = _cover_plain_text(text)

    combined = re.search(
        r'(\d[\d,]*)\s+and\s+(\d[\d,]*)\s+shares\s+of\s+Class\s+[A-Z0-9-]+'
        r'\s+and\s+Class\s+[A-Z0-9-]+\s+common stock[^.]{0,120}?outstanding',
        plain, re.I)
    if combined:
        return sum(float(value.replace(',', '')) for value in combined.groups())

    class_values = {}
    # Common SEC cover-page wording: "N shares of Class A common stock ... outstanding".
    for outstanding in re.finditer(r"\boutstanding\b", plain, re.I):
        window = plain[max(0, outstanding.start() - 500):outstanding.end()]
        for m in re.finditer(
            r"(\d[\d,]*)\s+shares\s+of\s+(Class\s+[A-Z0-9-]+)\s+common stock",
            window,
            re.I,
        ):
            value = float(m.group(1).replace(",", ""))
            label = m.group(2).upper()
            class_values[label] = max(class_values.get(label, 0.0), value)
    if class_values:
        return sum(class_values.values())

    # Generic single-class cover wording.
    generic = []
    patterns = [
        r"(?:as of|on)\s+[^.]{0,120}?there (?:were|was)\s+(\d[\d,]*)\s+shares\s+of\s+(?:our\s+)?common stock[^.]{0,120}?outstanding",
        r"(\d[\d,]*)\s+shares\s+of\s+(?:our\s+)?common stock[^.]{0,180}?outstanding",
        r"common stock[^.]{0,180}?(\d[\d,]*)\s+shares[^.]{0,120}?outstanding",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, plain, re.I):
            if not re.search(r'authorized|treasury', m.group(0), re.I):
                generic.append(float(m.group(1).replace(",", "")))
    return max(generic) if generic else 0.0

def extract_atm_remaining_usd(text: str) -> float:
    plain = re.sub(r"<[^>]+>", " ", text or "")
    plain = re.sub(r"&nbsp;|&#160;", " ", plain, flags=re.I)
    plain = re.sub(r"\s+", " ", plain)
    amount = r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|m|k)?"
    patterns = [
        rf"{amount}.{{0,100}}?(?:remaining|remain(?:ed|s)?|available).{{0,140}}?(?:at-the-market|sales agreement)",
        rf"(?:at-the-market|sales agreement).{{0,180}}?{amount}.{{0,100}}?(?:remaining|remain(?:ed|s)?|available)",
    ]
    values = []
    for pattern in patterns:
        for m in re.finditer(pattern, plain, re.I):
            raw = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            if unit in ("million", "m"):
                raw *= 1_000_000
            elif unit in ("thousand", "k"):
                raw *= 1_000
            values.append(raw)
    return max(values) if values else 0.0
