import csv
import json
from ssm.models import Candidate, Dilution
from ssm.report import write_outputs


def test_report_retains_held_cash_cvr_and_liquidation_and_excludes_capital(tmp_path):
    merger=Candidate(ticker='LFCR',event_type='MERGER_CASH_CVR',event_status='SIGNED',
                     event_terms={'cash_per_share_usd':6.28,'cvr_conditional':True,'cvr_transferable':False,
                                  'illustrative_total_per_share_usd':9.67},event_sources=['https://www.sec.gov/example'])
    liquidation=Candidate(ticker='ELME',event_type='LIQUIDATION_DISTRIBUTION',event_status='LIQUIDATING',
                          gate_status='WATCH',bucket='B_WATCH',event_terms={'distribution_per_share_usd':1.74,
                          'distribution_status':'DECLARED','payment_date':'2026-10-22','ex_dividend_date':'2026-10-23','due_bills':True})
    debt=Candidate(ticker='GREEL',security_type='DEBT',gate_status='EXCLUDED',bucket='EXCLUDED',
                   dilution=Dilution(common_shares=100,confidence='medium'),price=10)
    write_outputs([merger,liquidation,debt],{'max_candidates':10},tmp_path)
    md=(tmp_path/'latest.md').read_text()
    assert 'LFCR' in md and 'ELME' in md and 'not a fixed guaranteed payout' in md
    assert '2026-10-22' in md and 'DECLARED' in md and 'record date alone' in md
    rows=list(csv.DictReader((tmp_path/'candidates.csv').open(encoding='utf-8-sig')))
    assert json.loads(rows[0]['event_terms'])['cash_per_share_usd']==6.28
    assert rows[2]['basic_market_cap']==rows[2]['fd_ratio']==rows[2]['dilution_common_shares']==''
    checks=list(csv.DictReader((tmp_path/'dilution_check.csv').open(encoding='utf-8-sig')))
    assert checks[2]['common_shares']==checks[2]['fd_ratio']==''
    quality=json.loads((tmp_path/'quality.json').read_text())
    assert quality['excluded_count']==1 and quality['active_common_count']==2
    assert quality['SAFE_TO_ACT'] is False


def test_pending_stock_warrants_and_conditional_buyback_are_in_human_report(tmp_path):
    stock=Candidate(ticker='ESOA',event_type='ASSET_SALE_ACQUISITION',event_status='SIGNED',
                    dilution=Dilution(common_shares=100,pending_stock_consideration_usd=3_475_000))
    debt=Candidate(ticker='VIP',event_type='DEBT_RESTRUCTURING',event_status='SIGNED',event_terms={
                   'new_warrant_shares':1_000_000,'new_warrant_exercise_price_usd':1.87})
    sale=Candidate(ticker='INGN',event_type='ASSET_SALE_ACQUISITION',event_status='SIGNED',event_terms={
                   'sale_price_estimate_usd':24_800_000,'repurchase_total_usd':45_000_000,
                   'repurchase_increment_usd':15_000_000,'repurchase_conditional':True})
    write_outputs([stock,debt,sale],{'max_candidates':10},tmp_path)
    md=(tmp_path/'latest.md').read_text()
    assert 'ESOA' in md and 'incremental share count unresolved' in md
    assert 'VIP' in md and '1,000,000 shares at $1.87' in md
    assert 'INGN' in md and '$24.8M' in md and '$45.0M total' in md and 'conditional on closing' in md
