"""Request work is bounded before networking, with opt-in runtime diagnostics."""
import json
from pathlib import Path

import pytest
import requests

from ssm import pipeline
from ssm.providers.sec import SecClient
from ssm.progress import progress
from test_ownership_proposal_discovery import BODY, FILING, Sec


def test_ownership_aliases_use_one_source_identity_and_one_review(tmp_path, monkeypatch):
    class Aliases(Sec):
        calls = 0
        def recent_filings(self, days, forms):
            return [FILING, {**FILING, 'form': 'SC 13D/A'}]
        def enrich_filing(self, cik, raw):
            self.calls += 1
            return raw
    sec = Aliases()
    monkeypatch.setattr(pipeline, 'SecClient', lambda: sec)
    monkeypatch.setattr(pipeline, 'market_snapshots', lambda tickers: {})
    rows, state = pipeline.scan(7, 'config/default.json', str(tmp_path / 'none'), str(tmp_path / 'none'))
    assert sec.calls == 1
    assert state['_ma_ownership_reads'] == 1
    assert len(rows) == 1 and rows[0].ticker == 'LUCK'
    assert rows[0].event_terms['proposed_price_per_share_usd'] == 4.35
    assert rows[0].gate_status == 'DATA_HOLD'


def test_exhausted_unlisted_reporter_budget_never_fetches_submissions(tmp_path, monkeypatch):
    class NoNetworking(Sec):
        def enrich_filing(self, cik, raw):
            pytest.fail('An exhausted third-party budget must be checked before networking')
    monkeypatch.setattr(pipeline, 'SecClient', NoNetworking)
    cfg = json.loads(Path('config/default.json').read_text())
    cfg['ma_discovery_max_ownership_reads'] = 0
    path = tmp_path / 'cfg.json'
    path.write_text(json.dumps(cfg))
    rows, state = pipeline.scan(7, str(path), str(tmp_path / 'none'), str(tmp_path / 'none'))
    assert rows == [] and state['_ma_discovery_partial'] is True
    assert state['_ma_ownership_budget_exceeded_count'] == 1
    assert not state['_seen_filings']['entries']


@pytest.mark.parametrize('status,expected_calls', [(404, 1), (400, 1), (403, 3), (429, 3), (503, 3)])
def test_retry_only_transient_http_statuses(monkeypatch, status, expected_calls):
    sec = SecClient(user_agent='Test test@example.com', pause=0, max_retries=3)
    calls = []
    def get(url, timeout):
        calls.append(url)
        r = requests.Response()
        r.status_code = status
        r.url = url
        return r
    monkeypatch.setattr(sec.s, 'get', get)
    monkeypatch.setattr('ssm.providers.sec.time.sleep', lambda delay: None)
    with pytest.raises(requests.HTTPError):
        sec._get('https://data.sec.gov/submissions/CIK0000000001.json')
    assert len(calls) == expected_calls


def test_progress_is_opt_in_and_writes_json_to_stderr(monkeypatch, capsys):
    monkeypatch.delenv('SSM_PROGRESS', raising=False)
    progress('silent')
    assert capsys.readouterr().err == ''
    monkeypatch.setenv('SSM_PROGRESS', '1')
    progress('candidate.start', ticker='EXAMPLE')
    captured = capsys.readouterr()
    assert captured.out == ''
    assert json.loads(captured.err)['ssm_progress'] == 'candidate.start'
