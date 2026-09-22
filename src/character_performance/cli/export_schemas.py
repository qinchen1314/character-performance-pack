from __future__ import annotations

import argparse
import json
from pathlib import Path

from character_performance.domain.models import (
    CharacterProfile, EmotionState, PerformancePlan, PerformanceRequest,
    PerformanceUnit, RenderContext, RenderResult, SceneState, WorldState,
    ActiveAction, BlockingGoal, SceneLayout,
)
from character_performance.modifiers import Modifier
from character_performance.domain.behavior_models import (
    AcceptedDraft,
    ArcState,
    AuditIssue,
    AuditMetrics,
    AuditResult,
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    CandidateBehavior,
    ChangedSpan,
    CommitRequest,
    CommitResult,
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    NarrativePosition,
    OverusedBehavior,
    PreservationChecks,
    ReactionStrategyPlan,
    RelationshipStrategyOverride,
    RewriteRequest,
    RewriteResult,
    SignatureFamily,
    SourceSpan,
    StyleContext,
    SyntaxFeatures,
    TextReplacement,
    TextSpan,
)

SCHEMA_MODELS = (
    EmotionState, PerformanceUnit, PerformanceRequest, PerformancePlan,
    CharacterProfile, SceneState, WorldState, RenderContext, RenderResult, Modifier,
    ActiveAction, BlockingGoal, SceneLayout,
    NarrativePosition, SignatureFamily, RelationshipStrategyOverride, ArcState,
    BehaviorIdentity, ReactionStrategyPlan, SyntaxFeatures, BehaviorFingerprint,
    TextSpan, BehaviorOccurrence, StyleContext, GenerationRequest,
    OverusedBehavior, CandidateBehavior, GenerationBrief, ExtractionRequest,
    ExtractedBehavior, ExtractionResult, GeneratedDraft, SourceSpan, AuditIssue, AuditMetrics,
    AuditResult, RewriteRequest, TextReplacement, ChangedSpan,
    PreservationChecks, RewriteResult, AcceptedDraft, CommitRequest, CommitResult,
)


def export_schemas(output_dir: Path) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in SCHEMA_MODELS:
        path = output_dir / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export canonical JSON schemas")
    parser.add_argument("--output", type=Path, default=Path("schemas"))
    args = parser.parse_args()
    for path in export_schemas(args.output):
        print(path)


if __name__ == "__main__":
    main()
