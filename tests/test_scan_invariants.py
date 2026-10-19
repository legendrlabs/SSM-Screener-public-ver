import importlib.util
from pathlib import Path
from ssm.models import Candidate,Dilution
from ssm.report import write_outputs
import json

def test_scan_output_includes_generalized_invariant_counts(tmp_path):
    from ssm.financial_recapitalization import financial_capital_contexts
    record=dict(form='10-Q',filed='2026-08-10',report_date='2026-06-30',accession='q',filename='q')
    included=financial_capital_contexts('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',record)
    current=financial_capital_contexts('On August 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',record)
    a=Candidate('A',event_terms={'financial_capital_context_history':included})
    b=Candidate('B',gate_status='DATA_HOLD',event_terms={'financial_capital_context_history':current})
    write_outputs([a,b],dict(max_candidates=5),tmp_path)
    assert (tmp_path/'validation_audit.json').exists()
    data=json.loads((tmp_path/'validation_audit.json').read_text())
    assert data['invariants']['historical_not_incremental']['observed']==1
    assert data['invariants']['unresolved_current_capital_held']['observed']==1
    assert data['invariants']['unresolved_current_capital_held']['violations']==0

def test_same_input_comparison_distinguishes_confidence_changes_from_gate_changes():
    spec=importlib.util.find_spec('ssm.validation_audit')
    assert spec is not None,'General audit and old/new comparison are not implemented'
    from ssm.validation_audit import compare_candidates
    old=[Candidate('A',gate_status='DATA_HOLD',dilution=Dilution(common_shares=1e7,confidence='low'))]
    new=[Candidate('A',gate_status='DATA_HOLD',dilution=Dilution(common_shares=1e7,confidence='medium'))]
    diff=compare_candidates(new,old)
    assert diff['matched_candidate_count']==1
    assert diff['confidence_low_to_resolved']==1
    assert diff['data_hold_released']==0

def test_report_keeps_historical_only_event_without_implying_pending_fd(tmp_path):
    from ssm.financial_recapitalization import financial_capital_contexts
    rows=financial_capital_contexts('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',
         dict(form='10-Q',filed='2026-08-10',report_date='2026-06-30',accession='q',filename='q'))
    c=Candidate('A',event_terms={'financial_capital_context_history':rows})
    write_outputs([c],dict(max_candidates=5),tmp_path)
    text=(tmp_path/'latest.md').read_text()
    assert 'HISTORICAL_INCLUDED' in text
    assert 'FD reconciliation pending' not in text
