"""Guard the public operating workflow while v1.1.x releases remain immutable."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scan_schedule_and_explicit_trigger_are_restored():
    scan = (ROOT / ".github/workflows/daily-scan.yml").read_text()
    assert 'cron: "30 11 * * 1-5"' in scan  # 20:30 KST Mon-Fri
    assert 'cron: "30 22 * * 1-5"' in scan  # 07:30 KST Tue-Sat
    assert "workflow_dispatch:" in scan
    assert 'paths:' in scan and '".scan-trigger/**"' in scan
    assert "if: github.ref == 'refs/heads/main'" in scan


def test_scan_requires_explicit_sec_identity_and_writable_publication_token():
    scan = (ROOT / ".github/workflows/daily-scan.yml").read_text()
    assert "contents: write" in scan
    assert "secrets.SEC_USER_AGENT" in scan
    assert 'if [ -z "$SEC_USER_AGENT" ]; then' in scan
    assert "SSM_SEC_DISCOVERY_MODE: atom" in scan
    assert "ssm scan --days 7 --out output" in scan
    assert "upload-artifact@v4" in scan
    assert "python scripts/publish_outputs.py" in scan
    assert scan.index("ssm scan --days 7 --out output") < scan.index("upload-artifact@v4")
    assert scan.index("upload-artifact@v4") < scan.index("python scripts/publish_outputs.py")


def test_output_push_does_not_launch_full_ci_or_another_scan():
    tests = (ROOT / ".github/workflows/tests.yml").read_text()
    assert "paths-ignore:" in tests
    assert '"output/**"' in tests
    assert '".scan-trigger/**"' in tests
    scan = (ROOT / ".github/workflows/daily-scan.yml").read_text()
    assert "paths:" in scan
    assert '      - ".scan-trigger/**"' in scan
    assert "paths-ignore" not in scan


def test_main_public_publisher_requires_a_complete_snapshot():
    source = (ROOT / "scripts/publish_outputs.py").read_text()
    required = ("quality.json", "candidates.csv", "dilution_check.csv",
                "event_ledger.csv", "latest.md")
    for filename in required:
        assert filename in source
    assert "skipped_stale_source" in source
    assert "skipped_newer_run" in source
