from __future__ import annotations
import re
from typing import Tuple
from .financial_review import visible_filing_text


def operative_text(text: str) -> str:
    """Read the transaction narrative, excluding cover and cautionary boilerplate."""
    t = visible_filing_text(text)
    item = re.search(r'\bIntroductory\s+Note\b|\bItem\s+(?:1\.01|2\.01|7\.01|8\.01)\b', t, re.I)
    if item:
        t = t[item.start():]
    t = re.split(r'\bItem\s+9\.01\b|\bSIGNATURES?\b|Forward[- ]Looking Statements|Certain statements contained in', t, maxsplit=1, flags=re.I)[0]
    return t

EVENT_KEYWORDS = {
    "MERGER_REVERSE_MERGER": [r"\bmerger agreement\b", r"\breverse merger\b", r"\bbusiness combination\b", r"\bmerger consideration\b"],
    "ASSET_SALE_ACQUISITION": [r"\bacquisition\b", r"\bacquire[sd]?\b", r"\basset sale\b", r"\bdisposition\b", r"\bpurchase agreement\b"],
    "STRATEGIC_INVESTMENT_PIPE": [r"\bstrategic investment\b", r"\bprivate placement\b", r"\bpipe\b", r"\bsecurities purchase agreement\b"],
    "DEBT_RESTRUCTURING": [r"\bredemption\b", r"\brefinanc", r"\bdebt repayment\b", r"\bdebt extinguish", r"\bnotes? repaid\b"],
    "LARGE_CONTRACT": [r"\bmaster services agreement\b", r"\bpurchase order\b", r"\bcontract value\b", r"\bgovernment contract\b", r"\btake-or-pay\b"],
    "BUSINESS_PIVOT": [r"\bstrategic pivot\b", r"\btransition(?:ing)? to\b", r"\brebrand", r"\bname change\b", r"\bai infrastructure\b", r"\bdata center\b", r"\bgpu\b", r"\bbitcoin treasury\b", r"\brobotics\b"],
    "LISTING_CAPITAL_STRUCTURE": [r"\breverse stock split\b", r"\bminimum bid price\b", r"\bnasdaq deficiency\b", r"\bwarrant inducement\b"]
}

MERGER_KINDS = {'MERGER_REVERSE_MERGER', 'MERGER_CASH_CVR', 'REVERSE_MERGER_CVR',
                'MERGER_CVR_UNVERIFIED', 'MERGER_CASH_STOCK', 'MERGER_STOCK'}


def completed_merger(t):
    return any(
        re.search(r'\b(?:closed|completed|consummated)\s+(?:(?:the|its|their|previously|announced)\s+)*(?:merger|business combination)\b|\b(?:merger|business combination)\s+(?:(?:has|have) (?:been )?|was |is now )?(?:successfully )?(?:closed|completed|consummated)\b', sentence, re.I)
        and not re.search(r'\bif\b|\bnot\b|\bwill\b|\bwould\b|\bmay\b|\bexpected\b|\banticipat\w*\b|\bpending\b|\bremains\b|\bto be (?:closed|completed|consummated)\b|\bsubject to\b|\bfiling\b|\bregistration statement\b', sentence, re.I)
        for sentence in re.split(r'(?<=[.;])\s+', t))


def merger_parent_name(t):
    # Bind the legal entity immediately preceding Parent, never across a clause.
    parent = re.search(r'\b([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,6},?\s+(?:Inc\.|Corporation|Corp\.|Limited|Ltd\.))'
                       r'(?:,?\s+a[n]?\s+[A-Za-z ]{1,50}\s+(?:corporation|company))?\s*\([“"]Parent[”"]\)', t)
    return parent.group(1) if parent else None



def merger_share_consideration(t):
    """Common-holder exchange terms; cash for awards/fractions is not deal cash."""
    for clause in re.split(r'(?<=[.;])\s+', t):
        if not re.search(r'each share|shareholders|stockholders', clause, re.I):
            continue
        for exchange in re.finditer(r'(?:converted into (?:the )?right to receive|will receive)\s*(?:\([ivx]+\)\s*)?.{0,400}?(\d+(?:\.\d+)?)\s+(?:shares\b|of a.{0,100}?share\b)', clause, re.I):
            source = clause[:exchange.start()]
            holders = list(re.finditer(r'\beach share\b|\b(?:common )?(?:shareholders|stockholders)\b', source, re.I))
            source = source[holders[-1].start():] if holders else source
            if re.search(r'preferred', source, re.I) or not re.search(r'common stock|common (?:shareholders|stockholders)', source, re.I):
                continue
            payout = re.split(r'\beach (?:outstanding |unvested |vested )?(?:option|warrant|award|restricted stock|share of .{0,60}?preferred stock)\b|\bholders of .{0,60}?preferred stock\b', clause[exchange.start():], maxsplit=1, flags=re.I)[0]
            if not re.search(r'common stock', payout, re.I):
                continue
            terms = {'consideration_type': 'STOCK', 'stock_exchange_ratio': float(exchange.group(1))}
            if re.search(r'common stock of the surviving corporation', payout, re.I):
                terms['stock_consideration_security'] = 'Surviving corporation common stock'
            else:
                owner = re.search(r'common stock.{0,70}?of\s+([A-Za-z]+)', payout, re.I)
                if not owner and re.search(r'Parent Common Stock', payout, re.I):
                    parent = merger_parent_name(t)
                    if parent:
                        owner = re.match(r'(.+)', parent)
                if owner:
                    terms['stock_consideration_security'] = owner.group(1).title() + ' common stock'
                    ticker = re.search(re.escape(owner.group(1).split()[0]) + r'.{0,80}?\(?(?:NASDAQ|NYSE)\s*:\s*([A-Z]+)', t, re.I)
                    if ticker:
                        terms['stock_consideration_ticker'] = ticker.group(1).upper()
            cash = re.search(r'\$\s*(\d+(?:\.\d+)?)\s+(?:per (?:common )?share\s+)?in cash', payout, re.I)
            if cash and not re.search(r'cash in lieu of fractional', payout[:cash.end()], re.I):
                terms.update(consideration_type='CASH_AND_STOCK', cash_per_share_usd=float(cash.group(1)))
                if re.search(r'downward adjustment.{0,100}net working capital shortfall', payout, re.I):
                    terms.update(cash_adjustment_direction='DOWNWARD', cash_adjustment_basis='NET_WORKING_CAPITAL_SHORTFALL')
            return terms
    return {}

def liquidation_evidence(t):
    """Return operative liquidation clauses, not hypothetical security rights."""
    plan = r'(?:plan of (?:sale and )?liquidation|(?:liquidation|dissolution) plan)'
    distribution = r'liquidating (?:cash )?distribution'
    action = r'\b(?:approved|approves|adopted|adopts|declared|declares)\b'
    for sentence in re.split(r'(?<=[.;])\s+', t):
        if not re.search(r'\bliquidat(?:ion|ing)\b|\bdissolution\b', sentence, re.I):
            continue
        if re.search(r'\bif\b|\bunless\b|\bwould\b|\bmay (?:approve|adopt|declare|commence)\b|\b(?:not|never)\s+(?:yet\s+)?(?:approved|adopted|declared|commenced)|articles.{0,80}provide', sentence, re.I):
            continue
        if (re.search(action + r'.{0,100}(?:' + plan + '|' + distribution + ')', sentence, re.I)
                or re.search(plan + r'.{0,80}' + action, sentence, re.I)
                or re.search(r'\b(?:ongoing|continuing|commenced|undertaking|begun|initiated)\b.{0,35}\b(?:liquidation activities|(?:voluntary )?liquidation (?:process|proceedings))\b', sentence, re.I)):
            yield sentence


def current_liquidation(t):
    return next(liquidation_evidence(t), None) is not None


def adopted_rights_plan(t):
    for sentence in re.split(r'(?<=[.;])\s+', t):
        if re.search(r'\bif\b|\bunless\b|\bwould\b|\bmay\b|\b(?:not|never)\s+(?:yet\s+)?(?:adopted|approved)\b', sentence, re.I):
            continue
        if re.search(r'\b(?:adopted|approved)\b.{0,90}\b(?:stockholder|shareholder)(?: protection)? rights plan\b', sentence, re.I):
            return True
    return False


def resale_registration(t):
    for sentence in re.split(r'(?<=[.;])\s+', t[:2500]):
        if re.search(r'\bif\b|\bwould\b|\bmay\b|\bnot\b', sentence, re.I):
            continue
        if re.search(r'\b(?:company|registrant|issuer)\b.{0,40}registered for resale\b', sentence, re.I):
            return True
    return False


def closed_debt_equity_exchange(t):
    closed = any(re.search(r'\b(?:closed|completed|consummated)\b.{0,50}backstop exchange\b', sentence, re.I)
                 and not re.search(r'\bif\b|\bwill\b|\bmay\b|\bwould\b|\bnot\b|\bexpected\b', sentence, re.I)
                 for sentence in re.split(r'(?<=[.;])\s+', t))
    return bool(closed and re.search(r'\bnotes\b.{0,120}\bfor\b.{0,30}\b(?:shares of )?common stock\b', t, re.I))


def merger_consideration(t):
    # Financing proceeds and fractional-share cash are not cash merger prices.
    if re.search(r'all[- ]stock|stock[- ]for[- ]stock', t):
        return 'STOCK'
    if re.search(r'\$\s*\d+(?:\.\d+)?\s+(?:per share.{0,45}?in cash|in cash.{0,45}?per share)', t) or re.search(r'(?:shareholders|stockholders).{0,100}receive\s*\$\s*\d+(?:\.\d+)?\s+in cash', t):
        return 'CASH'
    if re.search(r'exchange ratio|converted into.{0,80}(?:shares of common stock|ordinary shares)', t):
        return 'STOCK'
    return 'UNVERIFIED'

def classify_event(text: str, *, cleaned=False) -> Tuple[str, int, str]:
    t = (text if cleaned else operative_text(text)).lower()
    terminal = bool(re.search(r'(?:separate existence.{0,60}ceased|ceased to exist as a separate entity)', t)
                    and re.search(r'converted into.{0,140}(?:cash|\$)|no longer.{0,50}(?:listed|traded)', t))
    anchor = None
    if terminal:
        anchor = 'TERMINAL_MERGER'
    elif re.search(r'(?:has |have |company |parties )terminated.{0,40}(?:merger|business combination) agreement|(?:merger|business combination) agreement (?:was|has been) terminated', t[:2500]):
        anchor = 'MERGER_TERMINATED'
    elif current_liquidation(t):
        anchor = 'LIQUIDATION_DISTRIBUTION'
    elif adopted_rights_plan(t):
        anchor = 'LISTING_CAPITAL_STRUCTURE'
    elif resale_registration(t):
        anchor = 'LISTING_CAPITAL_STRUCTURE'
    elif re.search(r'merger agreement|agreement and plan of merger|to be acquired', t) and re.search(r'contingent value right|\bcvr\b', t):
        anchor = {'STOCK': 'REVERSE_MERGER_CVR', 'CASH': 'MERGER_CASH_CVR', 'UNVERIFIED': 'MERGER_CVR_UNVERIFIED'}[merger_consideration(t)]
    elif completed_merger(t):
        anchor = 'MERGER_REVERSE_MERGER'
    elif (re.search(r'merger agreement|agreement and plan of merger', t)
          and not re.search(r'\bspac\b|special purpose acquisition|reverse merger', t)
          and merger_share_consideration(t)):
        anchor = 'MERGER_CASH_STOCK' if merger_share_consideration(t)['consideration_type'] == 'CASH_AND_STOCK' else 'MERGER_STOCK'
    elif re.search(r'(?:consummated|completed|closed).{0,100}initial public offering', t):
        anchor = 'IPO_COMPLETED'
    elif re.search(r'(?:entered into|amends and restates|executed|amended).{0,300}(?:credit(?: and security)? agreement|loan agreement)', t):
        anchor = 'DEBT_RESTRUCTURING'
    elif re.search(r'exchange agreement', t) and re.search(r'senior notes|principal amount|debt', t):
        anchor = 'DEBT_RESTRUCTURING'
    elif closed_debt_equity_exchange(t):
        anchor = 'DEBT_RESTRUCTURING'
    elif re.search(r'(?:entered into|executed|signed).{0,140}securities purchase agreement', t):
        anchor = 'STRATEGIC_INVESTMENT_PIPE'
    elif re.search(r'(?:entered into|signed|executed).{0,180}asset purchase agreement|completed.{0,80}(?:sale|acquisition)', t):
        anchor = 'ASSET_SALE_ACQUISITION'
    elif re.search(r'(?:forward|reverse) (?:stock|share) split', t):
        anchor = 'LISTING_CAPITAL_STRUCTURE'
    elif re.search(r'manufacturing.{0,70}agreement|supply agreement|contract extension', t):
        anchor = 'LARGE_CONTRACT'
    scores = {}
    for label, pats in EVENT_KEYWORDS.items():
        hits = sum(bool(re.search(p, t)) for p in pats)
        if hits:
            scores[label] = hits
    label = anchor or (max(scores, key=scores.get) if scores else "OTHER")
    proof = 0
    nonbinding = bool(re.search(r"\bnon[- ]binding\b|\bletter of intent\b|\bpreliminary\b|\bexplor(?:e|ing)\b|\bconsidering\b", t))
    if nonbinding:
        proof = 1
    else:
        if re.search(r"\bdefinitive agreement\b|\bbinding agreement\b|\bentered into\b|\bexecuted\b|\bsigned\b", t): proof = max(proof, 2)
        for sentence in re.split(r'(?<=[.;])\s+', t):
            if re.search(r'\bclosed\b|\bconsummated\b|\bcompleted\b|\bfunded\b|\beffected\b', sentence) and not re.search(r'\bif\b|\bnot\b|\bwill\b|\bwould\b|\bmay\b|\bexpected\b|\banticipat\w*\b|\bsubject to\b|\bupon\b', sentence):
                proof = max(proof, 3)
        if re.search(r"\bgo-live\b|\bcommenced operations\b|\brevenue recognized\b|\bcommercial operations\b|\bplaced into service\b", t): proof = max(proof, 4)
    if label in MERGER_KINDS and proof >= 3:
        # Completing a filing or funding a tranche does not close the merger.
        if not completed_merger(t):
            proof = 2
    if label in MERGER_KINDS and completed_merger(t):
        proof = 3
    if terminal:
        proof = 3
    if anchor == 'LISTING_CAPITAL_STRUCTURE' and adopted_rights_plan(t):
        proof = 2
    if anchor == 'LISTING_CAPITAL_STRUCTURE' and resale_registration(t):
        proof = 2
    if anchor == 'STRATEGIC_INVESTMENT_PIPE':
        for sentence in re.split(r'(?<=[.;])\s+', t):
            if re.search(r'\b(?:financing|private placement|investment)\b.{0,30}\b(?:closed|was completed|was consummated)\b', sentence) and not re.search(r'\bif\b|\bnot\b|\bwill\b|\bwould\b|\bmay\b|\bexpected\b|\bsubject to\b', sentence):
                proof = 3
    return label, proof, label.replace("_", " ").title() if label != "OTHER" else ""
