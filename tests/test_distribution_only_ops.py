"""Public skill distribution with isolated operator-only SEC scan workflows."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_upstream_has_release_tests_and_operator_scan_only():
    workflow_dir = ROOT / ".github/workflows"
    workflows = {p.name for p in workflow_dir.glob("*.yml")}
    assert workflows == {"tests.yml", "release.yml", "sec-scan.yml"}
    assert not (ROOT / ".scan-trigger").exists()
    for filename in ("tests.yml", "release.yml"):
        content = (workflow_dir / filename).read_text(encoding="utf-8")
        assert "ssm scan" not in content
        assert "SEC_USER_AGENT" not in content
        assert "publish_outputs.py" not in content
        assert "cron:" not in content
    scan = (workflow_dir / "sec-scan.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in scan
    assert "schedule:" in scan
    assert "secrets.SEC_USER_AGENT" in scan
    assert "permissions:\n  contents: read" in scan
    assert "persist-credentials: false" in scan
    assert "scripts/run_ssm.py scan" in scan
    assert "upload-artifact@v4" in scan
    assert "git push" not in scan
    assert "publish_outputs.py" not in scan


def test_user_identity_stays_per_installed_skill():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Distribution + maintainer operator scans" in skill
    assert "Each installed recipient still runs their own skill" in skill
    assert "Before live SEC requests, check `SEC_USER_AGENT`" in skill
    assert "If absent, ask the user once" in skill
    assert "Never invent an email" in skill
    assert "empty tracked `output/`" in skill


def test_operator_secret_and_reports_are_not_committed_to_main():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/operations/user-sec-setup.md").read_text(encoding="utf-8")
    assert "배포 및 운영자 SEC 스캔" in readme
    assert "SEC_USER_AGENT" in guide
    assert "사용자 자신의" in guide or "본인" in guide
    assert "Settings > Secrets and variables > Actions" in guide
    assert "GitHub Actions artifact" in readme
    assert "코드·커밋·로그에 표시하지 않습니다" in readme
    assert not (ROOT / "docs/operations/public-scan.md").exists()


def test_central_snapshot_publisher_is_not_packaged():
    assert not (ROOT / "scripts/publish_outputs.py").exists()
    assert not (ROOT / "tests/test_publish_outputs.py").exists()
    # Only a placeholder is committed; generated reports remain per-run artifacts.
    assert (ROOT / "output/.gitkeep").exists()
    assert not (ROOT / "output/quality.json").exists()
    assert not (ROOT / "output/latest.md").exists()
    assert (ROOT / "scripts/run_ssm.py").is_file()
    assert (ROOT / "ssm/providers/sec.py").is_file()
    assert (ROOT / ".github/workflows/release.yml").exists()


def test_documented_release_version_matches_package_and_skill():
    from ssm import __version__
    from ssm.release_policy import project_version

    version = project_version(ROOT)
    assert __version__ == version
    assert (ROOT / "README.md").read_text(encoding="utf-8").startswith(
        f"# Special Situation Microcap Screener (SSM) v{version}"
    )
    updating = (ROOT / "UPDATING.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert f"## 최신 배포 v{version}" in updating
    assert f"v{version} and later" in skill
    assert (ROOT / f"docs/releases/v{version}.md").is_file()
