from pathlib import Path

import pytest

from ssm import updater


SOURCE_COMMIT = "c" * 40


def test_git_update_fetches_and_checks_out_manifest_commit_without_unpinned_pull(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "check_output", lambda *args, **kwargs: b"")
    monkeypatch.setattr(updater.subprocess, "check_call", lambda command, *args, **kwargs: calls.append(command))

    updater._update_git_checkout(tmp_path, SOURCE_COMMIT)

    flattened = [str(part) for command in calls for part in command]
    assert SOURCE_COMMIT in flattened
    assert "pull" not in flattened
    assert "reset" not in flattened
    assert any(command[:4] == ["git", "-C", str(tmp_path), "fetch"] for command in calls)
    assert any("--ff-only" in command and SOURCE_COMMIT in command for command in calls)


def test_git_update_with_local_changes_fails_without_force_reset(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        updater.subprocess,
        "check_output",
        lambda *args, **kwargs: b" M ssm/updater.py\n",
    )
    monkeypatch.setattr(updater.subprocess, "check_call", lambda command, *args, **kwargs: calls.append(command))

    with pytest.raises(RuntimeError, match="local"):
        updater._update_git_checkout(tmp_path, SOURCE_COMMIT)

    assert calls == []


def test_pip_update_uses_commit_pinned_archive_url(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "check_call", lambda command, *args, **kwargs: calls.append(command))
    archive_url = updater.immutable_archive_url(SOURCE_COMMIT)

    updater._update_pip_install(archive_url)

    assert len(calls) == 1
    command = calls[0]
    assert archive_url in command
    assert SOURCE_COMMIT in archive_url
    assert "/main" not in archive_url
    assert "refs/heads/main" not in archive_url
