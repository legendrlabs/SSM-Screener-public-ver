import json
from datetime import date

import pytest

from ssm.event_rules import classify_event
from ssm.events import event_terms, event_status, select_event, review_material_events
from ssm.gates import evaluate_gates
from ssm.models import Candidate,Dilution
from ssm.scoring import bucket_candidate
from ssm.report import write_outputs


def test_spac_future_deadline_is_not_current_liquidation():
    ipo=('The Company consummated its initial public offering. If the Company does not complete a business combination '
         'by August 10, 2027, it will redeem the public shares and make a liquidating distribution and dissolve.')
    kind,proof,_=classify_event(ipo)
    assert kind=='IPO_COMPLETED'
    assert event_status(ipo,kind,proof)=='COMPLETED'
    assert not event_terms(ipo,kind).get('dissolution_status')
    merger='The Company entered into an Agreement and Plan of Merger with AIRE. The transaction remains subject to shareholder approval.'
    selected=select_event([{'event_type':kind,'filed':'2026-08-14','accession':'ipo'},
                           {'event_type':classify_event(merger)[0],'filed':'2026-09-30','accession':'merger'}])
    assert selected['accession']=='merger'


@pytest.mark.parametrize('text',[
    'If no business combination is completed, the Company will commence liquidation activities.',
    'The articles provide for a plan of sale and liquidation if no business combination is consummated by the future deadline.',
    'Shareholders may approve a plan of liquidation only if the proposed extension is not approved.',
    'The Board has not approved a plan of liquidation.',
])
def test_conditional_charter_language_is_not_a_liquidating_state(text):
    kind,proof,_=classify_event(text)
    assert kind!='LIQUIDATION_DISTRIBUTION'
    assert event_status(text,kind,proof)!='LIQUIDATING'


def test_real_liquidation_declaration_survives_conditional_boilerplate():
    text=('The Board approved an additional special liquidating distribution of $1.74 per common share. '
          'Sales of all remaining properties have been completed. If residual assets remain, they will transfer to a trust.')
    assert classify_event(text)[0]=='LIQUIDATION_DISTRIBUTION'


def test_all_stock_merger_cvr_has_ownership_but_no_fixed_cash_price():
    text=('The Company entered into an Agreement and Plan of Merger in an all-stock transaction. '
          'North stockholders (inclusive of investors in the Private Placement) are expected to own approximately 95.25% '
          'of the combined company and pre-Merger Company stockholders are expected to own approximately 4.75% of the combined company. '
          'Prior to the effective time the Company may declare one contingent value right per share. '
          'Payments depend on net proceeds, if any, from sale or licensing of legacy assets. No payment is guaranteed.')
    kind,proof,_=classify_event(text)
    assert kind=='REVERSE_MERGER_CVR'
    assert event_status(text,kind,proof)=='SIGNED'
    terms=event_terms(text,kind)
    assert terms['consideration_type']=='STOCK'
    assert terms['legacy_holder_ownership_pct']==4.75
    assert terms['target_and_financing_ownership_pct']==95.25
    assert terms['ownership_illustrative'] is True
    assert terms['cvr_conditional'] is True
    assert 'cash_per_share_usd' not in terms
    assert 'illustrative_total_per_share_usd' not in terms


def test_cvr_without_consideration_evidence_cannot_be_called_cash_merger():
    text='The Company entered into a merger agreement with a contingent value right. Consideration terms require further verification.'
    assert classify_event(text)[0]=='MERGER_CVR_UNVERIFIED'


def test_cash_at_closing_cvr_remains_distinct_from_pipe_cash_and_fractional_shares():
    cash='The Company entered into a merger agreement. Common shareholders will receive $6.28 per share in cash at closing plus a non-tradable contingent value right.'
    assert classify_event(cash)[0]=='MERGER_CASH_CVR'
    award_cash=cash + ' Outstanding awards will be cancelled and converted into the right to receive the common stock merger consideration.'
    assert classify_event(award_cash)[0]=='MERGER_CASH_CVR'
    stock=('The Company entered into a merger agreement in a stock-for-stock transaction with a contingent value right. '
           'A PIPE will raise $146 million in cash. Cash in lieu of fractional shares will be paid.')
    assert classify_event(stock)[0]=='REVERSE_MERGER_CVR'


def test_routine_credit_amendment_is_not_special_situation_pass(tmp_path):
    text=('The Company entered into a Fourth Amendment Agreement to its Credit and Security Agreement. '
          'The Fourth Amendment extends the maturity date from September 30, 2027 to September 30, 2029, '
          'reduces the aggregate revolving commitments from $500.0 million to $350.0 million and revises pricing grids. '
          'The Credit Agreement continues to contain customary events of default.')
    kind,proof,_=classify_event(text);terms=event_terms(text,kind)
    assert kind=='DEBT_RESTRUCTURING'
    assert terms['materiality']=='ROUTINE'
    assert terms['revolving_commitment_before_usd']==500_000_000
    assert terms['revolving_commitment_after_usd']==350_000_000
    assert terms['commitment_change_is_debt_reduction'] is False
    today=date.today().isoformat()
    c=Candidate(ticker='ULH',exchange='Nasdaq',price=20,adv20_usd=1_000_000,event_type=kind,event_terms=terms,
                event_proof=proof,event_status='SIGNED',latest_event_date=today,latest_financial_filing_date=today,
                financial_review_complete=True,dilution=Dilution(common_shares=10_000_000,confidence='medium'))
    cfg=json.load(open('config/default.json'))
    c.gate_status,reasons=evaluate_gates(c,cfg);c.data_warnings=reasons;c.bucket=bucket_candidate(c)
    assert c.gate_status==c.bucket=='REJECT'
    assert any('Routine' in x for x in reasons)
    write_outputs([c],cfg,tmp_path)
    assert json.loads((tmp_path/'quality.json').read_text())['pass_count']==0


def test_customary_default_clauses_do_not_create_a_structural_debt_catalyst():
    text='The Company amended its credit agreement to extend the maturity. Customary events of default include insolvency and failure to repay indebtedness.'
    assert event_terms(text,'DEBT_RESTRUCTURING')['materiality']=='ROUTINE'
    rescue='The Company entered into an exchange agreement to exchange old senior notes for new notes and warrants to purchase 1,000,000 shares at an exercise price of $1.87.'
    assert event_terms(rescue,'DEBT_RESTRUCTURING')['materiality']=='STRUCTURAL'


@pytest.mark.parametrize('clause',[
    'The lenders have not forgiven any debt.',
    'If a future bankruptcy occurs, lenders may have forgiven debt.',
])
def test_negative_or_conditional_debt_relief_is_not_structural(clause):
    text='The Company entered into an amendment to its credit agreement. '+clause
    assert event_terms(text,'DEBT_RESTRUCTURING')['materiality']=='ROUTINE'


def test_completed_debt_equity_exchange_is_structural_in_passive_voice():
    text='The Company amended its credit agreement. $100 million of notes were converted into common stock.'
    assert event_terms(text,'DEBT_RESTRUCTURING')['materiality']=='STRUCTURAL'


def test_stock_cvr_is_in_human_report_as_stock_ownership(tmp_path):
    c=Candidate(ticker='AEMD',event_type='REVERSE_MERGER_CVR',event_status='SIGNED',event_terms={
        'consideration_type':'STOCK','legacy_holder_ownership_pct':4.75,'target_and_financing_ownership_pct':95.25,
        'ownership_illustrative':True,'cvr_conditional':True,'cvr_basis':'Legacy asset monetization net proceeds'})
    write_outputs([c],{'max_candidates':5},tmp_path)
    md=(tmp_path/'latest.md').read_text()
    assert 'REVERSE_MERGER_CVR' in md and '4.75%' in md and '95.25%' in md
    assert 'Legacy asset monetization' in md
    assert 'Cash at closing' not in md


def test_incorporated_press_terms_survive_long_primary_and_prior_exhibit_caution():
    class Sec:
        def submissions(self,cik):return {'filings':{'recent':{'form':[]}}}
        def filing_documents(self,*args):return [{'type':'EX-99.1','url':'press1'},{'type':'EX-99.2','url':'press2'}]
        def submission_text(self,url):
            if url=='primary':return 'Item 1.01 The Company entered into a merger agreement with a CVR. '+('Background. '*2200)+' Exhibit 99.1 Item 9.01'
            if url=='press1':return 'Common shareholders receive $6.28 per share in cash. Forward Looking Statements Forecast disclaimer.'
            return 'The non-tradable CVR has aggregate potential merger consideration of $9.67 per share assuming full performance for illustration.'
    cfg=json.load(open('config/default.json'))
    selected,_,warnings=review_material_events(Sec(),'1',{'filename':'primary','filed':date.today().isoformat(),'form':'8-K','accession':'merger'},cfg)
    assert not warnings
    assert selected['event_type']=='MERGER_CASH_CVR'
    assert selected['terms']['cash_per_share_usd']==6.28
    assert selected['terms']['cvr_transferable'] is False
    assert selected['terms']['illustrative_total_per_share_usd']==9.67
