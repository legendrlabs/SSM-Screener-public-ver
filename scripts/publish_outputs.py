"""Publish a complete scan snapshot onto current main without rebasing CSVs."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(['git', '-C', str(repo), *args], text=True,
                          capture_output=True, check=check)


def publish_outputs(repo: Path, source_commit: str, attempts: int = 3) -> str:
    repo = Path(repo).resolve()
    required = ['quality.json', 'candidates.csv', 'dilution_check.csv', 'event_ledger.csv', 'latest.md']
    missing = [name for name in required if not (repo / 'output' / name).is_file()]
    if missing:
        raise ValueError(f'Incomplete scan snapshot: {missing}')
    snapshot = {name: (repo / 'output' / name).read_bytes() for name in required}
    quality = json.loads(snapshot['quality.json'])
    quality['source_commit'] = source_commit
    quality['workflow_run_id'] = os.getenv('GITHUB_RUN_ID', '')
    quality['generated_at'] = datetime.now(timezone.utc).isoformat()
    snapshot['quality.json'] = (json.dumps(quality, indent=2) + '\n').encode()

    for attempt in range(attempts):
        _git(repo, 'fetch', 'origin', 'main')
        latest = _git(repo, 'rev-parse', 'refs/remotes/origin/main').stdout.strip()
        changed = _git(repo, 'diff', '--quiet', source_commit, latest, '--', '.',
                       ':(exclude)output', ':(exclude).scan-trigger', check=False)
        if changed.returncode == 1:
            return 'skipped_stale_source'
        changed.check_returncode()

        with tempfile.TemporaryDirectory(prefix='ssm-publish-') as tmp:
            worktree = Path(tmp) / 'tree'
            _git(repo, 'worktree', 'add', '--detach', str(worktree), latest)
            try:
                old_quality = worktree / 'output/quality.json'
                if old_quality.exists():
                    previous = json.loads(old_quality.read_text())
                    old_run = str(previous.get('workflow_run_id', ''))
                    new_run = quality['workflow_run_id']
                    if old_run.isdigit() and new_run.isdigit() and int(old_run) > int(new_run):
                        return 'skipped_newer_run'
                for name, content in snapshot.items():
                    target = worktree / 'output' / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                _git(worktree, 'add', '-f', 'output/')
                if _git(worktree, 'diff', '--cached', '--quiet', check=False).returncode == 0:
                    return 'unchanged'
                _git(worktree, 'commit', '-m', 'chore: update SSM screening outputs')
                pushed = _git(worktree, 'push', 'origin', 'HEAD:main', check=False)
                if pushed.returncode == 0:
                    return 'published'
                if 'non-fast-forward' not in pushed.stderr and 'fetch first' not in pushed.stderr:
                    pushed.check_returncode()
            finally:
                _git(repo, 'worktree', 'remove', '--force', str(worktree))
    raise RuntimeError(f'Could not publish scan snapshot after {attempts} concurrent push attempts.')


if __name__ == '__main__':
    repo = Path.cwd()
    source = os.getenv('GITHUB_SHA') or _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    print(publish_outputs(repo, source))
