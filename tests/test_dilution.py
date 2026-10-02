from ssm.dilution import heuristic_extract_dilution,apply_override

def test_prefunded_extract():
    d,_=heuristic_extract_dilution("Pre-funded warrants to purchase 9,972,424 shares of common stock.",11_591_000)
    assert d.pre_funded_shares==9_972_424
    assert d.near_fd_shares>d.common_shares

def test_override_wins():
    d,_=heuristic_extract_dilution("",10);d=apply_override(d,{"common_shares":20,"pre_funded_shares":5,"confidence":"high","source":"test"})
    assert d.common_shares==20 and d.pre_funded_shares==5 and d.confidence=="high"
