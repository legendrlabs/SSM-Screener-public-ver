from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
import tomllib

PRESERVE_EXACT = {
    Path("config/watchlist.csv"),
    Path("config/overrides.json"),
}
PRESERVE_PREFIXES = (Path("output"),)
GENERATED_EXACT = {Path("release.json")}
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".superpowers",
}
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _safe_relative(relative: Path) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe repository-relative path: {relative}")
    if any(part in ("", ".") for part in relative.parts):
        raise ValueError(f"non-normalized repository-relative path: {relative}")
    return relative


def project_version(root: Path) -> str:
    data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml [project].version is missing")
    return version.strip()


def is_preserved_path(relative: Path) -> bool:
    relative = _safe_relative(relative)
    if relative in PRESERVE_EXACT:
        return True
    return any(relative == prefix or prefix in relative.parents for prefix in PRESERVE_PREFIXES)


def _is_generated_or_ignored(relative: Path) -> bool:
    if relative in GENERATED_EXACT:
        return True
    if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in relative.parts):
        return True
    return False


def _tracked_files(root: Path) -> list[Path] | None:
    if not (root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]


def iter_managed_files(root: Path) -> list[Path]:
    root = Path(root).resolve()
    candidates = _tracked_files(root)
    if candidates is None:
        candidates = [path for path in root.rglob("*") if path.is_file()]

    managed: list[Path] = []
    for path in candidates:
        path = Path(path)
        if not path.is_file():
            continue
        relative = _safe_relative(path.resolve().relative_to(root))
        if is_preserved_path(relative) or _is_generated_or_ignored(relative):
            continue
        managed.append(root / relative)
    return sorted(managed, key=lambda path: path.relative_to(root).as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, tag: str, source_commit: str) -> dict:
    root = Path(root).resolve()
    version = project_version(root)
    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise ValueError(f"release tag {tag!r} does not match project version {expected_tag!r}")
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source_commit must be a full 40-character lowercase hexadecimal SHA")

    managed_files = {
        path.relative_to(root).as_posix(): f"sha256:{sha256_file(path)}"
        for path in iter_managed_files(root)
    }
    return {
        "schema_version": 1,
        "version": version,
        "tag": tag,
        "source_commit": source_commit,
        "managed_files": managed_files,
    }
