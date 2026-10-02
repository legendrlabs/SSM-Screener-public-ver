import json
from datetime import date

import pytest

from ssm.event_rules import classify_event
from ssm.events import event_terms, review_material_events
from ssm.gates import evaluate_gates
from ssm.models import Candidate
from ssm.report import write_outputs


def test_foreign_purchase_price_retains_currency_disclosed_conversion_and_earnout(tmp_path):
    text = ('The aggregate purchase price of C$159.0 million in cash is subject to adjustments. '
            'Sellers are eligible for a contingent earnout payment of up to C$10.0 million. '
            'The cash consideration paid in the acquisition was approximately US$113 million in cash.')
    terms = event_terms(text, 'ASSET_SALE_ACQUISITION')
    assert terms['sale_price_amount'] == 159_000_000
    assert terms['sale_price_currency'] == 'CAD'
    assert terms['sale_price_estimate_usd'] == 113_000_000
    assert terms['usd_equivalent_source'] == 'ISSUER_DISCLOSED'
    assert terms['earnout_max_amount'] == 10_000_000
    assert terms['earnout_currency'] == 'CAD'
    assert terms['earnout_conditional'] is True
    c = Candidate('BUYER', event_type='ASSET_SALE_ACQUISITION', event_status='COMPLETED', event_terms=terms)
    write_outputs([c], json.load(open('config/default.json')), tmp_path)
    report = (tmp_path / 'latest.md').read_text()
    assert 'C$159.0M' in report and 'US$113.0M' in report and 'C$10.0M' in report
    assert 'Sale price estimate: $159.0M' not in report


@pytest.mark.parametrize('prefix,currency', [('C$', 'CAD'), ('A$', 'AUD'), ('HK$', 'HKD')])
def test_foreign_price_without_disclosed_usd_never_becomes_usd(prefix, currency):
    terms = event_terms(f'An aggregate purchase price of {prefix}159 million in cash.', 'ASSET_SALE_ACQUISITION')
    assert terms['sale_price_amount'] == 159_000_000
    assert terms['sale_price_currency'] == currency
    assert 'sale_price_estimate_usd' not in terms


def test_usd_purchase_price_keeps_existing_usd_economics():
    terms = event_terms('The aggregate purchase price is $24.8 million in cash.', 'ASSET_SALE_ACQUISITION')
    assert terms['sale_price_estimate_usd'] == 24_800_000


def test_unrelated_usd_acquisition_cannot_supply_foreign_purchase_conversion():
    terms = event_terms('The aggregate purchase price is C$159 million. The Company acquired OtherCo for US$8 million.', 'ASSET_SALE_ACQUISITION')
    assert terms['sale_price_currency'] == 'CAD'
    assert 'sale_price_estimate_usd' not in terms


def _closing_provider(*, completed=True, common=True):
    now = date.today().isoformat()
    class Sec:
        def submissions(self, cik):
            return {'filings': {'recent': {'form': ['8-K', '8-K', '25-NSE'],
                    'filingDate': [now, now, now], 'items': ['7.01,9.01', '1.01,2.03', ''],
                    'accessionNumber': ['press', 'loan', 'removal'], 'primaryDocument': ['press', 'loan', 'removal']}}}
        def submission_text(self, url):
            if url.endswith('press'):
                state = 'announcing the closing' if completed else 'announcing the expected closing'
                return (f'Item 7.01 New Parent issued a press release {state} of its business combination with the Company. '
                        'The ordinary shares of the combined company will commence trading under the ticker symbol “NEWP.” Item 9.01')
            if url.endswith('removal'):
                security = 'Ordinary Shares, Rights, and Unit' if common else 'Preferred Stock'
                return f'<table><tr><td>{security}</td></tr><tr><td><input type="checkbox" disabled checked>17 CFR 240.12d2-2(a)(3)</td></tr></table>'
            return 'Item 1.01 The Company entered into a loan agreement. Its business combination remains subject to closing conditions.'
    return Sec(), {'filename': 'edgar/data/1/loan/loan', 'form': '8-K', 'filed': now, 'accession': 'loan', 'items': '1.01,2.03'}


def test_closing_press_and_exchanged_common_class_remove_old_listing_from_candidates(tmp_path):
    sec, filing = _closing_provider()
    cfg = json.load(open('config/default.json'))
    selected, _, warnings = review_material_events(sec, '1', filing, cfg)
    assert not warnings
    assert selected['accession'] == 'press'
    assert selected['event_status'] == 'TERMINAL'
    assert selected['event_proof'] == 3
    assert selected['terms']['post_transaction_ticker'] == 'NEWP'
    assert selected['terms']['listing_termination_source_accession'] == 'removal'
    assert any('/removal/' in u for u in selected['sources'])
    c = Candidate('OLD', event_type=selected['event_type'], event_status=selected['event_status'],
                  event_proof=selected['event_proof'], event_terms=selected['terms'])
    c.gate_status, _ = evaluate_gates(c, cfg)
    assert c.gate_status == 'EXCLUDED'
    write_outputs([c], cfg, tmp_path)
    assert json.loads((tmp_path / 'quality.json').read_text())['SAFE_TO_ACT'] is False
    assert 'Material special situations' not in (tmp_path / 'latest.md').read_text()


@pytest.mark.parametrize('completed,common', [(False, True), (True, False)])
def test_future_closing_or_other_security_removal_cannot_terminate_common_merger(completed, common):
    sec, filing = _closing_provider(completed=completed, common=common)
    selected, _, warnings = review_material_events(sec, '1', filing, json.load(open('config/default.json')))
    assert not warnings
    assert selected['event_status'] != 'TERMINAL'
    if completed:
        assert selected['event_status'] == 'COMPLETED'


def test_announced_completion_is_not_a_filing_or_financing_completion():
    kind, proof, _ = classify_event('The Company issued a press release announcing the completion of its business combination.')
    assert kind == 'MERGER_REVERSE_MERGER' and proof == 3
    _, proof, _ = classify_event('The Company entered into a merger agreement. The Company announced completion of the registration statement.')
    assert proof < 3


@pytest.mark.parametrize('tail', ['is scheduled for October 5, 2026.', ', scheduled to occur next week.', 'is planned for next week.'])
def test_scheduled_closing_announcement_does_not_complete_merger(tail):
    _, proof, _ = classify_event('The Company announced the closing of its business combination ' + tail)
    assert proof < 3
