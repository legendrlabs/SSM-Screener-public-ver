import json
from datetime import date

import pytest

from ssm.events import event_terms
from ssm.gates import evaluate_gates
from ssm.models import Candidate, Dilution
from ssm.report import write_outputs


def context(text):
    return event_terms(text, 'STRATEGIC_INVESTMENT_PIPE')['capital_context']


def test_nnbr_authorized_increase_is_capacity_and_not_ninety_million_new_shares():
    text = ('Stockholders approved an Amended and Restated Certificate of Incorporation to increase '
            'the authorized number of shares of Common Stock from 90,000,000 shares to 180,000,000 shares. '
            'The Charter Amendments were effected on September 30, 2026.')
    c = context(text)
    assert c['authorized_capacity_increase'] == 90_000_000
    assert c['actual_common_issued'] == 0
    assert c['assessment'] == 'ISSUANCE_CAPACITY'
    d = Dilution(common_shares=82_580_446, confidence='medium')
    from ssm.recapitalization import reconcile_capital_context
    reconcile_capital_context(d, c, '', '2026-09-30', '2026-06-30')
    assert d.common_shares == 82_580_446 and d.fd_ratio == 1


def test_planned_alternative_common_or_prefunded_is_one_pending_share_equivalent_total():
    c = context('At closing, the Company will issue an aggregate of 16.1 million shares of common stock '
                '(or prefunded warrants in lieu thereof). The PIPE is expected to close on October 5, 2026. '
                'The Company will use the proceeds to redeem its remaining Series D Preferred Stock.')
    assert c['actual_common_issued'] == 0
    assert c['planned_common_equivalent_shares'] == 16_100_000
    assert c['use_of_proceeds'] == ['PREFERRED_REDEMPTION']
    assert c['retirements'][0]['status'] == 'PLANNED'
    assert c['confirmed_claim_reduction_usd'] == 0
    assert c['reconciliation_required'] is True


def test_completed_issue_and_preferred_redemption_show_both_sides_and_two_rates():
    text = ('Immediately before the transaction, 80 million shares of common stock were outstanding. '
            'The Company issued 25 million shares of common stock. '
            'The Company used the proceeds to redeem $70 million of Series D Preferred Stock. '
            'Annual preferred dividend expense was reduced by $7 million.')
    c = context(text)
    assert c['actual_common_issued'] == 25_000_000
    assert c['issuance_increase_pct'] == 31.25
    assert c['existing_holder_ownership_reduction_pct'] == pytest.approx(23.8095238095)
    assert c['confirmed_claim_reduction_usd'] == 70_000_000
    assert c['annual_fixed_charge_reduction_usd'] == 7_000_000
    assert c['assessment'] == 'RECAPITALIZATION_MIXED'


@pytest.mark.parametrize('purpose,expected', [
    ('repay its debt', 'DEBT_REPAYMENT'), ('redeem its preferred stock', 'PREFERRED_REDEMPTION'),
    ('fund the acquisition', 'ACQUISITION'), ('fund working capital', 'WORKING_CAPITAL'),
    ('fund general corporate purposes', 'GENERAL_CORPORATE')])
def test_proceeds_classification_requires_financing_use_clause(purpose, expected):
    c = context('The Company issued 2 million shares of common stock. The Company intends to use the proceeds to ' + purpose + '.')
    assert c['use_of_proceeds'] == [expected]


def test_unrelated_liabilities_cannot_supply_use_of_proceeds():
    c = context('The Company issued 2 million shares of common stock. A customer redeemed its preferred stock. The Company has debt.')
    assert c['use_of_proceeds'] == ['UNKNOWN']
    assert c['confirmed_claim_reduction_usd'] == 0
    assert c['assessment'] == 'UNKNOWN_USE_OF_PROCEEDS'


def test_unlinked_issuer_redemption_is_not_proof_of_equity_proceeds_use():
    c=context('The Company issued 2 million shares of common stock. On July 1, 2026, the Company redeemed $70 million of Series D Preferred Stock.')
    assert c['confirmed_claim_reduction_usd'] == 70e6
    assert c['use_of_proceeds'] == ['UNKNOWN']
    assert c['assessment'] == 'UNKNOWN_USE_OF_PROCEEDS'


def test_foreign_retirement_does_not_become_usd_and_future_payment_not_confirmed():
    c = context('The Company issued 2 million shares of common stock. The Company used the proceeds to repay C$10 million of debt. '
                'The Company will redeem $35 million of Series D Preferred Stock.')
    assert c['confirmed_claim_reduction_usd'] == 0
    assert c['retirements'][0]['currency'] == 'CAD'
    assert any(r['status'] == 'PLANNED' for r in c['retirements'])


def test_duplicate_narrative_is_not_additional_issuance_or_claim_reduction():
    text = 'The Company issued 2 million shares of common stock. The Company used the proceeds to repay $10 million of debt.'
    c = context(text + ' ' + text)
    assert c['actual_common_issued'] == 2_000_000
    assert c['confirmed_claim_reduction_usd'] == 10_000_000


def test_actual_issuance_without_pre_count_is_unresolved_not_fake_zero_rate():
    c = context('The Company issued 25 million shares of common stock. The proceeds will fund general corporate purposes.')
    assert c['issuance_increase_pct'] is None
    assert c['assessment'] == 'DILUTION_ONLY'
    assert c['reconciliation_required'] is True


def test_positive_context_does_not_override_gate_or_fd_hold(tmp_path):
    terms = event_terms('The Company issued 25 million shares of common stock. The Company used the proceeds to repay $70 million of debt.', 'STRATEGIC_INVESTMENT_PIPE')
    c = Candidate('TEST', exchange='Nasdaq', price=4, adv20_usd=1e6, event_type='STRATEGIC_INVESTMENT_PIPE',
                  event_status='COMPLETED', event_proof=3, event_terms=terms, latest_event_date=date.today().isoformat(),
                  latest_financial_filing_date=date.today().isoformat(),financial_review_complete=True,
                  dilution=Dilution(common_shares=80e6,confidence='high'))
    c.gate_status, _ = evaluate_gates(c, json.load(open('config/default.json')))
    assert c.gate_status == 'DATA_HOLD'
    write_outputs([c],json.load(open('config/default.json')),tmp_path)
    assert json.loads((tmp_path/'quality.json').read_text())['SAFE_TO_ACT'] is False
    assert '25,000,000' in (tmp_path/'latest.md').read_text()
    assert '70.0M' in (tmp_path/'latest.md').read_text()


def test_common_rebase_and_whole_named_conversion_remove_only_matched_instrument():
    from ssm.recapitalization import reconcile_capital_context
    text = ('Immediately before the transaction, 10 million shares of common stock were outstanding. '
            'The Company issued 5 million shares of common stock in exchange for all outstanding Series A Preferred Stock. '
            'All outstanding Series A Preferred Stock was extinguished.')
    c = context(text)
    d = Dilution(common_shares=10e6,preferred_shares_equiv=5e6,confidence='low')
    financial = 'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.'
    reconcile_capital_context(d,c,financial,'2026-10-01','2026-06-30')
    assert d.common_shares == 15e6
    assert d.preferred_shares_equiv == 0
    assert c['removed_fd_equivalents'] == 5e6
    assert d.fd_ratio is None


@pytest.mark.parametrize('common', [15e6, 13e6])
def test_post_count_is_not_incremented_again_and_unmatched_count_stays_hold(common):
    from ssm.recapitalization import reconcile_capital_context
    c = context('Immediately before the transaction, 10 million shares of common stock were outstanding. The Company issued 5 million shares of common stock. The proceeds fund working capital.')
    d = Dilution(common_shares=common,confidence='medium')
    reconcile_capital_context(d,c,'','2026-10-01','2026-06-30')
    assert d.common_shares == common
    assert d.fd_ratio is None


def test_partial_or_different_series_never_clears_financial_preferred_balance():
    from ssm.recapitalization import reconcile_capital_context
    for text in ['The Company redeemed a portion of Series A Preferred Stock.', 'All outstanding Series B Preferred Stock was extinguished.']:
        c=context('The Company issued 5 million shares of common stock. ' + text)
        d=Dilution(common_shares=10e6,preferred_shares_equiv=5e6,confidence='low')
        reconcile_capital_context(d,c,'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.','2026-10-01','2026-06-30')
        assert d.preferred_shares_equiv == 5e6 and d.fd_ratio is None


def test_pipeline_reconciles_common_and_retired_series_after_financial_merge():
    from ssm.pipeline import build_candidate
    event=('On June 1, 2026, the Company signed an agreement. '
           'Immediately before the transaction, 10 million shares of common stock were outstanding. '
           'On October 1, 2026, the Company issued 5 million shares of common stock in exchange for all outstanding Series A Preferred Stock. '
           'On October 1, 2026, all outstanding Series A Preferred Stock was extinguished.')
    class Sec:
        def submissions(self,cik):return {'filings':{'recent':{}}}
        def latest_financial_record(self,cik):return {'filename':'financial','filed':'2026-06-30','report_date':'2026-06-30','form':'10-Q'}
        def companyfacts(self,cik):return {}
        def submission_text(self,url):
            return event if url=='event' else ('As of June 30, 2026, there were 10,000,000 shares of common stock outstanding. '
                                            'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.')
        def relevant_exhibit_texts(self,*a,**kw):return []
    c=build_candidate(Sec(),{'ticker':'TEST','name':'Issuer','cik':'1','exchange':'Nasdaq','security_type':'COMMON_EQUITY'},
                      {'filename':'event','accession':'event','filed':date.today().isoformat(),'form':'8-K','items':'3.02'},
                      {},json.load(open('config/default.json')),{'price':4,'adv20_usd':1e6})
    assert c.dilution.common_shares==15e6
    assert c.dilution.preferred_shares_equiv==0
    assert c.dilution.fd_ratio is None and c.gate_status=='DATA_HOLD'


def test_agreed_upon_closing_is_planned_and_completed_alternative_is_not_all_common():
    pending = context('The Company has agreed to issue 5 million shares of common stock upon closing.')
    assert pending['actual_common_issued'] == 0
    assert pending['planned_common_equivalent_shares'] == 5e6
    alternative = context('The Company issued an aggregate of 16.1 million shares of common stock (or prefunded warrants in lieu thereof).')
    assert alternative['actual_common_issued'] is None
    assert alternative['actual_common_equivalent_shares'] == 16.1e6


def test_whole_retirement_marker_cannot_leak_between_instruments():
    from ssm.recapitalization import reconcile_capital_context
    c=context('The Company redeemed a portion of Series A Preferred Stock and repaid all outstanding debt.')
    d=Dilution(common_shares=10e6,preferred_shares_equiv=5e6,confidence='low')
    reconcile_capital_context(d,c,'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.','2026-10-01','2026-06-30')
    assert d.preferred_shares_equiv == 5e6
    assert not next(r for r in c['retirements'] if r['instrument_type']=='PREFERRED')['whole_instrument']


@pytest.mark.parametrize('retirement', [
    'The Company repaid all outstanding debt with proceeds from an asset sale for $70 million.',
    'The Company redeemed Series A Preferred Stock at $10 per share.',
    'The Company announced that an investor repaid $70 million of debt.',
])
def test_unrelated_or_unit_prices_and_other_subjects_do_not_become_claim_totals(retirement):
    c=context('The Company issued 2 million shares of common stock. '+retirement)
    assert c['confirmed_claim_reduction_usd'] == 0


def test_same_series_reissuance_blocks_retirement_subtraction():
    from ssm.recapitalization import reconcile_capital_context
    c=context('The Company redeemed all outstanding Series A Preferred Stock. The Company issued 5 million new Series A Preferred Stock.')
    d=Dilution(common_shares=10e6,preferred_shares_equiv=5e6,confidence='low')
    reconcile_capital_context(d,c,'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.','2026-10-01','2026-06-30')
    assert d.preferred_shares_equiv == 5e6


def test_capital_date_is_bound_to_capital_action_not_an_earlier_agreement():
    c=context('On June 1, 2026, the Company signed an agreement. On October 1, 2026, the Company issued 5 million shares of common stock.')
    assert c['transaction_date'] == '2026-10-01'


def test_completed_issuance_and_future_use_in_same_sentence_are_separate():
    c=context('The Company issued 2 million shares of common stock and will use the proceeds to repay debt.')
    assert c['actual_common_issued'] == 2e6
    assert c['confirmed_claim_reduction_usd'] == 0


def test_past_completed_at_closing_is_not_a_future_condition():
    c=context('Immediately before the transaction, 10 million shares of common stock were outstanding. On October 1, 2026, the Company issued 5 million shares of common stock at closing.')
    assert c['actual_common_issued'] == 5e6 and c['issuance_increase_pct'] == 50
    paid=context('On October 1, 2026, the Company repaid $70 million of debt at closing.')
    assert paid['confirmed_claim_reduction_usd'] == 70e6


def test_repeated_claim_with_different_whole_wording_is_not_double_counted():
    c=context('The Company redeemed $70 million of Series D Preferred Stock. The Company redeemed $70 million of all outstanding Series D Preferred Stock.')
    assert c['confirmed_claim_reduction_usd'] == 70e6


def test_unknown_capital_date_keeps_common_and_instrument_counts_unresolved():
    from ssm.recapitalization import reconcile_capital_context
    c=context('Immediately before the transaction, 10 million shares of common stock were outstanding. The Company issued 5 million shares of common stock.')
    d=Dilution(common_shares=10e6,confidence='medium')
    reconcile_capital_context(d,c,'',None,'2026-06-30')
    assert d.common_shares == 10e6 and d.fd_ratio is None


def test_separate_preferred_reissuance_context_blocks_old_series_removal():
    from ssm.recapitalization import reconcile_capital_context
    retired=context('On October 1, 2026, the Company redeemed all outstanding Series A Preferred Stock.')
    replacement=context('The Company issued 5 million new Series A Preferred Stock.')
    assert replacement['reconciliation_required']
    d=Dilution(common_shares=10e6,preferred_shares_equiv=5e6,confidence='low')
    reconcile_capital_context(d,retired,'Series A Preferred Stock outstanding was convertible into 5 million shares of common stock.','2026-10-01','2026-06-30',replacement['reissued_instrument_identities'])
    assert d.preferred_shares_equiv == 5e6


def test_unselected_capital_history_is_visible_with_source(tmp_path):
    cap=context('The Company issued 2 million shares of common stock. The proceeds will fund working capital.')
    c=Candidate('TEST',event_type='OTHER',event_terms={'capital_context_history':[{'filed':'2026-10-01','sources':['https://www.sec.gov/example'],'context':cap}]})
    write_outputs([c],json.load(open('config/default.json')),tmp_path)
    text=(tmp_path/'latest.md').read_text()
    assert '2,000,000' in text and 'WORKING_CAPITAL' in text and 'https://www.sec.gov/example' in text
