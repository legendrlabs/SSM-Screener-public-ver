"""Third-party 13D subject identity, proposal safety, and pipeline regression."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from ssm import pipeline
from ssm.gates import evaluate_gates
from ssm.ma_discovery import discover, name_index
from ssm.ma_review import offer_spread_gate
from ssm.models import Candidate
from ssm.report import write_outputs

# SEC source, fetched 2026-11-17:
# https://www.sec.gov/Archives/edgar/data/1882143/000110465926128837/primary_doc.xml
BODY = (Path(__file__).parent / 'fixtures/ownership/luck_20261117_13da.xml').read_text()
TARGET = {'ticker': 'LUCK', 'name': 'Lucky Strike Entertainment Corp', 'cik': '1840572', 'exchange': 'NYSE'}
INDEX = name_index({'LUCK': TARGET})
FILING = {'cik': '1882143', 'form': 'SCHEDULE 13D/A', 'filed': '2026-11-17',
          'accession': '0001104659-26-128837',
          'filename': 'edgar/data/1882143/000110465926128837/primary_doc.xml'}


class Sec:
    last_discovery_mode = 'atom'
    def exchange_tickers(self):
        return [TARGET]
    def recent_filings(self, days, forms):
        assert 'SCHEDULE 13D/A' in forms
        return [FILING]
    def enrich_filing(self, cik, raw):
        assert cik == '1882143'
        return raw
    def submission_text(self, filename):
        return BODY
    def filing_documents(self, *args):
        return []


@pytest.mark.parametrize('form', ['SC 13D', 'SC 13D/A', 'SCHEDULE 13D', 'SCHEDULE 13D/A'])
def test_actual_luck_xml_declares_target_not_reporting_person(form):
    c = discover(Sec(), {**FILING, 'form': form}, INDEX)
    assert c.ticker == 'LUCK' and c.cik == '1840572'
    assert c.event_terms['filing_cik'] == '1882143'
    assert c.event_terms['proposed_price_per_share_usd'] == 4.35
    assert c.event_terms.get('cash_per_share_status') != 'FIXED'
    assert c.event_status == 'PRELIMINARY'
    assert c.gate_status == c.bucket == 'DATA_HOLD'
    assert evaluate_gates(c, {})[0] == 'DATA_HOLD'
    # Even an apparently attractive quote cannot turn a proposal into arbitrage.
    assert offer_spread_gate(c.event_terms, 3.0, event_type=c.event_type)[0] == 'DATA_HOLD'
    assert c.event_sources[0].endswith(FILING['filename'])
    assert c.dilution.common_shares == 0 and c.dilution.confidence == 'low'


def test_legacy_cover_and_unrelated_or_conflicting_identities():
    text = ('ULTRALIFE CORPORATION\n(Name of Issuer)\nA non-binding proposal to acquire '
            'all outstanding shares for $16.00 per share in cash.')
    meta = {**TARGET, 'name': 'Ultralife Corp', 'ticker': 'ULBI', 'cik': '875657'}
    idx = name_index({'ULBI': meta})
    c = discover(Sec(), FILING, idx, text=text)
    assert c.ticker == 'ULBI' and c.event_terms['cash_per_share_status'] == 'PROPOSED_NONBINDING'
    assert discover(Sec(), FILING, INDEX, text=BODY.replace('0001840572', '0009999999')) is None
    assert discover(Sec(), FILING, INDEX, text=BODY.replace('Lucky Strike Entertainment Corporation', 'Unrelated Inc')) is None
    assert discover(Sec(), FILING, INDEX, text='Non-binding proposal to acquire Lucky Strike Entertainment Corporation.') is None
    assert discover(Sec(), FILING, INDEX, text='<issuerName>Lucky Strike Entertainment Corp</issuerName> Routine purchases of shares for investment.') is None
    ambiguous = name_index({'A': TARGET, 'B': {**TARGET, 'ticker': 'OTHER', 'cik': '42'}})
    assert discover(Sec(), FILING, ambiguous, text=BODY) is None


def test_proposal_exhibit_retains_primary_subject_and_source():
    class ExhibitSec(Sec):
        def filing_documents(self, *args):
            return [{'type': 'EX-99.1', 'url': 'https://www.sec.gov/proposal.htm'}]
        def submission_text(self, filename):
            return 'A non-binding proposal to acquire all outstanding shares for $7.00 per share in cash.'
    primary = '<issuerCIK>1840572</issuerCIK><issuerName>Lucky Strike Entertainment Corp</issuerName> See Exhibit 99.1.'
    c = discover(ExhibitSec(), FILING, INDEX, text=primary)
    assert c.ticker == 'LUCK' and c.event_terms['proposed_price_per_share_usd'] == 7
    assert len(c.event_sources) == 2 and c.event_status == 'PRELIMINARY'


def test_pipeline_unlisted_filer_and_old_checkpoint_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'SecClient', Sec)
    # An older routine issuer record must not hide a newer proposal.
    old = Candidate(ticker='LUCK', cik='1840572', event_type='MERGER_CASH',
                    latest_event_date='2026-11-16', event_review_complete=True,
                    gate_status='PASS', bucket='A_RESEARCH_NOW')
    # Discovery is independent of issuer-side build/price reads.
    monkeypatch.setattr(pipeline, 'market_snapshots', lambda ts: {})
    cfg = tmp_path / 'cfg.json'
    cfg.write_text(Path('config/default.json').read_text())
    now = datetime.now(timezone.utc)
    state = {'schema_version': 1, 'run_id': 'old',
             'entries': {pipeline._filing_key(FILING): now.date().isoformat()},
             'last_full_completed_at_utc': now.isoformat(), 'last_full_lookback_days': 7}
    checkpoint = tmp_path / 'seen.json'
    checkpoint.write_text(json.dumps(state))
    rows, details = pipeline.scan(7, str(cfg), str(tmp_path / 'empty.csv'), str(tmp_path / 'empty.json'), str(checkpoint))
    assert len(rows) == 1 and rows[0].ticker == 'LUCK'
    assert rows[0].gate_status == 'DATA_HOLD'
    assert details['_ma_ownership_reads'] == 1
    assert details['_seen_filings']['ownership_discovery_version'] == 1
    write_outputs(rows, details, tmp_path / 'out')
    quality = json.loads((tmp_path / 'out/quality.json').read_text())
    assert quality['SAFE_TO_ACT'] is False
    assert '$4.35 proposed per share (non-binding' in (tmp_path / 'out/latest.md').read_text()
    # Pre-upgrade checkpoints must replay ownership accessions once.
    old = {**details['_seen_filings'], 'run_id': 'old'}
    old.pop('ownership_discovery_version')
    old['last_full_completed_at_utc'] = datetime.now(timezone.utc).isoformat()
    old['last_full_lookback_days'] = 7
    old['entries'] = {pipeline._filing_key(FILING): datetime.now(timezone.utc).date().isoformat()}
    checkpoint = tmp_path / 'seen.json'
    checkpoint.write_text(json.dumps(old))
    upgraded, _ = pipeline.scan(7, str(cfg), str(tmp_path / 'empty.csv'), str(tmp_path / 'override.json'), incremental_state_path=str(checkpoint))
    assert len(upgraded) == 1 and upgraded[0].ticker == 'LUCK'
    saved = details['_seen_filings']
    saved['run_id'] = 'new'
    checkpoint.write_text(json.dumps(saved))
    replay, _ = pipeline.scan(7, str(cfg), str(tmp_path / 'empty.csv'), str(tmp_path / 'empty.json'), str(checkpoint))
    assert replay == []


def test_ownership_budget_is_visible_and_unread_accession_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'SecClient', Sec)
    cfg = json.loads(Path('config/default.json').read_text())
    cfg['ma_discovery_max_ownership_reads'] = 0
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(cfg))
    rows, state = pipeline.scan(7, str(path), str(tmp_path / 'empty'), str(tmp_path / 'empty'))
    assert rows == []
    assert state['_ma_discovery_partial'] is True
    assert state['_ma_ownership_budget_exceeded_count'] == 1
    assert pipeline._filing_key(FILING) not in state['_seen_filings']['entries']


def test_new_proposal_cannot_be_hidden_by_stale_issuer_merger(tmp_path, monkeypatch):
    class BothSec(Sec):
        def recent_filings(self, days, forms):
            return [FILING, {**FILING, 'cik': TARGET['cik'], 'form': '8-K',
                             'accession': 'old-event', 'filed': '2026-11-01', 'items': '1.01'}]
        def enrich_filing(self, cik, raw):
            return raw
    monkeypatch.setattr(pipeline, 'SecClient', BothSec)
    monkeypatch.setattr(pipeline, 'resolve_security', lambda sec, meta, filing: {**meta, 'security_type': 'COMMON_EQUITY'})
    monkeypatch.setattr(pipeline, 'market_snapshots', lambda tickers: {})
    monkeypatch.setattr(pipeline, 'build_candidate', lambda *args:
        Candidate(**TARGET, security_type='COMMON_EQUITY', event_type='MERGER_CASH',
                  event_review_complete=True, latest_event_date='2026-11-01',
                  gate_status='PASS', bucket='A_RESEARCH_NOW'))
    rows, _ = pipeline.scan(7, 'config/default.json', str(tmp_path / 'empty'), str(tmp_path / 'empty'))
    assert len(rows) == 1 and rows[0].ticker == 'LUCK'
    assert rows[0].event_status == 'PRELIMINARY'
    assert rows[0].gate_status == rows[0].bucket == 'DATA_HOLD'
