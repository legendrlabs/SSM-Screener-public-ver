from __future__ import annotations

from importlib import metadata
from pathlib import Path
import re
import shutil
import sys
import tempfile

import requests

from .release_policy import SOURCE_COMMIT_RE, is_preserved_path, project_version, sha256_file

PACKAGE_NAME = "special-situation-microcap"
REPO = "legendrlabs/SSM-Screener-public-ver"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
MANIFEST_ASSET_NAME = "release.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    return tuple(int(p) for p in parts[:3])


def current_version() -> str:
    local = _root() / "pyproject.toml"
    if local.exists():
        try:
            return project_version(_root())
        except (OSError, ValueError):
            pass
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _manifest_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("manifest managed path must be a normalized repository-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ValueError(f"unsafe manifest managed path: {value}")
    if relative.as_posix() != value:
        raise ValueError(f"non-normalized manifest managed path: {value}")
    return relative


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("release manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported release manifest schema")

    version = manifest.get("version")
    tag = manifest.get("tag")
    source_commit = manifest.get("source_commit")
    managed_files = manifest.get("managed_files")

    if not isinstance(version, str) or not version.strip():
        raise ValueError("release manifest version is missing")
    if tag != f"v{version}":
        raise ValueError("release manifest tag does not match version")
    if not isinstance(source_commit, str) or not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("release manifest source_commit is not a full lowercase commit SHA")
    if not isinstance(managed_files, dict):
        raise ValueError("release manifest managed_files must be an object")

    for path_text, digest in managed_files.items():
        relative = _manifest_path(path_text)
        if is_preserved_path(relative):
            raise ValueError(f"release manifest contains preserved user path: {path_text}")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise ValueError(f"invalid managed-file hash for {path_text}")

    return manifest


def fetch_release_manifest(timeout: float = 2.0) -> dict:
    release_response = requests.get(LATEST_RELEASE_API, timeout=timeout)
    release_response.raise_for_status()
    release = release_response.json()
    if not isinstance(release, dict):
        raise ValueError("latest release metadata is not an object")

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("latest release has no asset list")
    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict)
            and item.get("name") == MANIFEST_ASSET_NAME
            and isinstance(item.get("browser_download_url"), str)
        ),
        None,
    )
    if asset is None:
        raise ValueError("latest release does not contain release.json")

    manifest_response = requests.get(asset["browser_download_url"], timeout=timeout)
    manifest_response.raise_for_status()
    manifest = validate_manifest(manifest_response.json())

    tag_name = release.get("tag_name")
    if tag_name is not None and tag_name != manifest["tag"]:
        raise ValueError("release tag does not match release manifest tag")
    return manifest


def latest_version(timeout: float = 2.0) -> str:
    return fetch_release_manifest(timeout=timeout)["version"]


def version_status() -> dict:
    current = current_version()
    try:
        manifest = fetch_release_manifest()
    except Exception as exc:
        return {
            "current": current,
            "latest": None,
            "update_available": False,
            "check_error": f"{type(exc).__name__}: {exc}",
        }
    latest = manifest["version"]
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


def immutable_archive_url(source_commit: str) -> str:
    if not isinstance(source_commit, str) or not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase commit SHA")
    return f"https://github.com/{REPO}/archive/{source_commit}.zip"


def validate_archive(incoming_root: Path, manifest: dict, downloaded_source_commit: str) -> None:
    manifest = validate_manifest(manifest)
    if downloaded_source_commit != manifest["source_commit"]:
        raise ValueError("archive source_commit does not match release manifest source_commit")

    incoming_root = Path(incoming_root)
    try:
        archive_version = project_version(incoming_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"archive project version unavailable: {exc}") from exc
    if archive_version != manifest["version"]:
        raise ValueError(
            f"archive project version {archive_version!r} does not match manifest version {manifest['version']!r}"
        )

    for path_text, expected in manifest["managed_files"].items():
        relative = _manifest_path(path_text)
        candidate = incoming_root / relative
        if not candidate.is_file():
            raise ValueError(f"managed file missing from archive: {path_text}")
        actual = f"sha256:{sha256_file(candidate)}"
        if actual != expected:
            raise ValueError(f"managed-file hash mismatch: {path_text}")


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
                if is_preserved_path(relative) or ".git" in relative.parts:
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

    mode = _install_mode(_root())
    if dry_run:
        return {**status, "updated": False, "dry_run": True, "mode": mode}

    raise RuntimeError("immutable update application is not wired yet")
