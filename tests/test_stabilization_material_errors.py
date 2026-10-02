import json
from datetime import date, timedelta

from ssm.event_rules import classify_event, operative_text, merger_parent_name
from ssm.events import event_terms, event_status, review_material_events, same_merger_counterparty
from ssm.models import Candidate, Dilution
from ssm.gates import evaluate_gates


def test_introductory_closing_cannot_be_discarded_before_other_item_agreements():
    text = ('Cover page. Introductory Note The Merger closed and became effective on September 30, 2026. '
            'Item 1.01 The Company entered into a credit agreement. '
            'Item 2.01 The Introductory Note is incorporated by reference. Item 9.01 Financial Statements.')
    kind, proof, _ = classify_event(text)
    assert kind == 'MERGER_REVERSE_MERGER'
    assert proof == 3
    assert event_status(text, kind, proof) == 'COMPLETED'


def test_confirmed_merger_closing_is_not_overridden_by_other_preliminary_news():
    text = ('The parties completed their previously announced merger, effective October 1, 2026. '
            'The Company reported preliminary quarterly results and signed a non-binding customer MOU.')
    kind, proof, _ = classify_event(text)
    assert kind == 'MERGER_REVERSE_MERGER' and proof == 3


def test_cash_first_merger_terms_have_both_common_holder_payout_components():
    text = ('The Company entered into an Agreement and Plan of Merger with Beacon Group, Inc. ("Parent"). '
            'Each share of Company Common Stock will be cancelled and converted into the right to receive '
            '$33.00 per share in cash and 0.4735 shares of Parent Common Stock. '
            'Beacon Group, Inc. (Nasdaq: BECN) announced the transaction.')
    kind, _, _ = classify_event(text)
    assert kind == 'MERGER_CASH_STOCK'
    terms = event_terms(text, kind)
    assert terms['cash_per_share_usd'] == 33
    assert terms['stock_exchange_ratio'] == .4735
    assert terms['stock_consideration_ticker'] == 'BECN'


def test_completed_merger_capital_numbers_are_reported_without_fabricating_fd():
    text = ('Introductory Note The Merger closed on September 30, 2026. '
            'Unless noted otherwise, all references to share and per share amounts reflect the Reverse Stock Split. '
            'Immediately after giving effect to the Merger, there were approximately 13,407,360 shares of '
            'Combined Company common stock issued and outstanding with an aggregate of 16,048,110 shares '
            'issuable on a fully diluted basis. Our common stock will begin to trade under the ticker symbol “NEWC,”. '
            'Item 1.01 Registration rights agreement. Item 9.01 Exhibits.')
    terms = event_terms(text, 'MERGER_REVERSE_MERGER')
    assert terms['source_reported_post_merger_common_shares'] == 13_407_360
    assert terms['source_reported_post_merger_fd_shares'] == 16_048_110
    assert terms['reported_share_units'] == 'POST_REVERSE_SPLIT'
    assert terms['post_transaction_ticker'] == 'NEWC'
    c = Candidate('OLD', price=2, event_terms=terms, dilution=Dilution(common_shares=2_000_000, confidence='low'))
    assert c.basic_market_cap() is None and c.dilution.fd_ratio is None


def test_unreconciled_completed_merger_capital_cannot_become_trade_candidate():
    now = date.today().isoformat()
    c = Candidate('NEWC', exchange='Nasdaq', price=10, adv20_usd=500_000,
                  event_type='MERGER_REVERSE_MERGER', event_status='COMPLETED', event_proof=3,
                  latest_event_date=now, latest_financial_filing_date=now, financial_review_complete=True,
                  event_terms={'capital_counts_require_reconciliation': True},
                  dilution=Dilution(common_shares=5_000_000, confidence='high'))
    gate, _ = evaluate_gates(c, json.load(open('config/default.json')))
    assert gate == 'DATA_HOLD'
    assert c.to_dict()['fd_ratio'] is None
    assert c.basic_market_cap() is None


def test_common_and_replacement_securities_from_closing_are_not_omitted():
    text = ('The parties consummated the Merger. The Company issued approximately 134.6 million shares '
            'of Common Stock in addition to approximately 21.8 million Replacement Options '
            'and 28.6 million Replacement Warrants.')
    terms = event_terms(text, 'MERGER_REVERSE_MERGER')
    assert terms['new_common_shares_issued_reported'] == 134_600_000
    assert terms['replacement_options_reported'] == 21_800_000
    assert terms['replacement_warrants_reported'] == 28_600_000


def _source_provider(counterparty='Beacon Group, Inc.'):
    now = date.today().isoformat(); old = (date.today() - timedelta(days=70)).isoformat()
    class Sec:
        def submissions(self, cik):
            return {'filings': {'recent': {'form': ['8-K', '8-K'], 'filingDate': [now, old],
                    'items': ['8.01', '1.01'], 'accessionNumber': ['current', 'contract'],
                    'primaryDocument': ['update', 'contract']}}}
        def submission_text(self, url):
            if url.endswith('update'):
                return f'Item 8.01 {counterparty} and Acme filed their regulatory notices pursuant to the HSR Act, as amended. The Merger remains subject to the conditions set forth in the Merger Agreement. Item 9.01'
            return ('Item 1.01 Acme Inc. entered into an Agreement and Plan of Merger with Beacon Group, Inc. ("Parent"). '
                    'Each share of Common Stock will be converted into the right to receive $33.00 per share in cash '
                    'and 0.4735 shares of Parent Common Stock. Item 9.01')
    return Sec(), {'filename': 'edgar/data/1/current/update', 'filed': now, 'form': '8-K', 'accession': 'current'}


def test_regulatory_update_keeps_source_backed_terms_from_same_merger_beyond_scan_window():
    sec, filing = _source_provider()
    cfg = json.load(open('config/default.json'))
    selected, _, warnings = review_material_events(sec, '1', filing, cfg)
    assert not warnings
    assert selected['accession'] == 'current'
    assert selected['terms']['cash_per_share_usd'] == 33
    assert selected['terms']['stock_exchange_ratio'] == .4735
    assert selected['terms']['merger_terms_source_accession'] == 'contract'
    assert any('/contract/contract' in x for x in selected['sources'])


def test_other_counterparty_cannot_supply_old_merger_terms():
    sec, filing = _source_provider('DifferentBuyer')
    cfg = json.load(open('config/default.json'))
    selected, _, _ = review_material_events(sec, '1', filing, cfg)
    assert 'cash_per_share_usd' not in selected['terms']


def test_parent_definition_cannot_span_issuer_to_actual_buyer():
    text = 'Acme Inc. entered into an Agreement and Plan of Merger with Beacon Group, Inc. ("Parent").'
    assert merger_parent_name(text) == 'Beacon Group, Inc.'


def test_nonmaterial_press_release_cannot_replace_material_closing():
    now = date.today().isoformat(); closed = (date.today() - timedelta(days=1)).isoformat()
    class Sec:
        def submissions(self, cik):
            return {'filings': {'recent': {'form': ['8-K', '8-K'], 'filingDate': [now, closed],
                    'items': ['7.01,9.01', '2.01,9.01'], 'accessionNumber': ['press', 'closing'],
                    'primaryDocument': ['press', 'closing']}}}
        def submission_text(self, url):
            return ('Item 7.01 The Company announced its business combination under the merger agreement.'
                    if url.endswith('press') else 'Introductory Note The Merger closed. The Company issued 20 million shares of Common Stock. Item 2.01 Completion.')
    filing = {'filename': 'edgar/data/1/press/press', 'form': '8-K', 'filed': now, 'accession': 'press', 'items': '7.01,9.01'}
    selected, _, warnings = review_material_events(Sec(), '1', filing, json.load(open('config/default.json')))
    assert not warnings
    assert selected['accession'] == 'closing' and selected['event_status'] == 'COMPLETED'
    assert selected['terms']['new_common_shares_issued_reported'] == 20_000_000


def test_matching_brand_different_legal_buyer_cannot_supply_old_terms():
    sec, filing = _source_provider('Beacon Holdings, Inc.')
    selected, _, _ = review_material_events(sec, '1', filing, json.load(open('config/default.json')))
    assert 'cash_per_share_usd' not in selected['terms']


def test_short_counterparty_name_requires_explicit_source_alias():
    text = 'Acme Inc. entered into a merger agreement with Beacon Group, Inc. ("Parent").'
    prior = {'text': text, 'combined_text': text}
    current = 'Beacon and Acme filed regulatory notices.'
    assert not same_merger_counterparty(current, prior)
    prior['combined_text'] += ' Beacon Group, Inc. (Nasdaq: BECN) (“Beacon” or “the Company”) announced the merger.'
    assert same_merger_counterparty(current, prior)
    assert not same_merger_counterparty('Beacon Holdings, Inc. and Acme filed regulatory notices.', prior)


def test_exhibit_defined_alias_survives_primary_item_9_boundary():
    text = 'Item 1.01 Acme Inc. signed a merger with Beacon Group, Inc. ("Parent"). Item 9.01 Exhibits.'
    exhibit = 'Beacon Group, Inc. (Nasdaq: BECN) (“Beacon” or “the Company”) announced the merger.'
    prior = {'text': text, 'combined_text': text + exhibit, 'narrative': operative_text(text) + exhibit}
    assert same_merger_counterparty('Beacon and Acme filed regulatory notices.', prior)
