import json

import yaml

from character_performance.acceptance import AcceptanceReport, AutomaticEvidence, EvidenceProvenance
from character_performance.cli.acceptance import evaluate_acceptance_files, prepare_character_review


def _automatic() -> AutomaticEvidence:
    return AutomaticEvidence(
        provenance=EvidenceProvenance(
            producer="cpp-behavior-verification-suite",
            commit_sha="abcdef1",
            generated_at="2026-09-22T00:00:00Z",
            history_row_count=1_000_000,
            book_occurrence_count=200_000,
            test_counts={
                "unit": 1,
                "property": 1,
                "integration": 1,
                "scenario": 1,
                "chapter_benchmark": 1,
                "fault_injection": 1,
                "performance": 1,
            },
        ),
        immediate_exact_repeat_rate=0,
        chapter_semantic_over_limit=0,
        cliche_group_share=0.1,
        maximum_character_channel_share=0.4,
        cross_chapter_function_channel_repeat_rate=0.05,
        semantic_repeat_recall=0.91,
        semantic_repeat_precision=0.86,
        span_accuracy=0.99,
        rewrite_preservation_rate=1,
        duplicate_history_count=0,
        fault_injection_passed=True,
        prepare_p95_ms=90,
        rule_extraction_p95_ms=70,
        history_query_p95_ms=20,
        commit_p95_ms=40,
        deterministic_replay_passed=True,
    )


def test_acceptance_cli_keeps_answer_key_separate_and_reports_pending_human(tmp_path) -> None:
    samples = tmp_path / "samples.yaml"
    samples.write_text(
        yaml.safe_dump(
            [
                {"sample_id": "a", "character_id": "char.a", "character_name": "洛寒", "text": "洛寒先听完。"},
                {"sample_id": "b", "character_id": "char.b", "character_name": "程雾", "text": "程雾截住话头。"},
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    packet, key = prepare_character_review(samples, tmp_path / "blind", seed=1)
    assert "char.a" not in packet.read_text(encoding="utf-8")
    assert "char.a" in key.read_text(encoding="utf-8")

    automatic = tmp_path / "automatic.json"
    automatic.write_text(_automatic().model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "acceptance.json"
    evaluate_acceptance_files(automatic, output)
    report = AcceptanceReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert report.overall_status == "pending_human"
    assert not report.completion_claim_allowed


def test_acceptance_cli_loads_ready_threshold_policy(tmp_path) -> None:
    automatic = tmp_path / "automatic.json"
    automatic.write_text(_automatic().model_dump_json(indent=2), encoding="utf-8")
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "status": "ready",
                "source_report_sha256": "sha256:" + "c" * 64,
                "gates": {
                    "CLICHE_GROUP_SHARE": {"threshold": 0.05, "comparator": "<="}
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "acceptance.json"

    evaluate_acceptance_files(automatic, output, threshold_policy_path=thresholds)

    report = AcceptanceReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert report.automatic_status == "failed"
    gate = next(item for item in report.automatic_gates if item.code == "CLICHE_GROUP_SHARE")
    assert gate.threshold == 0.05
