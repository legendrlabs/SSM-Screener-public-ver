import sys

import pytest

from ssm import cli, updater


UPDATE_STATUS = {
    "current": "1.1.3",
    "latest": "1.1.4",
    "update_available": True,
}


def test_interactive_update_acceptance_runs_verified_update(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(updater, "version_status", lambda: UPDATE_STATUS)
    monkeypatch.setattr(
        updater,
        "perform_update",
        lambda dry_run=False: calls.append(dry_run) or {"updated": True, "latest": "1.1.4"},
    )

    updated = updater.maybe_update_notice(interactive=True, input_fn=lambda prompt: "y")

    assert updated is True
    assert calls == [False]
    stderr = capsys.readouterr().err
    assert "1.1.4" in stderr
    assert "1.1.3" in stderr


def test_interactive_update_decline_continues_without_update(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "version_status", lambda: UPDATE_STATUS)
    monkeypatch.setattr(updater, "perform_update", lambda dry_run=False: calls.append(dry_run))

    updated = updater.maybe_update_notice(interactive=True, input_fn=lambda prompt: "")

    assert updated is False
    assert calls == []


def test_noninteractive_update_notice_never_prompts_or_updates(monkeypatch, capsys):
    prompts = []
    updates = []
    monkeypatch.setattr(updater, "version_status", lambda: UPDATE_STATUS)
    monkeypatch.setattr(updater, "perform_update", lambda dry_run=False: updates.append(dry_run))

    updated = updater.maybe_update_notice(
        interactive=False,
        input_fn=lambda prompt: prompts.append(prompt) or "y",
    )

    assert updated is False
    assert prompts == []
    assert updates == []
    assert "ssm update" in capsys.readouterr().err


def test_cli_restarts_original_command_after_accepted_update(monkeypatch):
    restarted = []
    monkeypatch.setattr(cli, "maybe_update_notice", lambda: True)
    monkeypatch.setattr(cli, "_restart_current_command", lambda: restarted.append(tuple(sys.argv)))
    monkeypatch.setattr(sys, "argv", ["ssm", "check", "GPRO"])

    cli.main()

    assert restarted == [("ssm", "check", "GPRO")]
