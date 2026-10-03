from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ssm.release_policy import build_manifest, iter_managed_files, project_version


SOURCE_COMMIT = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


def _make_root(tmp_path: Path, version: str = "9.8.7") -> Path:
    root = tmp_path / "repo"
    (root / "ssm").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "output").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"fixture\"\nversion = \"%s\"\n" % version,
        encoding="utf-8",
    )
    (root / "ssm" / "engine.py").write_text("print('managed')\n", encoding="utf-8")
    (root / "config" / "default.json").write_text("{}\n", encoding="utf-8")
    (root / "config" / "watchlist.csv").write_text("ticker\nKEEP\n", encoding="utf-8")
    (root / "config" / "overrides.json").write_text('{"KEEP": true}\n', encoding="utf-8")
    (root / "output" / "latest.md").write_text("keep me\n", encoding="utf-8")
    return root


def test_manifest_version_matches_pyproject(tmp_path):
    root = _make_root(tmp_path)
    manifest = build_manifest(root, tag="v9.8.7", source_commit=SOURCE_COMMIT)

    assert project_version(root) == "9.8.7"
    assert manifest["schema_version"] == 1
    assert manifest["version"] == "9.8.7"
    assert manifest["tag"] == "v9.8.7"


def test_checked_out_manifest_version_matches_checked_out_pyproject():
    version = project_version(ROOT)
    manifest = build_manifest(ROOT, tag=f"v{version}", source_commit=SOURCE_COMMIT)

    assert manifest["version"] == version
    assert manifest["tag"] == f"v{version}"
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert "config/watchlist.csv" not in manifest["managed_files"]
    assert "config/overrides.json" not in manifest["managed_files"]
    assert not any(path.startswith("output/") for path in manifest["managed_files"])


def test_manifest_rejects_tag_version_mismatch(tmp_path):
    root = _make_root(tmp_path)

    with pytest.raises(ValueError, match="tag"):
        build_manifest(root, tag="v9.8.8", source_commit=SOURCE_COMMIT)


def test_manifest_records_supplied_source_commit(tmp_path):
    root = _make_root(tmp_path)
    manifest = build_manifest(root, tag="v9.8.7", source_commit=SOURCE_COMMIT)

    assert manifest["source_commit"] == SOURCE_COMMIT


def test_manifest_excludes_user_owned_paths(tmp_path):
    root = _make_root(tmp_path)
    manifest = build_manifest(root, tag="v9.8.7", source_commit=SOURCE_COMMIT)

    paths = set(manifest["managed_files"])
    assert "config/watchlist.csv" not in paths
    assert "config/overrides.json" not in paths
    assert not any(path == "output" or path.startswith("output/") for path in paths)
    assert "config/default.json" in paths


def test_manifest_hashes_managed_files(tmp_path):
    root = _make_root(tmp_path)
    manifest = build_manifest(root, tag="v9.8.7", source_commit=SOURCE_COMMIT)

    expected = hashlib.sha256((root / "ssm" / "engine.py").read_bytes()).hexdigest()
    assert manifest["managed_files"]["ssm/engine.py"] == f"sha256:{expected}"


def test_managed_paths_are_normalized_and_safe(tmp_path):
    root = _make_root(tmp_path)
    paths = [path.relative_to(root).as_posix() for path in iter_managed_files(root)]
    manifest = build_manifest(root, tag="v9.8.7", source_commit=SOURCE_COMMIT)

    assert paths == sorted(paths)
    assert set(paths) == set(manifest["managed_files"])
    assert all(not path.startswith("/") for path in paths)
    assert all(".." not in Path(path).parts for path in paths)
    assert all("\\" not in path for path in paths)
    assert all(value.startswith("sha256:") and len(value) == 71 for value in manifest["managed_files"].values())
