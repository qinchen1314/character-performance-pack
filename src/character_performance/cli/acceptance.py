"""CLI for identity-blind review packets and consolidated acceptance gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from character_performance.calibration import calibrate_manifest, render_calibration_markdown
from character_performance.gate_policy import load_gate_policy
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
    threshold_policy_path: Path | None = None,
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
    gate_policy = (
        load_gate_policy(threshold_policy_path, require_ready=True)
        if threshold_policy_path is not None
        else None
    )
    report = AcceptanceEvaluator(gate_policy=gate_policy).evaluate(automatic, human)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".md", ".markdown"}:
        output.write_text(render_acceptance_markdown(report), encoding="utf-8")
    elif output.suffix.lower() == ".json":
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    else:
        raise ValueError("acceptance output must end in .json, .md or .markdown")
    return output


def calibrate_thresholds(
    manifest: Path,
    output: Path,
    *,
    markdown: Path | None = None,
    policy_output: Path | None = None,
) -> tuple[Path, Path | None, Path | None]:
    report = calibrate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_calibration_markdown(report), encoding="utf-8")
    if policy_output is not None:
        policy_output.parent.mkdir(parents=True, exist_ok=True)
        policy_output.write_text(report.policy_json(), encoding="utf-8")
    return output, markdown, policy_output


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
    evaluate.add_argument("--thresholds", type=Path)
    calibrate = commands.add_parser(
        "calibrate", help="calibrate prose gates from accepted, formulaic, paired and sweep corpora"
    )
    calibrate.add_argument("manifest", type=Path)
    calibrate.add_argument("--output", type=Path, required=True)
    calibrate.add_argument("--markdown", type=Path)
    calibrate.add_argument("--policy-output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-human":
        packet, key = prepare_character_review(args.samples, args.output, seed=args.seed)
        print(json.dumps({"event": "behavior.verify.human_prepared", "packet": str(packet), "key": str(key)}, ensure_ascii=False))
    elif args.command == "calibrate":
        result, markdown, policy = calibrate_thresholds(
            args.manifest,
            args.output,
            markdown=args.markdown,
            policy_output=args.policy_output,
        )
        payload = {
            "event": "behavior.verify.calibrated",
            "output": str(result),
        }
        if markdown is not None:
            payload["markdown"] = str(markdown)
        if policy is not None:
            payload["policy"] = str(policy)
        print(json.dumps(payload, ensure_ascii=False))
    else:
        result = evaluate_acceptance_files(
            args.automatic,
            args.output,
            key_path=args.key,
            rating_paths=tuple(args.ratings or ()),
            minimum_reviewers=args.minimum_reviewers,
            threshold_policy_path=args.thresholds,
        )
        print(json.dumps({"event": "behavior.verify.completed", "output": str(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()


__all__ = ["calibrate_thresholds", "evaluate_acceptance_files", "main", "prepare_character_review"]
