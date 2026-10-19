"""Whole-universe counterexamples, expressed with fictional source records."""
import pytest
from ssm.events import select_event, event_terms, event_status, _read_event_filing
from ssm.event_rules import classify_event
from ssm.financial_recapitalization import financial_capital_contexts

AGREEMENT = ('On September 1, 2026, Elm Inc. entered into an Agreement and Plan of Merger '
             'with Cedar Group, Inc. and Cedar Merger Sub, Inc. '
             'Each share of Common Stock will be converted into the right to receive '
             '$33.00 per share in cash and 0.4735 shares of Parent Common Stock.')
RECORD = {'form':'10-Q','filed':'2026-08-10','report_date':'2026-06-30','accession':'q','filename':'q'}

def row(text, filed, accession):
    kind, proof, summary = classify_event(text)
    return {'text':text,'combined_text':text,'narrative':text,'filed':filed,'accession':accession,
            'form':'8-K','sources':['https://example.test/'+accession],'summary':summary,
            'event_type':kind,'event_proof':proof,'event_status':event_status(text,kind,proof),
            'terms':event_terms(text,kind)}

@pytest.mark.parametrize('condition', [
    'The exchange ratio would be changed if a stock split occurs.',
    'The merger consideration may be revised if the parties execute another amendment.',
    'The cash consideration shall be adjusted in the event of a stock split.',
])
def test_conditional_adjustment_does_not_invalidate_operative_terms(condition):
    selected=select_event([row(AGREEMENT+' '+condition,'2026-09-01','contract')])
    assert selected['terms']['stock_exchange_ratio']==.4735
    assert selected['terms']['cash_per_share_usd']==33
    assert not selected['terms'].get('economics_reconciliation_required')

def test_enacted_cash_only_revision_keeps_unaffected_stock():
    follow=('Pursuant to the September 1, 2026 Agreement and Plan of Merger with Cedar Group, Inc. '
            'and Cedar Merger Sub, Inc., the parties revised the cash consideration. '
            'The revised cash amount is not disclosed.')
    selected=select_event([row(AGREEMENT,'2026-09-01','old'),row(follow,'2026-09-20','amend')])
    assert selected['terms'].get('economics_reconciliation_required')
    assert 'cash_per_share_usd' not in selected['terms']
    assert selected['terms']['stock_exchange_ratio']==.4735

@pytest.mark.parametrize('financing',[
    'In 2025, the Company sold preferred stock for $1.65 per share in cash.',
    'The SAFEs were converted into preferred stock at $1.65 per share.',
])
def test_financing_price_is_not_common_holder_merger_consideration(financing):
    text=('The Company completed its business combination on May 7, 2026. '
          +financing)
    assert 'cash_per_share_usd' not in event_terms(text,'MERGER_UNVERIFIED')

def test_issuer_signed_merger_is_not_replaced_by_target_asset_acquisition():
    text=('On September 10, 2026, Elm Inc. entered into a definitive Business Combination Agreement '
          'with Cedar Holdings, Inc. The merger remains pending. '
          'On September 23, 2026, Cedar completed its acquisition of Valley Assets LLC.')
    selected=select_event([row(text,'2026-09-30','update')])
    assert 'MERGER' in selected['event_type']
    assert selected['event_status']!='COMPLETED'

def test_counterparty_subsidiary_action_does_not_close_pending_issuer_merger():
    text=('On September 10, 2026, Elm Inc. entered into a Merger Agreement with Cedar Holdings, Inc. '
          'The merger remains pending. On September 23, 2026, Valley Assets LLC became a wholly owned '
          'subsidiary of Cedar Holdings, Inc. as a result of an unrelated asset acquisition.')
    selected=select_event([row(text,'2026-09-30','update')])
    assert selected['event_status']!='COMPLETED'

def test_contract_credit_boilerplate_does_not_select_debt_event():
    class SEC:
        def submission_text(self,url):
            if url=='primary':
                return 'Item 1.01. Elm Inc. entered into an Agreement and Plan of Merger with Cedar Inc. Exhibit 2.1.'
            return 'The Company previously entered into a credit agreement. This Agreement and Plan of Merger is signed.'
        def filing_documents(self,*args):
            return [{'type':'EX-2.1','url':'contract','description':'Agreement and Plan of Merger'}]
    selected=_read_event_filing(SEC(),'1',{'filename':'primary','form':'8-K','filed':'2026-09-30','accession':'signed'})
    assert 'MERGER' in selected['event_type']

def test_incomplete_retirement_identities_keep_distinct_records():
    text=('On June 9, 2026, the Company repaid in full the outstanding balance under the Citizens RBL. '
          'On June 9, 2026, the Company redeemed in full its ABS II Notes.')
    records=financial_capital_contexts(text,RECORD)
    assert len(records)==2
    assert len({r['capital_event_id'] for r in records})==2
    assert len({r['context']['retirements'][0]['retirement_event_id'] for r in records})==2

def test_funding_portion_does_not_mean_partial_retirement():
    text=('On June 9, 2026, the Company repaid in full the outstanding balance under its Senior Notes, '
          'using a portion of the proceeds of the private placement.')
    records=financial_capital_contexts(text,RECORD)
    assert records[0]['context']['retirements'][0]['whole_instrument'] is True

def test_contractual_optional_redemption_is_not_announced_capital_event():
    text=('The Company may redeem some or all of the Senior Notes at any time at its option. '
          'If the New Notes are redeemed, the Company may repay the New Notes at principal plus interest.')
    assert financial_capital_contexts(text,RECORD)==[]

def test_direct_common_cash_conversion_retains_consideration():
    text=('Elm Inc. entered into a Merger Agreement with Cedar Inc. '
          'Each share of common stock will be converted into $33.00 per share in cash.')
    assert event_terms(text,'MERGER_UNVERIFIED')['cash_per_share_usd']==33

def test_with_proceeds_portion_does_not_mean_partial_retirement():
    text=('On June 9, 2026, the Company redeemed all outstanding Series D Preferred Stock '
          'with a portion of the net proceeds from the PIPE.')
    context=financial_capital_contexts(text,RECORD)[0]['context']
    assert context['retirements'][0]['whole_instrument'] is True
    assert context['classification']=='HISTORICAL_INCLUDED'
