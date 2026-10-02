import importlib.util
import json
import subprocess
from pathlib import Path


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def setup_repos(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    worker = tmp_path / 'worker'
    subprocess.run(['git', 'clone', str(remote), str(worker)], check=True, capture_output=True)
    git(worker, 'config', 'user.name', 'test')
    git(worker, 'config', 'user.email', 'test@example.com')
    git(worker, 'checkout', '-b', 'main')
    (worker / 'output').mkdir()
    (worker / 'output/quality.json').write_text('{"SAFE_TO_ACT": false}')
    (worker / 'output/candidates.csv').write_text('ticker\nOLD\n')
    for name in ['dilution_check.csv', 'event_ledger.csv', 'latest.md']:
        (worker / 'output' / name).write_text('baseline\n')
    (worker / 'source.py').write_text('VERSION = 1\n')
    git(worker, 'add', '.')
    git(worker, 'commit', '-m', 'baseline')
    git(worker, 'push', '-u', 'origin', 'main')
    source = git(worker, 'rev-parse', 'HEAD')
    other = tmp_path / 'other'
    subprocess.run(['git', 'clone', '-b', 'main', str(remote), str(other)], check=True, capture_output=True)
    git(other, 'config', 'user.name', 'test')
    git(other, 'config', 'user.email', 'test@example.com')
    return worker, other, source


def publisher_module():
    path = Path('scripts/publish_outputs.py').resolve()
    spec = importlib.util.spec_from_file_location('publisher', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publisher():
    return publisher_module().publish_outputs


def test_generated_snapshot_survives_concurrent_output_commit(tmp_path):
    worker, other, source = setup_repos(tmp_path)
    (other / 'output/candidates.csv').write_text('ticker\nOTHER\n')
    git(other, 'add', '.')
    git(other, 'commit', '-m', 'another scan')
    git(other, 'push', 'origin', 'main')
    (worker / 'output/candidates.csv').write_text('ticker\nNEW\n')
    assert publisher()(worker, source) == 'published'
    git(other, 'pull', '--ff-only')
    assert (other / 'output/candidates.csv').read_text() == 'ticker\nNEW\n'
    assert json.loads((other / 'output/quality.json').read_text())['source_commit'] == source


def test_old_source_cannot_overwrite_new_source_results(tmp_path):
    worker, other, source = setup_repos(tmp_path)
    (other / 'source.py').write_text('VERSION = 2\n')
    (other / 'output/candidates.csv').write_text('ticker\nNEW_SOURCE\n')
    git(other, 'add', '.')
    git(other, 'commit', '-m', 'new code and scan')
    git(other, 'push', 'origin', 'main')
    (worker / 'output/candidates.csv').write_text('ticker\nSTALE\n')
    assert publisher()(worker, source) == 'skipped_stale_source'
    git(other, 'pull', '--ff-only')
    assert (other / 'output/candidates.csv').read_text() == 'ticker\nNEW_SOURCE\n'


def test_push_race_retries_complete_snapshot(tmp_path, monkeypatch):
    worker, other, source = setup_repos(tmp_path)
    (worker / 'output/candidates.csv').write_text('ticker\nNEW\n')
    (worker / 'output/latest.md').write_text('NEW report\n')
    module = publisher_module()
    real_git = module._git
    raced = False
    def racing_git(repo, *args, **kwargs):
        nonlocal raced
        if args[0] == 'push' and not raced:
            raced = True
            (other / 'output/candidates.csv').write_text('ticker\nRACE\n')
            git(other, 'add', '.')
            git(other, 'commit', '-m', 'concurrent output')
            git(other, 'push', 'origin', 'main')
        return real_git(repo, *args, **kwargs)
    monkeypatch.setattr(module, '_git', racing_git)
    assert module.publish_outputs(worker, source) == 'published'
    git(other, 'pull', '--ff-only')
    assert raced
    assert (other / 'output/candidates.csv').read_text() == 'ticker\nNEW\n'
    assert (other / 'output/latest.md').read_text() == 'NEW report\n'
    assert (worker / 'source.py').read_text() == 'VERSION = 1\n'


def test_newer_run_snapshot_is_not_overwritten(tmp_path, monkeypatch):
    worker, other, source = setup_repos(tmp_path)
    (other / 'output/quality.json').write_text('{"SAFE_TO_ACT":false,"workflow_run_id":"200"}')
    git(other, 'add', '.')
    git(other, 'commit', '-m', 'newer run')
    git(other, 'push', 'origin', 'main')
    monkeypatch.setenv('GITHUB_RUN_ID', '100')
    assert publisher()(worker, source) == 'skipped_newer_run'


def test_incomplete_snapshot_is_not_published(tmp_path):
    import pytest
    worker, other, source = setup_repos(tmp_path)
    (worker / 'output/latest.md').unlink()
    with pytest.raises(ValueError, match='Incomplete scan snapshot'):
        publisher()(worker, source)
    assert git(other, 'rev-parse', 'HEAD') == source
