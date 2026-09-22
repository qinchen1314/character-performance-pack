"""CLI for identity-blind review packets and consolidated acceptance gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from character_performance.acceptance import (
    AcceptanceEvaluator,
    AutomaticEvidence,
    CharacterBlindKey,
    CharacterBlindRating,
    CharacterBlindSample,
    aggregate_character_blind_ratings,
    build_character_blind_packet,
    render_acceptance_markdown,
)


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def prepare_character_review(samples_path: Path, output: Path, *, seed: int) -> tuple[Path, Path]:
    payload = _load(samples_path)
    if not isinstance(payload, list):
        raise ValueError("blind samples must be a list")
    samples = tuple(CharacterBlindSample.model_validate(item) for item in payload)
    packet, key = build_character_blind_packet(samples, seed=seed)
    output.mkdir(parents=True, exist_ok=True)
    packet_path = output / "packet.json"
    key_path = output / "answer-key.json"
    packet_path.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    key_path.write_text(key.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return packet_path, key_path


def evaluate_acceptance_files(
    automatic_path: Path,
    output: Path,
    *,
    key_path: Path | None = None,
    rating_paths: tuple[Path, ...] = (),
    minimum_reviewers: int = 2,
) -> Path:
    automatic = AutomaticEvidence.model_validate(_load(automatic_path))
    human = None
    if key_path is not None or rating_paths:
        if key_path is None or not rating_paths:
            raise ValueError("both --key and --ratings are required for the human gate")
        key = CharacterBlindKey.model_validate_json(key_path.read_text(encoding="utf-8"))
        ratings = tuple(
            CharacterBlindRating.model_validate(row)
            for path in rating_paths
            for row in _load(path)
        )
        human = aggregate_character_blind_ratings(
            key, ratings, minimum_reviewers=minimum_reviewers
        )
    report = AcceptanceEvaluator().evaluate(automatic, human)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".md", ".markdown"}:
        output.write_text(render_acceptance_markdown(report), encoding="utf-8")
    elif output.suffix.lower() == ".json":
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    else:
        raise ValueError("acceptance output must end in .json, .md or .markdown")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(prog="cpp-behavior-verify")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-human", help="create an identity-blind character review packet")
    prepare.add_argument("samples", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=20260922)
    evaluate = commands.add_parser("evaluate", help="evaluate every automatic and human acceptance gate")
    evaluate.add_argument("automatic", type=Path)
    evaluate.add_argument("--key", type=Path)
    evaluate.add_argument("--ratings", type=Path, nargs="*")
    evaluate.add_argument("--minimum-reviewers", type=int, default=2)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-human":
        packet, key = prepare_character_review(args.samples, args.output, seed=args.seed)
        print(json.dumps({"event": "behavior.verify.human_prepared", "packet": str(packet), "key": str(key)}, ensure_ascii=False))
    else:
        result = evaluate_acceptance_files(
            args.automatic,
            args.output,
            key_path=args.key,
            rating_paths=tuple(args.ratings or ()),
            minimum_reviewers=args.minimum_reviewers,
        )
        print(json.dumps({"event": "behavior.verify.completed", "output": str(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()


__all__ = ["evaluate_acceptance_files", "main", "prepare_character_review"]
