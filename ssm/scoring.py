from .models import Candidate

def score_candidate(c: Candidate) -> float:
    if c.gate_status == 'EXCLUDED': return 0.0
    s={0:0,1:8,2:17,3:23,4:28}.get(c.event_proof,0)
    nav=c.nav_coverage()
    if nav is not None:
        s += 18 if nav>=2 else 15 if nav>=1.5 else 11 if nav>=1 else 6 if nav>=.7 else 0
    elif c.net_cash_usd is not None and c.strict_fd_market_cap():
        r=c.net_cash_usd/c.strict_fd_market_cap(); s += 12 if r>=.75 else 8 if r>=.4 else 4 if r>=.2 else 0
    if c.event_type in {"MERGER_REVERSE_MERGER","MERGER_CASH_STOCK","MERGER_STOCK","MERGER_CASH_CVR","REVERSE_MERGER_CVR","LIQUIDATION_DISTRIBUTION","ASSET_SALE_ACQUISITION","STRATEGIC_INVESTMENT_PIPE","LARGE_CONTRACT"}: s+=18
    elif c.event_type == "BUSINESS_PIVOT" or (c.event_type == "DEBT_RESTRUCTURING" and c.event_terms.get('materiality') == 'STRUCTURAL'): s+=14
    elif c.event_type=="LISTING_CAPITAL_STRUCTURE": s+=5
    adv=c.adv20_usd or 0; s += 12 if adv>=5_000_000 else 10 if adv>=1_000_000 else 8 if adv>=250_000 else 4 if adv>=50_000 else 0
    s += 12 if c.event_proof>=4 else 8 if c.event_proof==3 else 5 if c.event_proof==2 else 0
    fd=c.dilution.fd_ratio or 1; s -= 20 if fd>=4 else 14 if fd>=2.5 else 9 if fd>=1.75 else 4 if fd>=1.25 else 0
    atm=c.atm_ratio() or 0; s -= 12 if atm>=1 else 8 if atm>=.5 else 4 if atm>=.25 else 0
    s -= 8 if c.going_concern else 0; s -= 8 if c.nasdaq_deficiency else 0; s -= 5 if c.reverse_split else 0
    s -= 5 if c.related_party else 0; s -= 5 if c.vie_or_offshore else 0; s -= 10 if c.auditor_flag else 0
    return max(0.0,min(100.0,round(s,1)))

def bucket_candidate(c: Candidate) -> str:
    if c.gate_status=='EXCLUDED': return 'EXCLUDED'
    if c.gate_status=="DATA_HOLD": return "DATA_HOLD"
    if c.gate_status=="REJECT": return "REJECT"
    score=c.priority_score or 0
    if c.gate_status=="PASS" and score>=60: return "A_RESEARCH_NOW"
    if score>=40: return "B_WATCH"
    if score>=25: return "C_SPECULATIVE"
    return "REJECT"
