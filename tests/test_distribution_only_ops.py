"""Distribution-only repository: every recipient owns SEC contact and scan outputs."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upstream_has_only_release_and_ci_workflows():
    workflow_dir = ROOT / ".github/workflows"
    workflows = {p.name for p in workflow_dir.glob("*.yml")}
    assert workflows == {"tests.yml", "release.yml"}
    assert not (ROOT / ".scan-trigger").exists()
    # No SEC/market scans or output publishing from the upstream Actions account.
    for workflow in workflow_dir.glob("*.yml"):
        content = workflow.read_text(encoding="utf-8")
        assert "ssm scan" not in content
        assert "SEC_USER_AGENT" not in content
        assert "publish_outputs.py" not in content
        assert "cron:" not in content


def test_user_identity_is_configured_per_installed_skill():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Distribution-only policy" in skill
    assert "Every recipient runs their own installed engine" in skill
    assert "Before live SEC requests, check `SEC_USER_AGENT`" in skill
    assert "If absent, ask the user once" in skill
    assert "Never invent an email" in skill
    assert "Never read the canonical repository's `output/`" in skill


def test_personal_setup_has_no_central_secret_or_results():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/operations/user-sec-setup.md").read_text(encoding="utf-8")
    assert "배포 전용 저장소" in readme
    assert "SEC_USER_AGENT" in guide
    assert "사용자 자신의" in guide or "본인" in guide
    assert "Settings > Secrets and variables > Actions" in guide
    assert "퍼블릭 정기 스캔 및 채팅 보고" not in readme
    assert not (ROOT / "docs/operations/public-scan.md").exists()


def test_central_snapshot_publisher_is_not_packaged():
    assert not (ROOT / "scripts/publish_outputs.py").exists()
    assert not (ROOT / "tests/test_publish_outputs.py").exists()
    # Local users still have a task output directory; it is not the central report.
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
