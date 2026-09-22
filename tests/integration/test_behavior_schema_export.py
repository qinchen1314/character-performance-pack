from __future__ import annotations

import json

from character_performance.cli.export_schemas import SCHEMA_MODELS, export_schemas


EXPECTED_BEHAVIOR_SCHEMAS = {
    "NarrativePosition.schema.json",
    "BehaviorIdentity.schema.json",
    "ReactionStrategyPlan.schema.json",
    "BehaviorFingerprint.schema.json",
    "BehaviorOccurrence.schema.json",
    "GenerationRequest.schema.json",
    "GenerationBrief.schema.json",
    "ExtractionRequest.schema.json",
    "ExtractionResult.schema.json",
    "SourceSpan.schema.json",
    "AuditResult.schema.json",
    "RewriteRequest.schema.json",
    "RewriteResult.schema.json",
    "AcceptedDraft.schema.json",
    "CommitRequest.schema.json",
    "CommitResult.schema.json",
}


def test_export_schemas_includes_complete_behavior_control_contract(tmp_path) -> None:
    paths = export_schemas(tmp_path)
    names = {path.name for path in paths}

    assert EXPECTED_BEHAVIOR_SCHEMAS <= names
    for name in EXPECTED_BEHAVIOR_SCHEMAS:
        document = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert document["type"] == "object"
        assert document["additionalProperties"] is False

    occurrence_schema = json.loads(
        (tmp_path / "BehaviorOccurrence.schema.json").read_text(encoding="utf-8")
    )
    assert occurrence_schema["allOf"][0]["then"]["required"] == [
        "accepted_revision"
    ]


def test_schema_model_registry_has_no_duplicate_output_names() -> None:
    names = [model.__name__ for model in SCHEMA_MODELS]

    assert len(names) == len(set(names))
