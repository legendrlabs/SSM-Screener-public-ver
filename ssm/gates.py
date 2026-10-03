from __future__ import annotations
from datetime import date
from .models import Candidate

def _age_days(iso_date, today=None):
    if not iso_date: return None
    today=today or date.today()
    return (today-date.fromisoformat(iso_date[:10])).days

def evaluate_gates(c: Candidate, cfg):
    reasons=[]
    if c.security_type not in {'COMMON_EQUITY', 'UNKNOWN'}: return 'EXCLUDED', [f'{c.security_type} security is outside the common-equity universe.']
    if c.event_status in {'TERMINAL', 'CANCELLED'}: return 'EXCLUDED', [f'Event status {c.event_status}; excluded from active research candidates.']
    if c.event_terms.get('post_transaction_ticker', c.ticker) != c.ticker: return 'DATA_HOLD', [f"Listing changed to {c.event_terms['post_transaction_ticker']}; ticker, price and share units require reconciliation."]
    if c.event_terms.get('capital_counts_require_reconciliation'): return 'DATA_HOLD', ['Completed-merger capital counts require reconciliation with current common shares and outstanding instruments.']
    if c.security_type == 'UNKNOWN': return 'DATA_HOLD', ['Listed security type is not verified from SEC registered classes.']
    if c.event_terms.get('capital_context', {}).get('reconciliation_required'):
        return 'DATA_HOLD', ['Capital issuance/use-of-proceeds context requires post-transaction FD reconciliation; liability improvement does not certify the cap table.']
    if any(x.get('context', {}).get('reconciliation_required') for x in c.event_terms.get('capital_context_history', [])):
        return 'DATA_HOLD', ['Interim capital context requires complete post-transaction FD reconciliation.']
    if not c.event_review_complete: return 'DATA_HOLD', ['Material event review is incomplete.']
    if c.event_type == 'MERGER_CVR_UNVERIFIED': return 'DATA_HOLD', ['Merger consideration structure is unverified; CVR alone does not establish cash consideration.']
    if c.event_type == 'DEBT_RESTRUCTURING':
        if c.event_terms.get('materiality') == 'ROUTINE': return 'REJECT', ['Routine credit amendment without a verified structural special-situation catalyst.']
        if c.event_terms.get('materiality') != 'STRUCTURAL': return 'DATA_HOLD', ['Structural debt catalyst materiality is unverified.']
    if c.exchange not in cfg["exchanges"]: return "REJECT", [f"Exchange {c.exchange!r} outside allowed universe."]
    if c.price is None or c.price <= 0: return "DATA_HOLD", ["Missing/stale market price."]
    if c.dilution.common_shares <= 0: return "DATA_HOLD", ["Common shares outstanding not resolved."]
    if c.share_count_conflict: return "DATA_HOLD", ["Companyfacts and cover-page share counts materially conflict."]
    if c.dilution.confidence == "low": return "DATA_HOLD", ["Cap table confidence is low."]
    mc=c.basic_market_cap()
    if mc is None: return "DATA_HOLD", ["Basic market cap unavailable."]
    if mc < cfg["market_cap_min"]: reasons.append("Below preferred market-cap floor.")
    if mc > cfg["market_cap_expand_max"]: return "REJECT", ["Market cap above expanded universe ceiling."]
    if mc > cfg["market_cap_max"]: reasons.append("Above preferred microcap range; retained as expanded-universe candidate.")
    event_age=_age_days(c.latest_event_date)
    if event_age is None: return "DATA_HOLD", ["Latest material event date unavailable."]
    if event_age > cfg["event_max_age_days"]: return "REJECT", [f"No material event within {cfg['event_max_age_days']} days."]
    fin_age=_age_days(c.latest_financial_filing_date)
    if fin_age is None: return "DATA_HOLD", ["Latest 10-Q/10-K date unavailable."]
    if fin_age > cfg["financial_filing_max_age_days"]: return "DATA_HOLD", ["Financial filing is stale."]
    if not c.financial_review_complete: return "DATA_HOLD", ["Latest 10-Q/10-K second-pass review is incomplete."]
    if c.adv20_usd is None: reasons.append("ADV20 unavailable.")
    elif c.adv20_usd < cfg["adv20_watch_min"]: return "REJECT", ["Too illiquid for practical execution."]
    elif c.adv20_usd < cfg["adv20_pass_min"]: reasons.append("Liquidity only qualifies for WATCH.")
    if c.event_proof <= 0: return "REJECT", ["No source-backed event proof."]
    if c.event_proof == 1: reasons.append("Event is preliminary/non-binding.")
    if c.event_status == 'LIQUIDATING': reasons.append('Liquidation in progress; distribution entitlement, due bills and terminal dates require review.')
    fd=c.dilution.fd_ratio
    if fd and fd >= 4: reasons.append(f"Extreme fully diluted overhang ({fd:.1f}x basic).")
    atm=c.atm_ratio()
    if atm and atm >= 1: reasons.append(f"Remaining ATM capacity >= basic market cap ({atm:.1f}x).")
    if sum([c.going_concern,c.nasdaq_deficiency,c.auditor_flag]) >= 2: reasons.append("Multiple critical solvency/listing/auditor risks.")
    return ("WATCH",reasons) if reasons else ("PASS",[])
