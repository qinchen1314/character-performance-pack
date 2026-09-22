"""CLI adapters for generation briefs and local text extraction.

The command is intentionally thin: validation, selection and extraction stay
in the Python seams so a writing agent can use exactly the same behaviour as
the command line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import yaml

from character_performance.behavior_control import BehaviorControlSystem
from character_performance.domain.behavior_models import (
    AuditResult,
    ExtractionRequest,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    content_hash,
)
from character_performance.extraction import RuleBasedBehaviorExtractor
from character_performance.memory import (
    BehaviorCommitConflict,
    DraftHashMismatch,
    MemoryRevisionConflict,
    RunStateConflict,
    SQLiteBehaviorMemory,
)
from character_performance.ontology.pack import PerformancePack
from character_performance.prompt_brief import PromptBriefBuilder, estimate_prompt_tokens
from character_performance.reporting import BehaviorReportBuilder, render_html, render_markdown


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


def _emit(event: str, *, started: float, **fields: Any) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "level": "info",
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                **fields,
            },
            ensure_ascii=False,
        )
    )


class BehaviorCommandError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_EXCEPTION_CODES: tuple[tuple[type[Exception], str], ...] = (
    (MemoryRevisionConflict, "BEHAVIOR_MEMORY_REVISION_CONFLICT"),
    (DraftHashMismatch, "DRAFT_HASH_MISMATCH"),
    (RunStateConflict, "RUN_STATE_CONFLICT"),
    (BehaviorCommitConflict, "BEHAVIOR_COMMIT_CONFLICT"),
)


def _error_code(exc: Exception) -> str:
    if isinstance(exc, BehaviorCommandError):
        return exc.code
    return next(
        (code for exception_type, code in _EXCEPTION_CODES if isinstance(exc, exception_type)),
        "BEHAVIOR_COMMAND_FAILED",
    )


def _write_output(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    started = perf_counter()
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
        _emit(
            "behavior.prepare.completed",
            started=started,
            run_id=brief.run_id,
            memory_revision=brief.memory_revision,
            token_budget=brief.token_budget,
            prompt_tokens=estimate_prompt_tokens(brief.prompt_fragment),
            brief=str(args.output / "brief.json"),
            prompt=str(args.output / "prompt.txt"),
            preview=args.preview,
        )
    finally:
        memory.close()


def _extract(args: argparse.Namespace) -> None:
    started = perf_counter()
    payload = _load_document(args.request)
    request = ExtractionRequest.model_validate(payload)
    pack = _load_pack(args.pack_root)
    result = RuleBasedBehaviorExtractor(pack).extract(request)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    _emit(
        "behavior.extract.completed",
        started=started,
        run_id=result.run_id,
        behaviors=len(result.behaviors),
        unresolved_spans=len(result.unresolved_spans),
        output=str(args.output),
    )


def _audit(args: argparse.Namespace) -> None:
    started = perf_counter()
    brief = GenerationBrief.model_validate_json(args.brief.read_text(encoding="utf-8"))
    draft = GeneratedDraft(text=args.draft.read_text(encoding="utf-8"))
    memory = SQLiteBehaviorMemory(args.db)
    system = BehaviorControlSystem(pack=_load_pack(args.pack_root), repository=memory)
    try:
        recovered = system.recover(brief.run_id)
        if recovered.brief != brief:
            raise BehaviorCommandError(
                "RUN_STATE_CONFLICT", "brief file differs from durable run"
            )
        result = system.audit(brief.run_id, draft)
        _write_output(args.output, result.model_dump_json(indent=2) + "\n")
        _emit(
            "behavior.audit.completed",
            started=started,
            run_id=result.run_id,
            accepted=result.accepted,
            issue_count=len(result.issues),
            auto_rewrite_allowed=result.auto_rewrite_allowed,
            output=str(args.output),
        )
    finally:
        system.close()


def _rewrite(args: argparse.Namespace) -> None:
    started = perf_counter()
    audit = AuditResult.model_validate_json(args.audit.read_text(encoding="utf-8"))
    draft = args.draft.read_text(encoding="utf-8")
    memory = SQLiteBehaviorMemory(args.db)
    system = BehaviorControlSystem(pack=_load_pack(args.pack_root), repository=memory)
    try:
        recovered = system.recover(audit.run_id)
        if recovered.audit != audit:
            raise BehaviorCommandError(
                "RUN_STATE_CONFLICT", "audit file differs from durable run"
            )
        revised = system.rewrite(audit.run_id, draft, audit)
        _write_output(args.output, revised)
        _emit(
            "behavior.rewrite.completed",
            started=started,
            run_id=audit.run_id,
            changed=revised != draft,
            output=str(args.output),
        )
    finally:
        system.close()


def _commit(args: argparse.Namespace) -> None:
    started = perf_counter()
    audit = AuditResult.model_validate_json(args.audit.read_text(encoding="utf-8"))
    text = args.draft.read_text(encoding="utf-8")
    if not audit.accepted:
        raise BehaviorCommandError(
            "AUDIT_BLOCKED", "supplied audit did not accept the draft"
        )
    if audit.draft_hash != content_hash(text):
        raise BehaviorCommandError(
            "DRAFT_HASH_MISMATCH", "draft differs from the accepted audit"
        )
    audit.validate_draft(GeneratedDraft(text=text))
    memory = SQLiteBehaviorMemory(args.db)
    system = BehaviorControlSystem(pack=_load_pack(args.pack_root), repository=memory)
    try:
        recovered = system.recover(audit.run_id)
        if recovered.audit != audit:
            raise BehaviorCommandError(
                "RUN_STATE_CONFLICT", "audit file differs from durable run"
            )
        result = system.commit_text(audit.run_id, text)
        _emit(
            "behavior.commit.completed",
            started=started,
            **result.model_dump(mode="json"),
        )
    finally:
        system.close()


def _report(args: argparse.Namespace) -> None:
    started = perf_counter()
    memory = SQLiteBehaviorMemory(args.db)
    try:
        report = BehaviorReportBuilder(memory).build(args.book)
        suffix = args.output.suffix.lower()
        if suffix in {".md", ".markdown"}:
            rendered = render_markdown(report)
            report_format = "markdown"
        elif suffix in {".html", ".htm"}:
            rendered = render_html(report)
            report_format = "html"
        else:
            raise ValueError("report output must end in .md, .markdown, .html or .htm")
        _write_output(args.output, rendered)
        _emit(
            "behavior.report.completed",
            started=started,
            book_id=report.book_id,
            occurrence_count=report.occurrence_count,
            automatic_gates_passed=report.automatic_gates_passed,
            format=report_format,
            output=str(args.output),
        )
    finally:
        memory.close()


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
    audit = commands.add_parser("audit", help="audit a generated draft for a durable run")
    audit.add_argument("brief", type=Path)
    audit.add_argument("draft", type=Path)
    audit.add_argument("--db", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--pack-root", type=Path, default=None)
    audit.set_defaults(handler=_audit)
    rewrite = commands.add_parser("rewrite", help="rewrite only audit issue spans")
    rewrite.add_argument("audit", type=Path)
    rewrite.add_argument("draft", type=Path)
    rewrite.add_argument("--db", type=Path, required=True)
    rewrite.add_argument("--output", type=Path, required=True)
    rewrite.add_argument("--pack-root", type=Path, default=None)
    rewrite.set_defaults(handler=_rewrite)
    commit = commands.add_parser("commit", help="atomically commit an accepted draft")
    commit.add_argument("audit", type=Path)
    commit.add_argument("draft", type=Path)
    commit.add_argument("--db", type=Path, required=True)
    commit.add_argument("--pack-root", type=Path, default=None)
    commit.set_defaults(handler=_commit)
    report = commands.add_parser("report", help="render behavior distribution and hotspot reports")
    report.add_argument("--book", required=True)
    report.add_argument("--db", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.set_defaults(handler=_report)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.handler(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "behavior.command.failed",
                    "level": "error",
                    "command": args.command,
                    "error_code": _error_code(exc),
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


__all__ = ["BriefCLIAdapter", "main"]


if __name__ == "__main__":
    main()
