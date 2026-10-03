import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ssm import cli


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def _write_project(root: Path, version: str, engine_text: str = "engine\n") -> Path:
    (root / "ssm").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"fixture\"\nversion = \"%s\"\n" % version,
        encoding="utf-8",
    )
    (root / "ssm" / "engine.py").write_text(engine_text, encoding="utf-8")
    return root


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest(version: str = "2.0.0", source_commit: str = COMMIT_A, managed_files=None) -> dict:
    if managed_files is None:
        managed_files = {"ssm/engine.py": _digest("engine\n")}
    return {
        "schema_version": 1,
        "version": version,
        "tag": f"v{version}",
        "source_commit": source_commit,
        "managed_files": managed_files,
    }


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


def test_manifest_version_mismatch_rejected_before_apply(tmp_path):
    from ssm.updater import validate_archive

    incoming = _write_project(tmp_path / "incoming", "2.0.1")
    installed = _write_project(tmp_path / "installed", "1.0.0", "installed\n")
    before = (installed / "ssm" / "engine.py").read_bytes()

    with pytest.raises(ValueError, match="version"):
        validate_archive(incoming, _manifest(version="2.0.0"), COMMIT_A)

    assert (installed / "ssm" / "engine.py").read_bytes() == before


def test_archive_source_commit_mismatch_rejected_before_apply(tmp_path):
    from ssm.updater import validate_archive

    incoming = _write_project(tmp_path / "incoming", "2.0.0")
    installed = _write_project(tmp_path / "installed", "1.0.0", "installed\n")
    before = (installed / "ssm" / "engine.py").read_bytes()

    with pytest.raises(ValueError, match="source_commit"):
        validate_archive(incoming, _manifest(), COMMIT_B)

    assert (installed / "ssm" / "engine.py").read_bytes() == before


def test_managed_file_hash_mismatch_rejected_before_apply(tmp_path):
    from ssm.updater import validate_archive

    incoming = _write_project(tmp_path / "incoming", "2.0.0", "tampered\n")
    installed = _write_project(tmp_path / "installed", "1.0.0", "installed\n")
    before = (installed / "ssm" / "engine.py").read_bytes()

    with pytest.raises(ValueError, match="hash"):
        validate_archive(incoming, _manifest(), COMMIT_A)

    assert (installed / "ssm" / "engine.py").read_bytes() == before


def test_manifest_with_preserved_path_rejected():
    from ssm.updater import validate_manifest

    manifest = _manifest(managed_files={"config/watchlist.csv": _digest("ticker\n")})
    with pytest.raises(ValueError, match="preserved"):
        validate_manifest(manifest)


def test_invalid_manifest_schema_fails_closed():
    from ssm.updater import validate_manifest

    manifest = _manifest()
    manifest["schema_version"] = 999
    with pytest.raises(ValueError, match="schema"):
        validate_manifest(manifest)


def test_immutable_archive_url_uses_manifest_commit_not_main():
    from ssm.updater import immutable_archive_url

    url = immutable_archive_url(COMMIT_A)
    assert COMMIT_A in url
    assert "/main" not in url
    assert "refs/heads/main" not in url
