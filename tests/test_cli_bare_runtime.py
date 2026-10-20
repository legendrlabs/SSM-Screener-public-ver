"""Bare Python and release-check failure regressions for mounted skill bundles."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ssm import updater


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_ssm.py"


def test_help_works_in_python_without_site_packages(tmp_path):
    p = subprocess.run(
        [sys.executable, "-S", str(RUNNER), "--help"],
        cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    assert p.returncode == 0, p.stderr
    for cmd in ("scan", "check", "version", "update"):
        assert cmd in p.stdout


def test_version_offline_works_in_python_without_site_packages(tmp_path):
    p = subprocess.run(
        [sys.executable, "-S", str(RUNNER), "version", "--offline"],
        cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    assert p.returncode == 0, p.stderr
    result = json.loads(p.stdout)
    assert result["current"] == updater.current_version()
    assert result["latest"] is None
    assert result["update_available"] is None
    assert result["check_error"] == "OFFLINE_CHECK_SKIPPED"


def test_importing_cli_and_updater_does_not_import_scanning_deps(tmp_path):
    code = (
        "import sys; import ssm.cli, ssm.updater; "
        "assert 'ssm.pipeline' not in sys.modules; "
        "assert 'ssm.providers.sec' not in sys.modules; "
        "assert 'requests' not in sys.modules; "
        "assert 'pandas' not in sys.modules; "
        "assert 'yfinance' not in sys.modules"
    )
    p = subprocess.run(
        [sys.executable, "-S", "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=15,
    )
    assert p.returncode == 0, p.stderr


def test_network_timeout_returns_unknown_not_no_update(monkeypatch):
    monkeypatch.setattr(updater, "current_version", lambda: "1.1.6")

    def timeout():
        raise TimeoutError("simulated network timeout")

    monkeypatch.setattr(updater, "fetch_release_manifest", timeout)
    state = updater.version_status()
    assert state["current"] == "1.1.6"
    assert state["latest"] is None
    assert state["update_available"] is None
    assert "TimeoutError" in state["check_error"]


def test_fetch_release_manifest_uses_bounded_standard_library_retries(monkeypatch):
    url = f"https://github.com/{updater.REPO}/releases/download/v1.1.7/release.json"
    release = {"tag_name": "v1.1.7", "assets": [
        {"name": "release.json", "browser_download_url": url}
    ]}
    manifest = {
        "schema_version": 1, "version": "1.1.7", "tag": "v1.1.7",
        "source_commit": "a" * 40, "managed_files": {},
    }
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, limit):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise TimeoutError("first attempt")
        return FakeResponse(release if request.full_url == updater.LATEST_RELEASE_API else manifest)

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    monkeypatch.setattr(updater.time, "sleep", lambda delay: None)
    assert updater.fetch_release_manifest()["version"] == "1.1.7"
    assert all(timeout >= 8 for _, timeout in calls)
    assert len(calls) == 3  # release retries once; asset is fetched once


@pytest.mark.parametrize("url", [
    "https://attacker.example/release.json",
    "http://github.com/legendrlabs/SSM-Screener-public-ver/releases/download/v1/release.json",
    "https://github.com/another/repo/releases/download/v1/release.json",
])
def test_release_metadata_does_not_follow_arbitrary_asset_url(url):
    with pytest.raises(ValueError, match="official GitHub release"):
        updater._release_asset_url(url)


def test_bootstrap_refuses_to_write_inside_skill_source(monkeypatch):
    import scripts.prepare_runtime as bootstrap
    with pytest.raises(ValueError, match="outside"):
        bootstrap.prepare(ROOT / ".ssm-venv")
