"""Transaction-level behavior, with fictional legal parties and independent values."""
from copy import deepcopy
import pytest
from ssm.events import select_event, event_terms, event_status
from ssm.event_rules import classify_event

AGREEMENT = ('On September 1, 2026, Elm Inc. entered into an Agreement and Plan of Merger '
             'with Cedar Group, Inc. ("Parent") and Cedar Merger Sub, Inc. '
             'Each share of Common Stock will be converted into the right to receive '
             '$33.00 per share in cash and 0.4735 shares of Parent Common Stock.')

def record(text, filed, accession):
    kind, proof, summary = classify_event(text)
    return dict(text=text, combined_text=text, narrative=text, filed=filed, accession=accession,
                form='8-K', sources=['https://example.test/'+accession], summary=summary,
                event_type=kind, event_proof=proof, event_status=event_status(text,kind,proof),
                terms=event_terms(text,kind))

def follow(statement):
    return ('Pursuant to the September 1, 2026 Agreement and Plan of Merger with Cedar Group, Inc. '
            'and Cedar Merger Sub, Inc., '+statement)

def test_latest_same_transaction_closing_supersedes_old_cvr_priority():
    old=record(AGREEMENT+' Holders also receive a contingent value right.','2026-09-01','old')
    close=record(follow('the Company completed the merger on October 1, 2026.'),'2026-10-02','close')
    selected=select_event([old,close])
    assert selected['event_status']=='COMPLETED'
    assert selected['terms']['transaction_date']=='2026-10-01'
    assert selected['terms']['cash_per_share_usd']==33
    assert selected['terms']['stock_exchange_ratio']==.4735
    assert selected['terms']['lifecycle_source_accession']=='close'

@pytest.mark.parametrize('statement',[
    'the Company expects to close the merger on October 1, 2026.',
    'the shareholders approved the merger. Financing completed.',
    'the registration statement became effective. The transaction remains pending.',
    'consideration will be paid upon completion of the merger.',
])
def test_terms_survive_followups_without_actual_closing(statement):
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(follow(statement),'2026-10-02','update')])
    assert selected['event_status']!='COMPLETED'
    assert selected['terms']['cash_per_share_usd']==33
    assert selected['terms']['stock_exchange_ratio']==.4735
    assert selected['terms']['economics_provenance']['cash_per_share_usd']['accession']=='old'

def test_amended_cash_supersedes_old_cash_and_preserves_explicit_unchanged_stock():
    amendment=follow('the Company entered into an amendment to the Merger Agreement. '
                     'Cash consideration per common share was increased to $35.00. '
                     'The stock exchange ratio remains unchanged.')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(amendment,'2026-09-20','amend')])
    assert selected['terms']['cash_per_share_usd']==35
    assert selected['terms']['stock_exchange_ratio']==.4735
    assert selected['terms']['economics_provenance']['cash_per_share_usd']['accession']=='amend'

def test_unspecified_changed_consideration_is_not_backfilled_as_valid():
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(follow(
        'The parties amended the merger consideration. Revised amounts require further disclosure.'),'2026-09-20','amend')])
    assert selected['terms'].get('economics_reconciliation_required')
    assert 'cash_per_share_usd' not in selected['terms']

def test_different_original_agreement_with_same_buyer_does_not_inherit_terms():
    new=record(AGREEMENT.replace('September 1','September 25').replace('$33.00','$10.00'),'2026-09-25','new')
    old=record(AGREEMENT,'2026-09-01','old')
    new['terms']={}
    selected=select_event([old,new])
    assert 'cash_per_share_usd' not in selected['terms']

def test_same_agreement_date_without_legal_party_match_cannot_join():
    different=record(follow('the merger closed.').replace('Cedar','Maple'),'2026-10-02','different')
    original=record(AGREEMENT,'2026-09-01','old')
    selected=select_event([original,different])
    assert 'cash_per_share_usd' not in selected['terms']

def test_different_deal_cannot_revive_terminated_transaction():
    terminate=record(follow('the parties terminated the merger agreement.'),'2026-09-20','terminate')
    other=record(AGREEMENT.replace('Cedar','Maple').replace('September 1','September 25'),'2026-09-25','other')
    original=record(AGREEMENT,'2026-09-01','old')
    selected=select_event([original,terminate,other])
    assert selected['accession']=='other'
    assert selected['event_status']=='SIGNED'

def test_merger_sub_or_surviving_target_does_not_prove_reverse_merger():
    text=AGREEMENT+' Merger Sub will merge into Elm Inc., which will survive as a wholly owned subsidiary of Parent.'
    assert classify_event(text)[0]=='MERGER_CASH_STOCK'
    cash=AGREEMENT.split(' and 0.4735')[0]+'.'
    assert classify_event(cash)[0]=='MERGER_CASH'

def test_selection_is_read_only_and_exchange_ratio_does_not_enter_capital_counts():
    rows=[record(AGREEMENT,'2026-09-01','old'),record(follow('regulatory approval was received.'),'2026-10-02','new')]
    before=deepcopy(rows)
    selected=select_event(rows)
    assert rows==before
    assert selected['terms']['stock_exchange_ratio']==.4735
    assert not selected['terms'].get('capital_context')

@pytest.mark.parametrize('statement',[
    'the effective time of the merger occurred on October 1, 2026.',
    'the transaction closed on October 1, 2026.',
    'the Company became a wholly owned subsidiary of Parent on October 1, 2026.',
    'the merger consideration was paid to common shareholders on October 1, 2026.',
])
def test_actual_non_keyword_closing_evidence_updates_lifecycle(statement):
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(follow(statement),'2026-10-02','new')])
    assert selected['event_status']=='COMPLETED'
    assert selected['terms']['transaction_date']=='2026-10-01'

def test_same_issuer_same_date_but_new_buyer_is_a_different_transaction():
    new=AGREEMENT.split('Each share')[0].replace('Cedar','Maple')+' Closing remains pending.'
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(new,'2026-09-02','different')])
    assert 'cash_per_share_usd' not in selected['terms']

def test_hypothetical_termination_fee_does_not_cancel_actual_signed_transaction():
    row=record(AGREEMENT+' If the Company terminated the merger agreement, Parent would receive a termination fee.','2026-09-01','old')
    assert row['event_status']=='SIGNED'

def test_closing_of_securities_purchase_does_not_close_pending_merger():
    update=follow('the merger remains pending. On September 20, 2026, the Company completed '
                  'the transaction contemplated by the Securities Purchase Agreement.')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(update,'2026-09-20','financing')])
    assert selected['event_status']!='COMPLETED'

def test_restated_prior_cash_does_not_override_actual_amended_cash():
    update=follow('common holders were entitled to $33.00 per share in cash. '
                  'The parties amended the merger consideration to $35.00 per share in cash. '
                  'The stock exchange ratio remains unchanged.')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(update,'2026-09-20','amend')])
    assert selected['terms']['cash_per_share_usd']==35

def test_parent_accounting_acquirer_alone_does_not_prove_reverse_merger():
    selected=select_event([record(AGREEMENT+' Parent has been identified as the accounting acquirer.','2026-09-01','old')])
    assert selected['event_type']=='MERGER_CASH_STOCK'

def test_calendar_may_does_not_invalidate_actual_closing():
    selected=select_event([record(AGREEMENT.replace('September 1','April 1'),'2026-04-01','old'),record(
        follow('the Company completed the merger on May 1, 2026.').replace('September 1','April 1'),'2026-05-02','new')])
    assert selected['event_status']=='COMPLETED'
    assert selected['terms']['transaction_date']=='2026-05-01'

def test_undated_bridge_cannot_merge_conflicting_original_agreement_dates():
    middle=record('Pursuant to the previously announced Merger Agreement with Cedar Group, Inc. and Cedar Merger Sub, Inc., regulatory approval was received.','2026-09-10','middle')
    later=record(AGREEMENT.split('Each share')[0].replace('September 1','September 25')+' Closing remains pending.','2026-09-25','new')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),middle,later])
    assert 'cash_per_share_usd' not in selected['terms']

def test_current_amended_price_precedes_original_contract_exhibit():
    updated=follow('Cash consideration per common share was increased to $35.00. The stock exchange ratio remains unchanged.')+'\n'+AGREEMENT
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(updated,'2026-09-20','amend')])
    assert selected['terms']['cash_per_share_usd']==35

def test_historical_financial_note_cannot_revalidate_invalidated_consideration():
    amend=record(follow('The parties amended the merger consideration. Revised amounts require further disclosure.'),'2026-09-20','amend')
    note=record(AGREEMENT,'2026-09-25','q');note['form']='10-Q'
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),amend,note])
    assert selected['terms'].get('economics_reconciliation_required')
    assert 'cash_per_share_usd' not in selected['terms']

def test_revised_stock_ratio_precedes_original_agreement_ratio():
    update=AGREEMENT+' The parties amended the stock exchange ratio to 0.6000 shares of Parent Common Stock. Cash consideration remains unchanged.'
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(update,'2026-09-20','amend')])
    assert selected['terms']['stock_exchange_ratio']==.6

def test_original_exhibit_cannot_revalidate_terms_in_any_followup_form():
    amend=record(follow('The parties amended the merger consideration. Revised amounts require further disclosure.'),'2026-09-20','amend')
    update=record(follow('regulatory approval was received. The transaction remains pending.')+'\n'+AGREEMENT,'2026-09-25','reg')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),amend,update])
    assert selected['terms'].get('economics_reconciliation_required')
    assert 'cash_per_share_usd' not in selected['terms']

def test_generic_close_requires_same_agreement_object_without_financing_denylist():
    update=follow('the merger remains pending. On September 20, 2026, the Company completed the transaction contemplated by the Subscription Agreement.')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(update,'2026-09-20','fin')])
    assert selected['event_status']!='COMPLETED'

def test_completed_separate_economic_object_does_not_close_merger():
    update=follow('the merger remains pending. On September 20, 2026, the Company completed the transaction involving the sale of 2 million shares of common stock to investors for gross proceeds of $10 million.')
    selected=select_event([record(AGREEMENT,'2026-09-01','old'),record(update,'2026-09-20','fin')])
    assert selected['event_status']!='COMPLETED'
