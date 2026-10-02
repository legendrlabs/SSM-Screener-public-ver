from ssm.event_rules import classify_event

def test_definitive_merger():
    label,proof,_=classify_event("The company entered into a definitive merger agreement.")
    assert label=="MERGER_REVERSE_MERGER" and proof>=2

def test_nonbinding_loi():
    _,proof,_=classify_event("The parties signed a non-binding letter of intent to explore a transaction.")
    assert proof==1
