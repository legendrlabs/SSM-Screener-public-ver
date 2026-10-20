"""Prepare an isolated Python environment for an installed SSM skill bundle.

This tool never edits the skill root. It performs no SEC requests, scans,
version updates or user-configuration changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ("requests", "pandas", "yfinance")


def python_in_venv(venv: Path) -> Path:
    return (venv / "Scripts" / "python.exe") if sys.platform == "win32" else (venv / "bin" / "python")


def prepare(venv: Path) -> dict:
    target = Path(venv).expanduser().resolve()
    installed = ROOT.resolve()
    if target == installed or installed in target.parents:
        raise ValueError("virtual environment must be outside the installed skill root")
    target.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run([sys.executable, "-m", "venv", str(target)], check=True)
    py = python_in_venv(target)
    subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input", str(installed)], check=True)
    subprocess.run([str(py), "-m", "pip", "check"], check=True)
    subprocess.run([str(py), "-c", "import requests, pandas, yfinance"], check=True)
    return {
        "status": "DEPENDENCIES_READY",
        "python": str(py),
        "skill_dir": str(installed),
        "dependencies": list(DEPENDENCIES),
        "installed_skill_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create/verify an isolated SSM runtime outside the installed skill."
    )
    parser.add_argument("--venv", type=Path, required=True,
                        help="writable path outside the mounted skill (for example TASK_DIR/.ssm-venv)")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.venv)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(json.dumps({
            "status": "DEPENDENCY_INSTALL_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "installed_skill_modified": False,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
