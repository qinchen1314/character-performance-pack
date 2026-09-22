"""Prepare anonymous literary-review packets and aggregate human ratings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from character_performance.blind_review import (
    BlindKey,
    BlindRating,
    ReviewCase,
    aggregate_ratings,
    build_blind_packet,
)
from character_performance.catalog import CatalogRecord


CATALOG_FILES = (
    "micro.json",
    "face-gaze.json",
    "body.json",
    "spatial.json",
    "physiology.json",
    "speech.json",
    "xianxia.json",
)


def _read_records(project_root: Path) -> tuple[CatalogRecord, ...]:
    records = tuple(
        CatalogRecord.model_validate(row)
        for name in CATALOG_FILES
        for row in json.loads(
            (project_root / "data" / "catalog" / name).read_text(encoding="utf-8")
        )
    )
    return tuple(record for record in records if record.editorial_status == "active")


def prepare_review(
    project_root: Path,
    output_dir: Path,
    *,
    seed: int = 20260921,
    lenses_per_record: int = 3,
) -> tuple[Path, Path]:
    lens_path = project_root / "data" / "review" / "lenses.json"
    cases = tuple(
        ReviewCase.model_validate(row)
        for row in json.loads(lens_path.read_text(encoding="utf-8"))
    )
    packet, key = build_blind_packet(
        _read_records(project_root),
        cases,
        seed=seed,
        lenses_per_record=lenses_per_record,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "packet.json"
    key_path = output_dir / "answer-key.json"
    packet_path.write_text(
        packet.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    key_path.write_text(key.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return packet_path, key_path


def aggregate_review(
    key_path: Path,
    rating_paths: Sequence[Path],
    output_path: Path,
    *,
    minimum_reviewers: int = 2,
) -> Path:
    key = BlindKey.model_validate_json(key_path.read_text(encoding="utf-8"))
    ratings = tuple(
        BlindRating.model_validate(row)
        for path in rating_paths
        for row in json.loads(path.read_text(encoding="utf-8"))
    )
    report = aggregate_ratings(
        key.unit_ids, ratings, minimum_reviewers=minimum_reviewers
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run identity-blind human prose review")
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--project-root", type=Path, default=Path.cwd())
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=20260921)
    prepare.add_argument("--lenses-per-record", type=int, default=3)
    aggregate = subcommands.add_parser("aggregate")
    aggregate.add_argument("--key", type=Path, required=True)
    aggregate.add_argument("--ratings", type=Path, nargs="+", required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.add_argument("--minimum-reviewers", type=int, default=2)
    args = parser.parse_args()
    if args.command == "prepare":
        paths = prepare_review(
            args.project_root,
            args.output,
            seed=args.seed,
            lenses_per_record=args.lenses_per_record,
        )
        print("\n".join(str(path) for path in paths))
    else:
        print(
            aggregate_review(
                args.key,
                args.ratings,
                args.output,
                minimum_reviewers=args.minimum_reviewers,
            )
        )


if __name__ == "__main__":
    main()
