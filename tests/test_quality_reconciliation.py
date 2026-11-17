"""Real-source completion and repeated financing evidence; no production ticker exceptions."""
import json
from pathlib import Path

import pytest

from ssm import pipeline
from ssm.financial_recapitalization import financial_capital_contexts, _deduplicate_capital_records
from ssm.ma_review import completed_target_common_conversion
from ssm.models import Candidate, Dilution
from ssm.report import write_outputs
from ssm.validation_audit import summarize_invariants

FIXTURE = Path(__file__).parent / 'fixtures/quality'
# SEC 0001140361-26-044354 (issuer 8-K) and 0001140361-26-044347 (tender amendment), 2026-11-17.
# Conversion paragraphs: SEC 0001213900-26-120875 (10-Q), repeated note/MD&A evidence.
BODY = (FIXTURE / 'pcrx_20261117_8k.htm').read_text()
TENDER = (FIXTURE / 'pcrx_20261117_tender.htm').read_text()
CFG = json.loads(Path('config/default.json').read_text())
META = {'ticker':'PCRX','name':'Pacira BioSciences, Inc.','cik':'1396814','exchange':'Nasdaq'}

class CompletionSec:
    last_discovery_mode = 'atom'
    def exchange_tickers(self):return [META]
    def recent_filings(self, *args):
        return [{'cik':'1792044','form':'SC TO-T/A','filed':'2026-11-17',
                 'accession':'0001140361-26-044347','filename':'tender'}]
    def enrich_filing(self, cik, raw):return raw
    def submissions(self, cik):
        return {'filings':{'recent':{'form':['8-K'],'filingDate':['2026-11-17'],
                'accessionNumber':['0001140361-26-044354'],'primaryDocument':['issuer.htm'],
                'items':['1.01,2.01,3.01,3.03,5.01']}}}
    def submission_text(self, filename):return TENDER if filename=='tender' else BODY
    def filing_documents(self,*args):return []


def test_completed_target_overrides_discovery_even_without_microcap_issuer_row(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline,'SecClient',CompletionSec)
    monkeypatch.setattr(pipeline,'market_snapshots',lambda tickers:{})
    rows, cfg = pipeline.scan(7,'config/default.json',str(tmp_path/'none'),str(tmp_path/'none'))
    assert len(rows)==1
    c=rows[0]
    assert c.ticker=='PCRX'
    assert c.event_status in {'COMPLETED','TERMINAL'}
    assert c.gate_status==c.bucket=='EXCLUDED'
    assert c.latest_event_accession=='0001140361-26-044354'
    assert c.price is None and c.event_terms['target_common_conversion_verified'] is True
    assert any('044354' in url for url in c.event_sources)


@pytest.mark.parametrize('body',[
    'The Company expects to complete the merger. Its common stock will be converted into the right to receive cash.',
    'The Company completed an asset acquisition. Shares of common stock of the target were converted into the right to receive cash.',
    'The Company completed the merger. Notes were converted into the right to receive cash.',
])
def test_planned_asset_buyer_and_note_conversion_do_not_prove_target_common_exit(body):
    assert not completed_target_common_conversion(body)


def test_financial_note_and_mda_repetition_create_one_record_per_event():
    text=(FIXTURE/'cyab_conversion_repeat.txt').read_text()
    record={'form':'10-Q','filed':'2026-11-16','report_date':'2026-09-30','accession':'q','filename':'q'}
    rows=financial_capital_contexts(text,record)
    ids=[r['capital_event_id'] for r in rows]
    assert len(ids)==len(set(ids))
    assert any(len(r.get('evidence_variants',[]))>=2 for r in rows)
    c=Candidate(ticker='REPEAT',gate_status='DATA_HOLD',dilution=Dilution(common_shares=38399374))
    c.event_terms['financial_capital_context_history']=rows
    assert summarize_invariants([c])['invariants']['duplicate_sources_not_summed']['violations']==0
    assert c.dilution.common_shares==38399374
    assert all(r['context']['read_only'] for r in rows)


def test_duplicate_conflict_keeps_reconciliation_hold():
    def row(extent):
        return {'capital_event_id':'same','sources':['sec'], 'duplicate_event_accessions':[],
                'context':{'retirements':[{'evidence':'e','whole_instrument':extent}],
                           'reconciliation_required':False,'classification':'HISTORICAL_INCLUDED'}}
    rows=_deduplicate_capital_records([row(True),row(False)])
    assert len(rows)==1
    assert rows[0]['context']['reconciliation_required'] is True


def test_default_full_discovery_has_no_numeric_cap(tmp_path, monkeypatch):
    class ManySec:
        last_discovery_mode='atom'
        def exchange_tickers(self):return []
        def recent_filings(self,*args):
            return [{'form':'SCHEDULE 13D/A','cik':str(100000+i),'filed':'2026-11-17',
                     'accession':str(i),'filename':str(i)} for i in range(205)]
        def enrich_filing(self,cik,raw):return raw
    monkeypatch.setattr(pipeline,'SecClient',ManySec)
    monkeypatch.setattr(pipeline,'discover',lambda *args:None)
    _,cfg=pipeline.scan(7,'config/default.json',str(tmp_path/'none'),str(tmp_path/'none'))
    assert cfg['_ma_ownership_reads']==205
    assert cfg['_ma_ownership_budget_exceeded_count']==0


def test_unresolved_tender_has_source_and_is_not_checkpointed(tmp_path,monkeypatch):
    monkeypatch.setattr(pipeline,'SecClient',CompletionSec)
    monkeypatch.setattr(pipeline,'discover',lambda *args:None)
    _,cfg=pipeline.scan(7,'config/default.json',str(tmp_path/'none'),str(tmp_path/'none'))
    assert cfg['_ma_unresolved_filings'][0]['accession']=='0001140361-26-044347'
    assert cfg['_ma_unresolved_filings'][0]['reason']=='subject_or_transaction_unresolved'
    assert cfg['_seen_filings']['entries']=={}


def test_partial_discovery_blocks_safe_even_if_one_candidate_passes(tmp_path):
    c=Candidate(ticker='PASSING',security_type='COMMON_EQUITY',gate_status='PASS',bucket='A_RESEARCH_NOW',
                financial_review_complete=True,event_review_complete=True)
    write_outputs([c],{**CFG,'_ma_discovery_partial':True},tmp_path)
    q=json.loads((tmp_path/'quality.json').read_text())
    assert q['pass_count']==1 and q['SAFE_TO_ACT'] is False
    assert q['quality_status']=='REVIEW_REQUIRED'
    assert '**SAFE_TO_ACT: FALSE**' in (tmp_path/'latest.md').read_text()


def test_old_closing_cannot_replace_a_newer_discovery():
    c=Candidate(ticker='PCRX',cik='1396814',latest_event_date='2026-11-18',
                gate_status='DATA_HOLD',bucket='DATA_HOLD')
    assert not pipeline._review_target_completion(CompletionSec(),c,CFG)
    assert c.gate_status=='DATA_HOLD'


def test_invariant_violation_blocks_safe_even_without_partial_coverage(tmp_path):
    c=Candidate(ticker='PASSING',security_type='COMMON_EQUITY',gate_status='PASS',bucket='A_RESEARCH_NOW',
                financial_review_complete=True,event_review_complete=True)
    record={'form':'10-Q','filed':'2026-11-16','report_date':'2026-09-30','accession':'q','filename':'q'}
    row=financial_capital_contexts('On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',record)[0]
    c.event_terms['financial_capital_context_history']=[row,row]
    write_outputs([c],CFG,tmp_path)
    q=json.loads((tmp_path/'quality.json').read_text())
    assert q['invariant_violation_count']==1 and q['SAFE_TO_ACT'] is False
