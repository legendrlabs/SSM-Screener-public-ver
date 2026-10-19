from ssm.financial_recapitalization import financial_capital_contexts
from ssm.models import Candidate, Dilution
from ssm.gates import evaluate_gates
import json

RECORD={'form':'10-Q','filed':'2026-08-10','report_date':'2026-06-30','accession':'q','filename':'q'}

def test_old_common_issuance_is_history_without_current_fd_downgrade():
    rows=financial_capital_contexts('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',RECORD)
    context=rows[0]['context']
    assert context['classification']=='HISTORICAL_INCLUDED'
    assert context['common_count_reconciliation']=='ALREADY_INCLUDED_OR_HISTORICAL'
    assert context['current_fd_impact']=='NONE'
    assert context['reconciliation_required'] is False
    assert context['actual_common_issued']==2e6 and context['read_only']

def test_subsequent_issuance_after_cover_requires_current_reconciliation():
    text=('As of July 15, 2026, there were 10,000,000 shares of common stock outstanding. PART I. '
          'On August 1, 2026, the Company issued 2 million shares of common stock in a PIPE.')
    cap=financial_capital_contexts(text,RECORD)[0]['context']
    assert cap['classification']=='CURRENT_RECONCILIATION_REQUIRED'
    assert cap['current_fd_impact']=='UNRESOLVED'
    assert cap['reconciliation_required'] is True

def test_old_partial_retirement_keeps_live_same_class_obligation_unresolved():
    text=('On March 1, 2026, the Company issued 2 million shares of common stock in the Private Placement. '
          'On March 2, 2026, the Company used the proceeds from the Private Placement to redeem a portion of Series D Preferred Stock for an aggregate redemption price of $10 million. '
          'On March 2, 2026, 100 shares of Series D Preferred Stock remained outstanding.')
    cap=financial_capital_contexts(text,RECORD)[0]['context']
    assert cap['reconciliation_required'] is True
    assert cap['actual_common_issued']==2e6
    assert cap['retirements'][0]['remaining_instrument_units']==100

def test_multiple_issuances_same_filing_keep_separate_stable_transaction_ids():
    text=('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE. '
          'On April 1, 2026, the Company issued 3 million shares of common stock in a public offering.')
    rows=financial_capital_contexts(text,RECORD)
    repeated=financial_capital_contexts(text,RECORD|{'accession':'other','filename':'other'})
    assert len(rows)==2
    ids=[r['capital_event_id'] for r in rows]
    assert len(set(ids))==2
    assert ids==[r['capital_event_id'] for r in repeated]

def test_history_does_not_waive_independent_fd_warning_or_promote_pass():
    rows=financial_capital_contexts('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',RECORD)
    c=Candidate('FICTION',exchange='Nasdaq',price=4,event_terms={'financial_capital_context_history':rows},dilution=Dilution(common_shares=1e7,confidence='low'))
    assert evaluate_gates(c,json.load(open('config/default.json')))[0]=='DATA_HOLD'

def test_unlinked_retirements_are_separate_from_financing_and_each_other():
    text=('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE. '
          'On April 1, 2026, the Company redeemed all outstanding Series A Preferred Stock for an aggregate redemption price of $10 million. '
          'On May 1, 2026, the Company redeemed all outstanding Series B Preferred Stock for an aggregate redemption price of $20 million.')
    rows=financial_capital_contexts(text,RECORD)
    assert len(rows)==3
    issued=next(r['context'] for r in rows if r['context']['actual_common_issued']==2e6)
    assert issued['retirements']==[]
    claims=[r['context']['retirements'][0] for r in rows if r['context']['retirements']]
    assert {c['cash_paid'] for c in claims}=={1e7,2e7}
    assert len({r['capital_event_id'] for r in rows})==3

def test_old_read_only_history_preserves_pipeline_confidence_and_common_count():
    from datetime import date
    from ssm.pipeline import build_candidate
    class Sec:
        def submissions(self,cik):return {'filings':{'recent':{}}}
        def latest_financial_record(self,cik):return RECORD
        def companyfacts(self,cik):return {}
        def relevant_exhibit_texts(self,*a,**kw):return []
        def submission_text(self,url):
            if url=='event':return 'The Company entered into a manufacturing supply agreement.'
            return ('As of July 15, 2026, there were 10,000,000 shares of common stock outstanding. PART I. '
                    'On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.')
    c=build_candidate(Sec(),dict(ticker='FICTION',name='Issuer',cik='1',exchange='Nasdaq',security_type='COMMON_EQUITY'),
                      dict(filename='event',filed=date.today().isoformat(),form='8-K',accession='current'),
                      {},json.load(open('config/default.json')),dict(price=4,adv20_usd=1e6))
    assert c.dilution.common_shares==1e7
    assert c.dilution.confidence=='medium'
    assert c.event_terms['financial_capital_context_history'][0]['context']['current_fd_impact']=='NONE'

def test_past_fully_retired_exchange_creates_no_current_incremental_shares():
    text=('On March 1, 2026, the Company exchanged all outstanding Series D Preferred Stock '
          'for 2 million newly issued shares of common stock.')
    cap=financial_capital_contexts(text,RECORD)[0]['context']
    assert cap['actual_common_issued']==2e6
    assert cap['reconciliation_required'] is False

def test_old_common_financing_with_fully_retired_preferred_is_only_history():
    text=('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE to fund redemption of Series D Preferred Stock. '
          'On March 2, 2026, the Company used the proceeds from the PIPE to redeem all outstanding Series D Preferred Stock for an aggregate redemption price of $10 million.')
    cap=financial_capital_contexts(text,RECORD)[0]['context']
    assert cap['link_verification']=='CONFIRMED'
    assert cap['reconciliation_required'] is False

def test_cover_market_value_date_is_not_common_count_date():
    record=RECORD|dict(form='10-K',filed='2027-02-20',report_date='2026-12-31')
    text=('The aggregate market value of voting common equity held by non-affiliates as of June 30, 2026 was $30 million. '
          'As of February 10, 2027, there were 10,000,000 shares of common stock outstanding. PART I. '
          'On October 1, 2026, the Company issued 2 million shares of common stock in a PIPE.')
    cap=financial_capital_contexts(text,record)[0]['context']
    assert cap['common_baseline_as_of']=='2027-02-10'
    assert cap['current_fd_impact']=='NONE'

def test_distinct_same_day_same_size_placements_keep_both_records():
    text=('On March 1, 2026, the Company issued 2 million shares of common stock to Alpha LLC in a private placement. '
          'On March 1, 2026, the Company issued 2 million shares of common stock to Beta LLC in a separate private placement.')
    rows=financial_capital_contexts(text,RECORD)
    assert len(rows)==2
    assert len({r['capital_event_id'] for r in rows})==2

def test_calendar_may_does_not_erase_historical_issuance():
    rows=financial_capital_contexts('On May 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',RECORD)
    assert len(rows)==1 and rows[0]['context']['actual_common_issued']==2e6
    assert rows[0]['context']['current_fd_impact']=='NONE'

def test_later_whole_class_extinction_resolves_old_partial_retirement_only():
    text=('On April 1, 2026, the Company used the proceeds from the PIPE to redeem a portion of Series D Preferred Stock for an aggregate redemption price of $10 million. '
          'On June 1, 2026, the Company redeemed all outstanding Series D Preferred Stock for an aggregate redemption price of $5 million.')
    rows=financial_capital_contexts(text,RECORD)
    assert len(rows)==2
    assert all(not r['context']['reconciliation_required'] for r in rows)
    assert rows[0]['context']['retirements'][0]['whole_instrument'] is False
    assert len({r['context']['retirements'][0]['retirement_event_id'] for r in rows})==2
