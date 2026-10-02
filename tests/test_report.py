import json
from ssm.report import write_outputs

def test_safe_to_act_false_when_no_a_candidates(tmp_path):
    write_outputs([], {"max_candidates": 5, "_sec_discovery_mode": "atom"}, tmp_path)
    quality = json.loads((tmp_path / "quality.json").read_text())
    assert quality["SAFE_TO_ACT"] is False
def test_unresolved_cap_table_does_not_report_complete_fd_economics(tmp_path):
    import csv, json
    from ssm.models import Candidate, Dilution
    from ssm.report import write_outputs
    c = Candidate(ticker='UNRESOLVED', price=5, dilution=Dilution(common_shares=10_000_000, confidence='low'))
    write_outputs([c], {'max_candidates': 5}, tmp_path)
    row = next(csv.DictReader((tmp_path / 'candidates.csv').open(encoding='utf-8-sig')))
    assert row['basic_market_cap'] == '50000000'
    assert row['near_fd_market_cap'] == ''
    assert row['strict_fd_market_cap'] == ''
    assert row['fd_ratio'] == ''
    dilution = next(csv.DictReader((tmp_path / 'dilution_check.csv').open(encoding='utf-8-sig')))
    assert dilution['near_fd_shares'] == ''
    assert dilution['strict_fd_shares'] == ''
    assert json.loads((tmp_path / 'quality.json').read_text())['SAFE_TO_ACT'] is False
