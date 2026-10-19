"""Merger taxonomy changes must not hide consideration or source evidence."""
import json
import pytest
from ssm.event_rules import classify_event
from ssm.events import event_terms
from ssm.models import Candidate, Dilution
from ssm.report import write_outputs


def test_classified_cash_merger_keeps_common_payout_and_source_while_on_hold(tmp_path):
    text=('The Company entered into a definitive merger agreement. '
          'Each share of common stock will be converted into the right to receive $33.00 per share in cash.')
    kind,proof,_=classify_event(text)
    assert kind=='MERGER_CASH'
    terms=event_terms(text,kind)
    assert terms['cash_per_share_usd']==33
    c=Candidate('CASH',event_type=kind,event_proof=proof,event_status='SIGNED',gate_status='DATA_HOLD',
        bucket='DATA_HOLD',event_terms=terms,event_sources=['https://www.sec.gov/Archives/fixture-cash'],
        dilution=Dilution(common_shares=1_000_000,confidence='low'))
    write_outputs([c],{'max_candidates':5},tmp_path)
    report=(tmp_path/'latest.md').read_text()
    assert '$33.00' in report
    assert 'https://www.sec.gov/Archives/fixture-cash' in report
    assert json.loads((tmp_path/'quality.json').read_text())['SAFE_TO_ACT'] is False


@pytest.mark.parametrize('kind',['MERGER_STOCK_CVR','REVERSE_MERGER','MERGER_UNVERIFIED'])
def test_new_merger_labels_remain_in_source_review_without_changing_hold(kind,tmp_path):
    source='https://www.sec.gov/Archives/fixture-'+kind.lower()
    c=Candidate('MERGER',event_type=kind,event_status='SIGNED',gate_status='DATA_HOLD',bucket='DATA_HOLD',
        event_terms={'stock_exchange_ratio':0.125,'cash_per_share_usd':2.5,'cvr_conditional':True},
        event_sources=[source],dilution=Dilution(common_shares=1_000_000,confidence='low'))
    write_outputs([c],{'max_candidates':5},tmp_path)
    report=(tmp_path/'latest.md').read_text()
    assert '## Material special situations' in report
    assert kind+' / SIGNED / DATA_HOLD' in report
    assert source in report
    assert '$2.50' in report
    quality=json.loads((tmp_path/'quality.json').read_text())
    assert quality['pass_count']==0 and quality['SAFE_TO_ACT'] is False
