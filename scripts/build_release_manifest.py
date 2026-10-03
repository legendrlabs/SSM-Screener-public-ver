from __future__ import annotations

import argparse
import json
from pathlib import Path

from ssm.release_policy import build_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build immutable SSM release metadata")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    manifest = build_manifest(Path(args.root), args.tag, args.source_commit)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
