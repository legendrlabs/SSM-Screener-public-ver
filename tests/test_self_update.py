import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ssm import cli


def test_version_command_reports_current_and_latest(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "version_status",
        lambda: {"current": "1.1.2", "latest": "1.1.3", "update_available": True},
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["ssm", "version"])

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"current": "1.1.2", "latest": "1.1.3", "update_available": True}


def test_bundle_update_preserves_user_state(tmp_path):
    assert importlib.util.find_spec("ssm.updater") is not None, "self-update module is missing"
    from ssm.updater import apply_bundle_update

    installed = tmp_path / "installed"
    incoming = tmp_path / "incoming"
    for root in (installed, incoming):
        (root / "ssm").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "output").mkdir()

    (installed / "ssm" / "engine.py").write_text("old-code", encoding="utf-8")
    (installed / "config" / "watchlist.csv").write_text("ticker\nKEEP\n", encoding="utf-8")
    (installed / "config" / "overrides.json").write_text('{"KEEP": 1}', encoding="utf-8")
    (installed / "output" / "latest.md").write_text("keep-output", encoding="utf-8")

    (incoming / "ssm" / "engine.py").write_text("new-code", encoding="utf-8")
    (incoming / "config" / "watchlist.csv").write_text("ticker\nREPLACE\n", encoding="utf-8")
    (incoming / "config" / "overrides.json").write_text('{"REPLACE": 1}', encoding="utf-8")
    (incoming / "output" / "latest.md").write_text("replace-output", encoding="utf-8")
    (incoming / "README.md").write_text("new-readme", encoding="utf-8")

    apply_bundle_update(installed, incoming)

    assert (installed / "ssm" / "engine.py").read_text(encoding="utf-8") == "new-code"
    assert (installed / "README.md").read_text(encoding="utf-8") == "new-readme"
    assert (installed / "config" / "watchlist.csv").read_text(encoding="utf-8") == "ticker\nKEEP\n"
    assert (installed / "config" / "overrides.json").read_text(encoding="utf-8") == '{"KEEP": 1}'
    assert (installed / "output" / "latest.md").read_text(encoding="utf-8") == "keep-output"


def test_bundle_update_rolls_back_overwritten_files_on_failure(tmp_path, monkeypatch):
    assert importlib.util.find_spec("ssm.updater") is not None, "self-update module is missing"
    from ssm import updater

    installed = tmp_path / "installed"
    incoming = tmp_path / "incoming"
    (installed / "ssm").mkdir(parents=True)
    (incoming / "ssm").mkdir(parents=True)
    (installed / "ssm" / "a.py").write_text("old-a", encoding="utf-8")
    (installed / "ssm" / "b.py").write_text("old-b", encoding="utf-8")
    (incoming / "ssm" / "a.py").write_text("new-a", encoding="utf-8")
    (incoming / "ssm" / "b.py").write_text("new-b", encoding="utf-8")

    original_copy = updater.shutil.copy2
    calls = {"count": 0}

    def flaky_copy(src, dst, *args, **kwargs):
        if str(src).startswith(str(incoming)):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("synthetic copy failure")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(updater.shutil, "copy2", flaky_copy)

    with pytest.raises(OSError, match="synthetic copy failure"):
        updater.apply_bundle_update(installed, incoming)

    assert (installed / "ssm" / "a.py").read_text(encoding="utf-8") == "old-a"
    assert (installed / "ssm" / "b.py").read_text(encoding="utf-8") == "old-b"
