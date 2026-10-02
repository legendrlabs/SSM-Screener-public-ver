import json
from datetime import date

import pytest

from ssm.event_rules import classify_event
from ssm.events import event_status, event_terms, select_event
from ssm.models import Candidate, Dilution
from ssm.report import write_outputs
from ssm.scoring import score_candidate

GPRO = ('The Company entered into a Merger Agreement with Parent. Merger Sub will merge with and into '
        'the Company, with the Company continuing as the surviving corporation and a subsidiary of Parent. '
        'Each share of Company Common Stock will be canceled and automatically converted into the right to receive '
        '(i) 0.1 of a validly issued, fully paid and nonassessable share of common stock of the surviving corporation '
        'and (ii) $1.14 in cash, subject to a potential downward adjustment for any net working capital shortfall below a threshold.')
CBNK = ('Capital and Peoples entered into an Agreement and Plan of Merger. Capital will merge with and into Peoples, '
        'with Peoples continuing as the surviving corporation. Each share of Capital Common Stock will be converted '
        'into the right to receive 1.11 shares of common stock of Peoples. Holders will receive cash in lieu of fractional shares. '
        'Options will be canceled in exchange for cash. Peoples Bancorp (NASDAQ: PEBO) announced the merger.')
KLXE = ('The Company completed its subscription rights offering and closed the Backstop Exchange. '
        '24,975,001 shares of common stock were purchased pursuant to the exercise of subscription rights '
        'at the subscription price of $1.49 per whole share for gross proceeds of $37.2 million. '
        'Of the gross proceeds, $6.2 million will redeem the 2030 Notes. '
        'After giving effect to the Rights Offering and the Backstop Exchange, the Company expects to have '
        '105,677,168 shares of Common Stock issued and outstanding. '
        'The outstanding principal amount of the 2030 Notes will be reduced by $94.0 million as a result of '
        'the combination of par redemptions and the exchange of 2030 Notes for Common Stock in the Backstop Exchange. '
        'An aggregate of 59,273,445 shares of Common Stock will be issued to the Backstop Parties in the Backstop Exchange.')


def test_mixed_common_holder_consideration_has_cash_stock_type_and_adjustment():
    kind, proof, _ = classify_event(GPRO)
    assert kind == 'MERGER_CASH_STOCK'
    assert event_status(GPRO, kind, proof) == 'SIGNED'
    terms = event_terms(GPRO, kind)
    assert terms['cash_per_share_usd'] == 1.14
    assert terms['stock_exchange_ratio'] == .1
    assert terms['stock_consideration_security'] == 'Surviving corporation common stock'
    assert terms['cash_adjustment_direction'] == 'DOWNWARD'
    assert terms['cash_adjustment_basis'] == 'NET_WORKING_CAPITAL_SHORTFALL'


def test_fractional_share_and_award_cash_do_not_turn_stock_merger_into_mixed_merger():
    kind, proof, _ = classify_event(CBNK)
    assert kind == 'MERGER_STOCK'
    assert event_status(CBNK, kind, proof) == 'SIGNED'
    terms = event_terms(CBNK, kind)
    assert terms['stock_exchange_ratio'] == 1.11
    assert terms['stock_consideration_ticker'] == 'PEBO'
    assert 'cash_per_share_usd' not in terms


def test_same_sentence_option_cash_cannot_become_common_merger_cash():
    text = ('The Company entered into a merger agreement. Each share of Common Stock will be converted '
            'into the right to receive 1.11 shares of Peoples common stock, and each outstanding option '
            'will be cancelled for $2 in cash.')
    kind, _, _ = classify_event(text)
    assert kind == 'MERGER_STOCK'
    terms = event_terms(text, kind)
    assert terms['stock_exchange_ratio'] == 1.11
    assert 'cash_per_share_usd' not in terms


@pytest.mark.parametrize('separator', ['. ', ', and '])
def test_preferred_to_common_exchange_cannot_override_common_holder_ratio(separator):
    text = ('The Company entered into a merger agreement. Each share of Series A preferred stock '
            'will be converted into the right to receive 4 shares of common stock' + separator +
            'Each share of Company Common Stock will be converted into the right to receive '
            '1.11 shares of Peoples common stock.')
    kind, _, _ = classify_event(text)
    assert kind == 'MERGER_STOCK'
    assert event_terms(text, kind)['stock_exchange_ratio'] == 1.11


def test_rights_and_backstop_terms_preserve_expected_scope_without_changing_current_fd():
    terms = event_terms(KLXE, 'DEBT_RESTRUCTURING')
    assert terms['rights_offering_shares'] == 24_975_001
    assert terms['rights_subscription_price_usd'] == 1.49
    assert terms['rights_gross_proceeds_usd'] == 37_200_000
    assert terms['backstop_exchange_common_shares'] == 59_273_445
    assert terms['combined_notes_principal_reduction_usd'] == 94_000_000
    assert terms['debt_principal_reduction_status'] == 'EXPECTED'
    assert terms['expected_post_transaction_common_shares'] == 105_677_168
    c = Candidate('KLXE', event_terms=terms, dilution=Dilution(common_shares=21_000_000, confidence='low'))
    assert c.dilution.common_shares == 21_000_000 and c.dilution.fd_ratio is None


def test_new_merger_types_retain_lifecycle_priority_and_catalyst_score():
    for kind in ('MERGER_CASH_STOCK', 'MERGER_STOCK'):
        selected = select_event([{'event_type': kind, 'filed': '2026-09-01', 'accession': 'merger'},
                                 {'event_type': 'LARGE_CONTRACT', 'filed': '2026-10-01', 'accession': 'routine'}])
        assert selected['accession'] == 'merger'
        c = Candidate('X', event_type=kind, event_proof=2)
        assert score_candidate(c) == 40


def test_readable_report_exposes_common_holder_payout_and_expected_debt_scope(tmp_path):
    cases = [Candidate('GPRO', event_type='MERGER_CASH_STOCK', event_status='SIGNED', event_terms={
        'cash_per_share_usd': 1.14, 'stock_exchange_ratio': .1,
        'stock_consideration_security': 'Surviving corporation common stock',
        'cash_adjustment_direction': 'DOWNWARD', 'cash_adjustment_basis': 'NET_WORKING_CAPITAL_SHORTFALL'}),
        Candidate('CBNK', event_type='MERGER_STOCK', event_status='SIGNED', event_terms={
        'consideration_type': 'STOCK', 'stock_exchange_ratio': 1.11, 'stock_consideration_ticker': 'PEBO'}),
        Candidate('KLXE', event_type='DEBT_RESTRUCTURING', event_status='COMPLETED', event_terms={
        'capital_structure_action': 'DEBT_EQUITY_EXCHANGE', 'materiality': 'STRUCTURAL',
        'rights_offering_shares': 24_975_001, 'rights_subscription_price_usd': 1.49,
        'rights_gross_proceeds_usd': 37_200_000, 'combined_notes_principal_reduction_usd': 94_000_000,
        'debt_principal_reduction_status': 'EXPECTED', 'expected_post_transaction_common_shares': 105_677_168})]
    write_outputs(cases, {'max_candidates': 5}, tmp_path)
    md = (tmp_path / 'latest.md').read_text()
    assert '**GPRO**' in md and '$1.14' in md and '0.1' in md and 'downward' in md.lower()
    assert '**CBNK**' in md and '1.11' in md and 'PEBO' in md
    cbnk_line = next(line for line in md.splitlines() if '**CBNK**' in line)
    assert 'Pro forma ownership' not in cbnk_line
    assert '24,975,001' in md and '$1.49' in md and '$37.2M' in md
    assert '$94.0M' in md and '105,677,168' in md and 'expected' in md.lower()
