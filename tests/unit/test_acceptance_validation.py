from __future__ import annotations

from character_performance.acceptance import (
    AcceptanceEvaluator,
    AutomaticEvidence,
    CharacterBlindRating,
    CharacterBlindSample,
    aggregate_character_blind_ratings,
    build_character_blind_packet,
    EvidenceProvenance,
)


def _passing_automatic() -> AutomaticEvidence:
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
        immediate_exact_repeat_rate=0.0,
        chapter_semantic_over_limit=0,
        cliche_group_share=0.15,
        maximum_character_channel_share=0.40,
        cross_chapter_function_channel_repeat_rate=0.08,
        semantic_repeat_recall=0.92,
        semantic_repeat_precision=0.88,
        span_accuracy=0.99,
        rewrite_preservation_rate=1.0,
        duplicate_history_count=0,
        fault_injection_passed=True,
        prepare_p95_ms=90,
        rule_extraction_p95_ms=70,
        history_query_p95_ms=25,
        commit_p95_ms=40,
        deterministic_replay_passed=True,
    )


def test_automatic_success_stays_pending_until_human_gate_exists() -> None:
    report = AcceptanceEvaluator().evaluate(_passing_automatic())

    assert report.automatic_status == "passed"
    assert report.human_status == "pending"
    assert report.overall_status == "pending_human"
    assert not report.completion_claim_allowed


def test_identity_blind_review_measures_recognition_naturalness_and_flags() -> None:
    samples = (
        CharacterBlindSample(sample_id="sample.a", character_id="char.a", character_name="洛寒", text="洛寒先听完，才把问题原样推回去。"),
        CharacterBlindSample(sample_id="sample.b", character_id="char.b", character_name="程雾", text="程雾当场截住话头，逼对方给出期限。"),
        CharacterBlindSample(sample_id="sample.c", character_id="char.c", character_name="燕七", text="燕七退到门侧，先替身后的人留出路。"),
    )
    packet, key = build_character_blind_packet(samples, seed=17)
    public = packet.model_dump_json()
    assert "character_id" not in public
    assert "char.a" not in public
    assert "洛寒" not in public
    assert set(packet.candidate_labels) == set(key.label_to_character)

    ratings = tuple(
        CharacterBlindRating(
            sample_id=item.sample_id,
            reviewer_id=reviewer,
            guessed_label=key.character_to_label[key.sample_characters[item.sample_id]],
            naturalness=4,
            character_fit=4,
            prose_value=4,
        )
        for reviewer in ("reader.1", "reader.2")
        for item in packet.items
    )
    human = aggregate_character_blind_ratings(key, ratings, minimum_reviewers=2)
    report = AcceptanceEvaluator().evaluate(_passing_automatic(), human)

    assert human.recognition_rate == 1.0
    assert report.human_status == "passed"
    assert report.overall_status == "passed"
    assert report.completion_claim_allowed


def test_human_gate_fails_formulaic_or_low_scoring_results() -> None:
    samples = (
        CharacterBlindSample(sample_id="sample.a", character_id="char.a", character_name="洛寒", text="洛寒皱眉。"),
        CharacterBlindSample(sample_id="sample.b", character_id="char.b", character_name="程雾", text="程雾皱眉。"),
    )
    packet, key = build_character_blind_packet(samples, seed=4)
    ratings = tuple(
        CharacterBlindRating(
            sample_id=item.sample_id,
            reviewer_id=reviewer,
            guessed_label=packet.candidate_labels[0],
            naturalness=3,
            character_fit=2,
            prose_value=2,
            flags=("formulaic", "indistinguishable"),
        )
        for reviewer in ("reader.1", "reader.2")
        for item in packet.items
    )

    human = aggregate_character_blind_ratings(key, ratings)
    report = AcceptanceEvaluator().evaluate(_passing_automatic(), human)

    assert report.human_status == "failed"
    assert report.overall_status == "failed"
    assert not report.completion_claim_allowed


def test_each_required_automatic_threshold_is_a_hard_gate() -> None:
    baseline = _passing_automatic()
    for field, failing_value in {
        "immediate_exact_repeat_rate": 0.01,
        "chapter_semantic_over_limit": 1,
        "cliche_group_share": 0.21,
        "maximum_character_channel_share": 0.46,
        "cross_chapter_function_channel_repeat_rate": 0.11,
        "semantic_repeat_recall": 0.89,
        "semantic_repeat_precision": 0.84,
        "span_accuracy": 0.97,
        "rewrite_preservation_rate": 0.99,
        "duplicate_history_count": 1,
        "fault_injection_passed": False,
        "prepare_p95_ms": 101,
        "rule_extraction_p95_ms": 81,
        "history_query_p95_ms": 31,
        "commit_p95_ms": 51,
        "deterministic_replay_passed": False,
    }.items():
        evidence = baseline.model_copy(update={field: failing_value})
        report = AcceptanceEvaluator().evaluate(evidence)
        assert report.automatic_status == "failed", field
        assert not report.completion_claim_allowed
