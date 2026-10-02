from ssm.models import Candidate,Dilution
from ssm.scoring import score_candidate

def test_dilution_penalty():
    a=Candidate(ticker="A",price=1,adv20_usd=1_000_000,event_proof=3,event_type="LARGE_CONTRACT",dilution=Dilution(common_shares=10_000_000,confidence="high"))
    b=Candidate(ticker="B",price=1,adv20_usd=1_000_000,event_proof=3,event_type="LARGE_CONTRACT",dilution=Dilution(common_shares=10_000_000,pre_funded_shares=30_000_000,confidence="high"))
    assert score_candidate(a)>score_candidate(b)
