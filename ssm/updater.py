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

from .release_policy import SOURCE_COMMIT_RE, is_preserved_path, project_version, sha256_file

PACKAGE_NAME = "special-situation-microcap"
REPO = "legendrlabs/SSM-Screener-public-ver"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
MANIFEST_ASSET_NAME = "release.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PINNED_ARCHIVE_RE = re.compile(
    rf"^https://github\.com/{re.escape(REPO)}/archive/[0-9a-f]{{40}}\.zip$"
)


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


def _status_from_manifest(manifest: dict) -> dict:
    current = current_version()
    latest = manifest["version"]
    return {
        "current": current,
        "latest": latest,
        "update_available": _version_tuple(latest) > _version_tuple(current),
    }


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
    return _status_from_manifest(manifest)


def maybe_update_notice(interactive: bool | None = None, input_fn=None) -> bool:
    status = version_status()
    if not status.get("update_available"):
        return False

    print(
        f"SSM {status['latest']} available (current {status['current']}). Run: ssm update",
        file=sys.stderr,
    )

    if interactive is None:
        interactive = bool(sys.stdin.isatty() and sys.stderr.isatty())
    if not interactive:
        return False

    if input_fn is None:
        input_fn = input
    try:
        answer = input_fn("Update now? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        print("Update skipped.", file=sys.stderr)
        return False

    if str(answer).strip().lower() not in {"y", "yes"}:
        return False

    try:
        result = perform_update(False)
    except Exception as exc:
        print(
            f"Update failed; continuing with SSM {status['current']} "
            f"({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )
        return False

    updated = bool(result.get("updated"))
    if updated:
        print(f"SSM updated to {result.get('latest', status['latest'])}.", file=sys.stderr)
    return updated


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


def apply_bundle_update(
    installed_root: Path,
    incoming_root: Path,
    managed_paths: set[str] | None = None,
) -> dict:
    installed_root = Path(installed_root)
    incoming_root = Path(incoming_root)
    overwritten: list[tuple[Path, Path]] = []
    created: list[Path] = []
    copied = 0

    if managed_paths is None:
        sources = sorted(p for p in incoming_root.rglob("*") if p.is_file())
    else:
        sources = [incoming_root / _manifest_path(path_text) for path_text in sorted(managed_paths)]

    with tempfile.TemporaryDirectory(prefix="ssm-update-backup-") as backup_dir:
        backup_root = Path(backup_dir)
        try:
            for src in sources:
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


def _safe_extract_archive(payload: bytes, destination: Path) -> Path:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"unsafe archive path: {member.filename}")
        archive.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError("unexpected GitHub archive layout")
    return roots[0]


def _download_bundle(
    source_commit: str,
    timeout: float = 30.0,
) -> tuple[tempfile.TemporaryDirectory, Path, str]:
    url = immutable_archive_url(source_commit)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    temp = tempfile.TemporaryDirectory(prefix="ssm-update-")
    try:
        incoming = _safe_extract_archive(response.content, Path(temp.name))
    except Exception:
        temp.cleanup()
        raise
    return temp, incoming, source_commit


def _install_mode(root: Path) -> str:
    if (root / ".git").exists():
        return "git"
    if (root / "pyproject.toml").exists() and (root / "ssm").is_dir():
        return "bundle"
    return "pip"


def _update_git_checkout(root: Path, source_commit: str) -> None:
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase commit SHA")
    root = Path(root)
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"],
    )
    if isinstance(dirty, bytes):
        dirty = dirty.decode("utf-8", errors="replace")
    if str(dirty).strip():
        raise RuntimeError("git checkout has local changes; refusing immutable update")

    subprocess.check_call(["git", "-C", str(root), "fetch", "origin", source_commit])
    subprocess.check_call(["git", "-C", str(root), "merge", "--ff-only", source_commit])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", str(root)])


def _update_pip_install(archive_url: str) -> None:
    if not isinstance(archive_url, str) or not PINNED_ARCHIVE_RE.fullmatch(archive_url):
        raise ValueError("pip update source must be a commit-pinned SSM archive URL")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-deps", archive_url]
    )


def perform_update(dry_run: bool = False) -> dict:
    try:
        manifest = fetch_release_manifest()
    except Exception as exc:
        raise RuntimeError(f"unable to check latest version: {type(exc).__name__}: {exc}") from exc

    status = _status_from_manifest(manifest)
    root = _root()
    mode = _install_mode(root)
    if not status["update_available"]:
        return {**status, "updated": False, "mode": mode}
    if dry_run:
        return {**status, "updated": False, "dry_run": True, "mode": mode}

    temp, incoming, downloaded_source_commit = _download_bundle(manifest["source_commit"])
    try:
        validate_archive(incoming, manifest, downloaded_source_commit)
        if mode == "bundle":
            apply_bundle_update(root, incoming, set(manifest["managed_files"]))
        elif mode == "git":
            _update_git_checkout(root, manifest["source_commit"])
        elif mode == "pip":
            _update_pip_install(immutable_archive_url(manifest["source_commit"]))
        else:
            raise RuntimeError(f"unsupported immutable update mode: {mode}")
    finally:
        temp.cleanup()

    return {
        "current": status["current"],
        "latest": status["latest"],
        "updated": True,
        "mode": mode,
        "preserved": ["config/watchlist.csv", "config/overrides.json", "output/", "SEC_USER_AGENT"],
    }
