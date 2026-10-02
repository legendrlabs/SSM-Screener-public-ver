import json
from datetime import date

import pytest

from ssm.dilution import heuristic_extract_dilution
from ssm.event_rules import classify_event


@pytest.mark.parametrize('text,label', [
    ('The Company entered into a Fourth Amended and Restated Credit Agreement. Covenants restrict material acquisitions and pledge acquired assets.', 'DEBT_RESTRUCTURING'),
    ('The Company entered into an exchange agreement with holders of senior notes. New notes and warrants will replace old notes. Holders cannot acquire beneficial ownership exceeding 4.99%.', 'DEBT_RESTRUCTURING'),
    ('The Company declared a liquidating distribution after selling all remaining properties. Dissolution and the last day of trading are anticipated in November.', 'LIQUIDATION_DISTRIBUTION'),
    ('The Company signed a definitive merger agreement. Common stockholders will receive $6.28 in cash plus one non-tradable contingent value right.', 'MERGER_CASH_CVR'),
    ('At the effective time, all common shares were converted into $14.31 cash. The separate existence of the Company ceased and shares will no longer be listed or traded.', 'TERMINAL_MERGER'),
    ('The Fund effected a 3-for-1 forward share split. The split did not change total investment value.', 'LISTING_CAPITAL_STRUCTURE'),
])
def test_actual_transaction_anchors_outweigh_incidental_words(text, label):
    assert classify_event(text)[0] == label


def test_cash_sale_does_not_inherit_earnout_warning_from_cashflow_table():
    financial = ('<table><tr><td>Payments of accrued earnout</td><td>—</td><td>3,178</td></tr>'
                 '<tr><td>Proceeds from issuance of common stock</td><td>—</td><td>27,210</td></tr></table>'
                 '<p>The share repurchase authorization applies to outstanding common stock.</p>')
    d, warnings = heuristic_extract_dilution(financial, 10_000_000)
    assert d.confidence == 'medium'
    assert not any('earnout' in warning for warning in warnings)


def test_zero_preferred_prose_and_authorization_are_not_live_preferred():
    financial = ('The Company is authorized to issue 10,000,000 preferred shares. '
                 'The ability to issue preferred equity provides a financing tool. '
                 'As of June 30, 2026, no preferred shares were issued and outstanding.')
    d, warnings = heuristic_extract_dilution(financial, 10_000_000)
    assert d.confidence == 'medium'
    assert not any('preferred' in warning for warning in warnings)
    d, warnings = heuristic_extract_dilution(financial + ' On July 1, new Series B preferred shares were issued.', 10_000_000)
    assert d.confidence == 'low'
    d, warnings = heuristic_extract_dilution('As of June 30, 2026, no preferred shares were issued and outstanding, but on July 1, 2026, we issued 1,000 shares.', 10_000_000)
    assert d.confidence == 'low'
    assert any('preferred' in x for x in warnings)


def test_unselected_interim_warrant_tranche_cannot_be_erased_by_new_contract():
    from ssm.pipeline import build_candidate
    from datetime import timedelta
    today = date.today(); old = (today-timedelta(days=2)).isoformat(); latest=today.isoformat()
    class Sec:
        def submissions(self,cik):
            return {'filings':{'recent':{'form':['8-K'],'filingDate':[old], 'accessionNumber':['exchange'],
                    'primaryDocument':['exchange.htm'],'items':['1.01,3.02']}}}
        def latest_financial_record(self,cik):
            return {'filename':'financial','filed':(today-timedelta(days=30)).isoformat(),'form':'10-Q'}
        def companyfacts(self,cik):
            return {'facts':{'dei':{'EntityCommonStockSharesOutstanding':{'units':{'shares':[{'val':10_000_000,'filed':latest}]}}}}}
        def submission_text(self,filename):
            if filename=='contract':return 'The Company entered into a manufacturing supply agreement.'
            if filename=='financial':return 'Preferred stock, none issued.'
            return 'The Company entered into an exchange agreement for senior notes and warrants to purchase 1,000,000 shares at an exercise price of $1.87.'
        def relevant_exhibit_texts(self,*args,**kwargs):return []
    c=build_candidate(Sec(),{'ticker':'VIP','name':'Issuer','exchange':'Nasdaq','cik':'1','security_type':'COMMON_EQUITY'},
                      {'filename':'contract','filed':latest,'form':'8-K','accession':'contract','items':'1.01'},
                      {},json.load(open('config/default.json')),{'price':3,'adv20_usd':1_000_000})
    assert c.event_type=='LARGE_CONTRACT'
    assert c.gate_status=='DATA_HOLD'
    assert c.dilution.fd_ratio is None
    assert any('exchange' in x and 'Interim capital event' in x for x in c.data_warnings)


def test_new_pipe_warrant_tranche_does_not_merge_away_under_old_larger_baseline():
    from ssm.pipeline import build_candidate
    from datetime import timedelta
    today=date.today(); latest=today.isoformat(); old=(today-timedelta(days=2)).isoformat()
    class Sec:
        def submissions(self,cik):
            return {'filings':{'recent':{'form':['8-K'],'filingDate':[old],'accessionNumber':['pipe'],
                    'primaryDocument':['pipe.htm'],'items':['1.01,3.02']}}}
        def latest_financial_record(self,cik):
            return {'filename':'financial','filed':(today-timedelta(days=30)).isoformat(),'form':'10-Q'}
        def companyfacts(self,cik):
            return {'facts':{'dei':{'EntityCommonStockSharesOutstanding':{'units':{'shares':[{'val':10_000_000,'filed':latest}]}}}}}
        def submission_text(self,filename):
            if filename=='contract':return 'The Company entered into a manufacturing supply agreement.'
            if filename=='financial':return 'Warrants exercisable for 5,000,000 shares of common stock remained outstanding.'
            return 'The Company signed a securities purchase agreement and issued new warrants exercisable for 1,000,000 shares of common stock.'
        def relevant_exhibit_texts(self,*args,**kwargs):return []
    c=build_candidate(Sec(),{'ticker':'PIPE','name':'Issuer','exchange':'Nasdaq','cik':'1','security_type':'COMMON_EQUITY'},
                      {'filename':'contract','filed':latest,'form':'8-K','accession':'contract','items':'1.01'},
                      {},json.load(open('config/default.json')),{'price':3,'adv20_usd':1_000_000})
    assert c.gate_status=='DATA_HOLD' and c.dilution.fd_ratio is None
    assert any('tranche' in x and 'pipe' in x for x in c.data_warnings)


def test_conditional_termination_and_nonclosing_are_not_completed_events():
    from ssm.events import event_status
    merger = ('The Company entered into a merger agreement for $6.28 per share in cash plus a CVR. '
              'If the merger is consummated, shares will be delisted. The merger agreement may be terminated before closing. '
              'The parties may pay fees following termination of the merger agreement.')
    kind, proof, _ = classify_event(merger)
    assert kind == 'MERGER_CASH_CVR'
    assert event_status(merger, kind, proof) == 'SIGNED'
    sale = ('The Company entered into an Asset Purchase Agreement to sell its oxygen rental business for cash. '
            'A separate product supply agreement was announced. If the Transaction is not consummated, the repurchase increase will not become effective.')
    kind, proof, _ = classify_event(sale)
    assert kind == 'ASSET_SALE_ACQUISITION'
    assert event_status(sale, kind, proof) == 'SIGNED'


def test_pending_stock_purchase_consideration_cannot_show_fd_one():
    text = ('The Company signed an asset purchase agreement for a base purchase price of $6.95 million. '
            'One-half of the purchase price will be paid in Company common stock, to be issued after closing.')
    d, warnings = heuristic_extract_dilution(text, 10_000_000, event_context=True)
    assert d.confidence == 'low'
    assert d.fd_ratio is None
    assert d.pending_stock_consideration_usd == 3_475_000
    assert any('stock consideration' in warning for warning in warnings)


def test_live_stock_awards_require_reconciliation_not_zero():
    text = ('Potentially dilutive securities excluded due to a net loss include '
            'stock options, restricted stock units and performance stock units. '
            'Unvested equity awards remain outstanding.')
    d, warnings = heuristic_extract_dilution(text, 10_000_000)
    assert d.confidence == 'low'
    assert d.fd_ratio is None
    assert any('stock awards' in warning for warning in warnings)
    d, warnings = heuristic_extract_dilution('There are no unvested restricted stock units, but 1,000,000 stock options remain outstanding.', 10_000_000)
    assert d.confidence == 'low'
    assert any('stock awards' in warning for warning in warnings)


def test_security_type_comes_from_registered_class_not_cik():
    from ssm.securities import registered_securities, security_type
    cover = ('<table><tr><td>Title of each class</td><td>Trading Symbol</td><td>Name of each exchange</td></tr>'
             '<tr><td>Class A common stock</td><td>VIP</td><td>Nasdaq</td></tr>'
             '<tr><td>8.50% Senior Notes due 2026</td><td>GREEL</td><td>Nasdaq</td></tr></table>')
    classes = registered_securities(cover)
    assert security_type(classes['VIP']) == 'COMMON_EQUITY'
    assert security_type(classes['GREEL']) == 'DEBT'
    assert security_type('Shares', issuer_name='The Zcash ETF') == 'FUND'
    assert security_type('Common shares of beneficial interest', issuer_name='Elme Communities') == 'COMMON_EQUITY'
    assert security_type('Unknown instrument') == 'UNKNOWN'
    assert security_type('Shares of Beneficial Interest', 'Elme Communities') == 'COMMON_EQUITY'
    split_cells = cover.replace('<td>Class A common stock</td>', '<td>Common Stock</td><td>$0.01 par value</td>')
    assert registered_securities(split_cells)['VIP'] == 'Common Stock $0.01 par value'


def test_older_active_merger_survives_newer_supply_contract():
    from ssm.events import select_event
    reviewed = [
        {'filed': '2026-09-29', 'event_type': 'LARGE_CONTRACT', 'event_status': 'SIGNED', 'accession': 'contract'},
        {'filed': '2026-09-28', 'event_type': 'MERGER_CASH_CVR', 'event_status': 'SIGNED', 'accession': 'merger'},
    ]
    assert select_event(reviewed)['accession'] == 'merger'
    reviewed.append({'filed': '2026-10-01', 'event_type': 'MERGER_TERMINATED', 'event_status': 'CANCELLED', 'accession': 'terminated'})
    assert select_event(reviewed)['accession'] == 'terminated'
    assert select_event([
        {'filed': '2026-09-10', 'event_type': 'ASSET_SALE_ACQUISITION', 'accession': 'asset'},
        {'filed': '2026-09-29', 'event_type': 'DEBT_RESTRUCTURING', 'accession': 'debt'},
    ])['accession'] == 'debt'


def test_warranties_are_not_security_warrants():
    d, warnings = heuristic_extract_dilution('Covenants include breach of representations and warranties.', 100)
    assert d.confidence == 'medium'
    assert not warnings


def test_liquidation_dates_do_not_borrow_due_bill_prose_or_heading_dates():
    from ssm.events import event_terms
    text = ('The Board declared a $1.74 per share liquidating distribution. '
            'The Special Dividend will be paid on October 22, 2026 to shareholders of record on October 9, 2026. '
            'October 23, 2026 ex-dividend date (this period of time from October 9, 2026 to October 22, 2026 represents due bills). '
            'Delisting and Dissolution On September 29, 2026 the Board approved a plan. '
            'The Company anticipates the last day of trading on the NYSE to be November 5, 2026. '
            'Voluntary dissolution, effective November 6, 2026, is intended.')
    terms = event_terms(text, 'LIQUIDATION_DISTRIBUTION')
    assert terms['payment_date'] == '2026-10-22'
    assert terms['ex_dividend_date'] == '2026-10-23'
    assert terms['last_trading_date'] == '2026-11-05'
    assert terms['dissolution_date'] == '2026-11-06'


def test_declared_distribution_and_illustrative_cvr_are_distinct_terms():
    from ssm.events import event_terms
    merger = ('Common shareholders will receive $6.28 per share in cash plus one non-tradable CVR. '
              'Assuming full performance milestone payments, the aggregate potential merger consideration is $9.67 per share.')
    terms = event_terms(merger, 'MERGER_CASH_CVR')
    assert terms['cash_per_share_usd'] == 6.28
    assert terms['illustrative_total_per_share_usd'] == 9.67
    assert 'guaranteed_total_per_share_usd' not in terms
    assert terms['cvr_transferable'] is False
    liquidation = ('The Board declared a $1.74 per share liquidating distribution, payable on October 22, 2026. '
                   'The record date is October 9, 2026 and the ex-dividend date is October 23, 2026. Due bills apply. '
                   'The last day of trading is expected to be November 5, 2026 and dissolution is planned for November 6, 2026.')
    terms = event_terms(liquidation, 'LIQUIDATION_DISTRIBUTION')
    assert terms['distribution_status'] == 'DECLARED'
    assert terms['distribution_per_share_usd'] == 1.74
    assert terms['payment_date'] == '2026-10-22'
    assert terms['due_bills'] is True
    assert terms['dissolution_status'] == 'PLANNED'


def test_debt_fund_and_terminal_events_are_excluded_before_capital_math():
    from ssm.models import Candidate, Dilution
    from ssm.gates import evaluate_gates
    from ssm.scoring import bucket_candidate
    cfg = json.load(open('config/default.json'))
    for kind, status in [('DEBT', 'SIGNED'), ('FUND', 'COMPLETED'), ('COMMON_EQUITY', 'TERMINAL')]:
        c = Candidate(ticker='EXCLUDED', security_type=kind, event_status=status,
                      price=10, dilution=Dilution(common_shares=1_000_000, confidence='medium'))
        c.gate_status, _ = evaluate_gates(c, cfg)
        assert c.gate_status == 'EXCLUDED'
        assert bucket_candidate(c) == 'EXCLUDED'
        assert c.basic_market_cap() is None


def test_cik_mapping_keeps_registered_share_and_note_symbols():
    from ssm.pipeline import _ticker_map
    class Sec:
        def exchange_tickers(self):
            return [{'cik': 1, 'ticker': ticker, 'name': 'Issuer', 'exchange': 'Nasdaq'} for ticker in ['VIP', 'GREEL']]
    by_cik, by_ticker = _ticker_map(Sec())
    assert [x['ticker'] for x in by_cik['1']] == ['VIP', 'GREEL']


def test_pipeline_retains_merger_and_press_release_beyond_exhibit_cap():
    from ssm.pipeline import build_candidate
    today = date.today().isoformat()
    class Sec:
        def submissions(self, cik):
            return {'filings': {'recent': {'form': ['8-K'], 'filingDate': [today],
                    'accessionNumber': ['merger'], 'items': ['1.01,9.01'], 'primaryDocument': ['merger.html']}}}
        def latest_financial_record(self, cik):
            return {'filename': 'financial', 'filed': today, 'form': '10-Q'}
        def companyfacts(self, cik):
            return {'facts': {'dei': {'EntityCommonStockSharesOutstanding': {'units': {'shares': [{'val': 10_000_000, 'filed': today}]}}}}}
        def submission_text(self, filename):
            if filename == 'contract': return 'The Company amended its manufacturing supply agreement.'
            if filename == 'financial': return 'Preferred stock, none issued.'
            if filename == 'release':
                return 'Common shareholders will receive $6.28 per share in cash plus a non-tradable CVR. Assuming full payments, aggregate potential merger consideration is $9.67 per share.'
            return 'The Company signed a definitive merger agreement plus contingent value rights. See Exhibit 99.1.'
        def filing_documents(self, *args):
            return [{'type': 'EX-10.1', 'url': 'irrelevant'}] * 8 + [{'type': 'EX-99.1', 'url': 'release'}]
        def relevant_exhibit_texts(self, *args, **kwargs): return []
    c = build_candidate(Sec(), {'ticker': 'LFCR', 'name': 'Issuer', 'exchange': 'Nasdaq', 'cik': '1', 'security_type': 'COMMON_EQUITY'},
                        {'filename': 'contract', 'filed': today, 'form': '8-K', 'accession': 'contract', 'items': '1.01'},
                        {}, json.load(open('config/default.json')), {'price': 6, 'adv20_usd': 1_000_000})
    assert c.latest_event_accession == 'merger'
    assert c.event_type == 'MERGER_CASH_CVR'
    assert c.event_status == 'SIGNED'
    assert c.event_terms['cash_per_share_usd'] == 6.28
    assert c.event_terms['illustrative_total_per_share_usd'] == 9.67
    assert 'release' in c.event_sources
    assert c.gate_status == 'DATA_HOLD'
