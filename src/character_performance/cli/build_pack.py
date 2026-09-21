from __future__ import annotations

import argparse
from pathlib import Path

from character_performance.build import build_pack
from character_performance.sources.registry import BuildPolicy


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a validated performance pack")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("data/compiled"))
    parser.add_argument("--commercial", action="store_true")
    parser.add_argument("--redistribute", action="store_true")
    parser.add_argument("--allow-share-alike", action="store_true")
    args = parser.parse_args()

    result = build_pack(
        project_root=args.project_root.resolve(),
        output_dir=args.output.resolve(),
        policy=BuildPolicy(
            commercial=args.commercial,
            redistribution=args.redistribute,
            allow_share_alike=args.allow_share_alike,
        ),
    )
    print(result.manifest_path)


if __name__ == "__main__":
    main()

