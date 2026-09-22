"""CLI adapters for generation briefs and local text extraction.

The command is intentionally thin: validation, selection and extraction stay
in the Python seams so a writing agent can use exactly the same behaviour as
the command line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from character_performance.domain.behavior_models import ExtractionRequest, GenerationRequest
from character_performance.extraction import RuleBasedBehaviorExtractor
from character_performance.memory import SQLiteBehaviorMemory
from character_performance.ontology.pack import PerformancePack
from character_performance.prompt_brief import PromptBriefBuilder, estimate_prompt_tokens


def _load_document(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request document must contain an object")
    for key in ("generation_request", "request"):
        if key in payload and isinstance(payload[key], dict):
            payload = payload[key]
            break
    return payload


def _load_pack(root: Path | None) -> PerformancePack | None:
    if root is None:
        candidate = Path.cwd()
        if not (candidate / "data" / "ontology" / "units.yaml").is_file():
            return None
        root = candidate
    return PerformancePack.from_project(root)


class BriefCLIAdapter:
    """The CLI-facing adapter shares the same builder as Python callers."""

    def __init__(self, *, pack: PerformancePack | None = None) -> None:
        self.builder = PromptBriefBuilder(pack)

    def prepare(
        self,
        request: GenerationRequest,
        memory: SQLiteBehaviorMemory,
        *,
        preview: bool = False,
    ):
        history = memory.query_history(request.position, request.character.id)
        brief = self.builder.build(request, history)
        if not preview:
            memory.save_identity(request.position.book_id, request.behavior_identity)
            memory.create_run(request, brief)
        return brief


def _prepare(args: argparse.Namespace) -> None:
    request = GenerationRequest.model_validate(_load_document(args.request))
    pack = _load_pack(args.pack_root)
    memory = SQLiteBehaviorMemory(args.db)
    try:
        brief = BriefCLIAdapter(pack=pack).prepare(request, memory, preview=args.preview)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "brief.json").write_text(
            brief.model_dump_json(indent=2), encoding="utf-8"
        )
        (args.output / "prompt.txt").write_text(brief.prompt_fragment + "\n", encoding="utf-8")
        print(json.dumps({
            "run_id": brief.run_id,
            "memory_revision": brief.memory_revision,
            "token_budget": brief.token_budget,
            "prompt_tokens": estimate_prompt_tokens(brief.prompt_fragment),
            "brief": str(args.output / "brief.json"),
            "prompt": str(args.output / "prompt.txt"),
            "preview": args.preview,
        }, ensure_ascii=False))
    finally:
        memory.close()


def _extract(args: argparse.Namespace) -> None:
    payload = _load_document(args.request)
    request = ExtractionRequest.model_validate(payload)
    pack = _load_pack(args.pack_root)
    result = RuleBasedBehaviorExtractor(pack).extract(request)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({
        "run_id": result.run_id,
        "behaviors": len(result.behaviors),
        "unresolved_spans": len(result.unresolved_spans),
        "output": str(args.output),
    }, ensure_ascii=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cpp-behavior")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="build a model-facing generation brief")
    prepare.add_argument("request", type=Path)
    prepare.add_argument("--db", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--pack-root", type=Path, default=None)
    prepare.add_argument("--preview", action="store_true", help="do not create a durable run")
    prepare.set_defaults(handler=_prepare)
    extract = commands.add_parser("extract", help="extract behaviour from a draft request")
    extract.add_argument("request", type=Path)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--pack-root", type=Path, default=None)
    extract.set_defaults(handler=_extract)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.handler(args)


__all__ = ["BriefCLIAdapter", "main"]


if __name__ == "__main__":
    main()
