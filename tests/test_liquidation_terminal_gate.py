"""Terminal common-share liquidation must not remain an investable WATCH."""
from ssm.events import event_terms
from ssm.gates import evaluate_gates
from ssm.models import Candidate


def test_terminal_common_share_evidence_extracted():
    text = ('The Board declared a liquidating distribution of $1.74 per common share. '
            'The common shares have been cancelled following dissolution.')
    assert event_terms(text, 'LIQUIDATION_DISTRIBUTION')['liquidation_common_trading_terminated'] is True


def test_planned_terminal_date_does_not_prove_completion():
    text = ('The Board declared a liquidating distribution of $1.74 per common share. '
            'The common shares are expected to be cancelled on December 1, 2026.')
    assert not event_terms(text, 'LIQUIDATION_DISTRIBUTION').get('liquidation_common_trading_terminated')


def test_terminal_common_gate_precedes_market_and_dilution_gates():
    candidate = Candidate(ticker='TEST')
    candidate.event_type = 'LIQUIDATION_DISTRIBUTION'
    candidate.event_status = 'LIQUIDATING'
    candidate.event_terms = {'liquidation_common_trading_terminated': True}
    status, reasons = evaluate_gates(candidate, {})
    assert status == 'EXCLUDED'
    assert 'ceased trading' in reasons[0]
