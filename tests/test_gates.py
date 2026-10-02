from datetime import date
from ssm.models import Candidate,Dilution
from ssm.gates import evaluate_gates
CFG={"exchanges":["Nasdaq","NYSE","NYSE American"],"market_cap_min":20_000_000,"market_cap_max":500_000_000,"market_cap_expand_max":1_000_000_000,"adv20_pass_min":250_000,"adv20_watch_min":50_000,"event_max_age_days":60,"financial_filing_max_age_days":210}
def base():
    today=date.today().isoformat();return Candidate(ticker="TEST",exchange="Nasdaq",price=5,adv20_usd=500_000,latest_event_date=today,latest_financial_filing_date=today,financial_review_complete=True,event_proof=3,dilution=Dilution(common_shares=10_000_000,confidence="high"))
def test_pass():assert evaluate_gates(base(),CFG)[0]=="PASS"
def test_hold():c=base();c.dilution.confidence="low";assert evaluate_gates(c,CFG)[0]=="DATA_HOLD"
def test_illiquid():c=base();c.adv20_usd=10_000;assert evaluate_gates(c,CFG)[0]=="REJECT"


def test_financial_review_required():
    c=base();c.financial_review_complete=False
    assert evaluate_gates(c,CFG)[0]=="DATA_HOLD"


def test_share_count_conflict_holds():
    c=base();c.share_count_conflict=True
    assert evaluate_gates(c,CFG)[0]=="DATA_HOLD"
