"""The installed skill must work from a task directory outside its source."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import ssm.cli
from ssm.pipeline import load_json, load_watchlist
from ssm.models import Candidate

ROOT = Path(__file__).resolve().parents[1]


def runner_main():
    path = ROOT / 'scripts/run_ssm.py'
    assert path.is_file(), 'The skill needs a runnable entry point'
    spec = importlib.util.spec_from_file_location('skill_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def local_scan(days, config_path, watchlist_path, overrides_path):
    # Read real local inputs; only the live SEC/market scan is replaced.
    cfg = load_json(config_path)
    load_json(overrides_path)
    tickers = load_watchlist(watchlist_path)
    rows = [Candidate(ticker=t, gate_status='DATA_HOLD') for t in tickers]
    return rows, cfg


def test_scan_from_unrelated_directory_uses_bundled_defaults(monkeypatch, tmp_path):
    main = runner_main()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ssm.cli, 'scan', local_scan)
    main(['scan', '--out', 'results'])
    q = json.loads((tmp_path / 'results/quality.json').read_text())
    assert q['candidate_count'] == 0 and q['SAFE_TO_ACT'] is False
    assert (tmp_path / 'results/event_ledger.csv').exists()
    assert (tmp_path / 'results/latest.md').exists()


def test_check_from_unrelated_directory_uses_requested_tickers(monkeypatch, tmp_path):
    main = runner_main()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ssm.cli, 'scan', local_scan)
    main(['check', 'TESTA', 'TESTB', '--out', 'results'])
    q = json.loads((tmp_path / 'results/quality.json').read_text())
    assert q['candidate_count'] == 2 and q['data_hold_count'] == 2
    assert q['SAFE_TO_ACT'] is False
    text = (tmp_path / 'results/candidates.csv').read_text()
    assert 'TESTA' in text and 'TESTB' in text


def test_explicit_user_config_overrides_bundled_default(monkeypatch, tmp_path):
    main = runner_main()
    monkeypatch.chdir(tmp_path)
    cfg = load_json(ROOT / 'config/default.json')
    cfg['_sec_discovery_mode'] = 'custom-user-config'
    (tmp_path / 'custom.json').write_text(json.dumps(cfg))
    monkeypatch.setattr(ssm.cli, 'scan', local_scan)
    main(['scan', '--config', 'custom.json', '--out', 'results'])
    q = json.loads((tmp_path / 'results/quality.json').read_text())
    assert q['sec_discovery_mode'] == 'custom-user-config'


def test_script_help_works_from_an_unrelated_directory_without_sec_identity(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_ssm.py'), '--help'],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert '{scan,check}' in result.stdout
