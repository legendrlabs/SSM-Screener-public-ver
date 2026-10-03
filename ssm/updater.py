from __future__ import annotations

from io import BytesIO
from importlib import metadata
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

PACKAGE_NAME = "special-situation-microcap"
REPO = "legendrlabs/SSM-Screener-public-ver"
REMOTE_PYPROJECT = f"https://raw.githubusercontent.com/{REPO}/main/pyproject.toml"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
PRESERVE_EXACT = {Path("config/watchlist.csv"), Path("config/overrides.json")}
PRESERVE_PREFIXES = (Path("output"),)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    return tuple(int(p) for p in parts[:3])


def _version_from_pyproject(text: str) -> str:
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not match:
        raise ValueError("version not found in pyproject.toml")
    return match.group(1)


def current_version() -> str:
    local = _root() / "pyproject.toml"
    if local.exists():
        try:
            return _version_from_pyproject(local.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def latest_version(timeout: float = 2.0) -> str:
    response = requests.get(REMOTE_PYPROJECT, timeout=timeout)
    response.raise_for_status()
    return _version_from_pyproject(response.text)


def version_status() -> dict:
    current = current_version()
    try:
        latest = latest_version()
    except Exception as exc:
        return {
            "current": current,
            "latest": None,
            "update_available": False,
            "check_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "current": current,
        "latest": latest,
        "update_available": _version_tuple(latest) > _version_tuple(current),
    }


def maybe_update_notice() -> None:
    status = version_status()
    if status.get("update_available"):
        print(
            f"SSM {status['latest']} available (current {status['current']}). Run: ssm update",
            file=sys.stderr,
        )


def _preserved(relative: Path) -> bool:
    if relative in PRESERVE_EXACT:
        return True
    return any(relative == prefix or prefix in relative.parents for prefix in PRESERVE_PREFIXES)


def apply_bundle_update(installed_root: Path, incoming_root: Path) -> dict:
    installed_root = Path(installed_root)
    incoming_root = Path(incoming_root)
    overwritten: list[tuple[Path, Path]] = []
    created: list[Path] = []
    copied = 0

    with tempfile.TemporaryDirectory(prefix="ssm-update-backup-") as backup_dir:
        backup_root = Path(backup_dir)
        try:
            for src in sorted(p for p in incoming_root.rglob("*") if p.is_file()):
                relative = src.relative_to(incoming_root)
                if _preserved(relative) or ".git" in relative.parts:
                    continue
                dst = installed_root / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, backup)
                    overwritten.append((dst, backup))
                else:
                    created.append(dst)
                shutil.copy2(src, dst)
                copied += 1
        except Exception:
            for dst in reversed(created):
                try:
                    if dst.exists():
                        dst.unlink()
                except OSError:
                    pass
            for dst, backup in reversed(overwritten):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, dst)
            raise

    return {"mode": "bundle", "files_updated": copied}


def _download_bundle(timeout: float = 30.0) -> tuple[tempfile.TemporaryDirectory, Path]:
    response = requests.get(ARCHIVE_URL, timeout=timeout)
    response.raise_for_status()
    temp = tempfile.TemporaryDirectory(prefix="ssm-update-")
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        archive.extractall(temp.name)
    roots = [p for p in Path(temp.name).iterdir() if p.is_dir()]
    if len(roots) != 1:
        temp.cleanup()
        raise RuntimeError("unexpected GitHub archive layout")
    return temp, roots[0]


def _install_mode(root: Path) -> str:
    if (root / ".git").exists():
        return "git"
    if (root / "SKILL.md").exists() and (root / "pyproject.toml").exists():
        return "bundle"
    return "pip"


def perform_update(dry_run: bool = False) -> dict:
    status = version_status()
    if status.get("latest") is None:
        raise RuntimeError(f"unable to check latest version: {status.get('check_error', 'unknown error')}")
    if not status["update_available"]:
        return {**status, "updated": False, "mode": _install_mode(_root())}

    root = _root()
    mode = _install_mode(root)
    if dry_run:
        return {**status, "updated": False, "dry_run": True, "mode": mode}

    if mode == "git":
        subprocess.check_call(["git", "-C", str(root), "pull", "--ff-only"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", str(root)])
    elif mode == "bundle":
        temp, incoming = _download_bundle()
        try:
            apply_bundle_update(root, incoming)
        finally:
            temp.cleanup()
    else:
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-deps",
            ARCHIVE_URL,
        ])

    return {
        "current": status["current"],
        "latest": status["latest"],
        "updated": True,
        "mode": mode,
        "preserved": ["config/watchlist.csv", "config/overrides.json", "output/", "SEC_USER_AGENT"],
    }
