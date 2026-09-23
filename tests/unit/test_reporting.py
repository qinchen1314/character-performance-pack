from character_performance.domain.behavior_models import (
    BehaviorFingerprint,
    BehaviorOccurrence,
    NarrativePosition,
    SyntaxFeatures,
    TextSpan,
)
from character_performance.reporting import (
    build_behavior_report,
    calculate_chapter_calibrated_gate_values,
)
from character_performance.gate_policy import GatePolicy, GateSpec
import pytest


def _occurrence(
    index: int,
    *,
    chapter: str,
    channel: str,
    group: str,
    function: str = "delay_response",
) -> BehaviorOccurrence:
    text = f"动作{index}"
    return BehaviorOccurrence(
        occurrence_id=f"occ.{index}",
        book_id="book.report",
        position=NarrativePosition(
            book_id="book.report",
            chapter_id=chapter,
            scene_id=f"scene.{index}",
            paragraph_index=index,
            beat_index=index,
            global_beat_index=index,
        ),
        actor_id="char.a",
        fingerprint=BehaviorFingerprint(
            semantic_groups={group},
            channel=channel,
            narrative_functions={function},
            actor_id="char.a",
            syntax_features=SyntaxFeatures(temporal_shape="instant"),
        ),
        source="extracted",
        text_span=TextSpan(start=0, end=len(text), text=text),
        confidence=1,
        generation_run_id=f"run.{index}",
        accepted_revision=1,
    )


def test_report_excludes_signature_families_from_channel_concentration() -> None:
    report = build_behavior_report(
        "book.report",
        (
            _occurrence(1, chapter="chapter.1", channel="gaze", group="signature_pause"),
            _occurrence(2, chapter="chapter.2", channel="gaze", group="signature_pause"),
            _occurrence(3, chapter="chapter.3", channel="hands", group="object_handling"),
            _occurrence(4, chapter="chapter.4", channel="spatial", group="distance_change"),
        ),
        signature_groups_by_actor={"char.a": frozenset({"signature_pause"})},
    )

    distribution = report.character_distributions[0]
    assert distribution.channel_counts["gaze"] == 2
    assert distribution.highest_non_signature_channel_share == 0.5


def test_cross_chapter_metric_does_not_count_repetition_inside_current_chapter() -> None:
    report = build_behavior_report(
        "book.report",
        (
            _occurrence(1, chapter="chapter.1", channel="gaze", group="gaze_hold"),
            _occurrence(2, chapter="chapter.1", channel="gaze", group="gaze_shift"),
        ),
    )

    gate = next(
        gate
        for gate in report.gates
        if gate.code == "CROSS_CHAPTER_FUNCTION_CHANNEL_REPEAT_RATE"
    )
    assert gate.sample_size == 0
    assert gate.value == 0
    assert gate.passed


def test_behavior_report_uses_calibrated_gate_policy() -> None:
    policy = GatePolicy(
        status="ready",
        source_report_sha256="sha256:" + "b" * 64,
        overrides=(
            GateSpec("MAX_CHARACTER_CHANNEL_SHARE", "maximum_character_channel_share", 0.40, "<="),
        ),
    )

    report = build_behavior_report(
        "book.report",
        (
            _occurrence(1, chapter="chapter.1", channel="gaze", group="gaze_hold"),
            _occurrence(2, chapter="chapter.2", channel="hands", group="object_handling"),
        ),
        gate_policy=policy,
    )

    gate = next(item for item in report.gates if item.code == "MAX_CHARACTER_CHANNEL_SHARE")
    assert gate.threshold == 0.40
    assert not gate.passed


def test_behavior_report_rejects_provisional_gate_policy() -> None:
    policy = GatePolicy(
        status="provisional",
        source_report_sha256="sha256:" + "d" * 64,
        overrides=(),
    )

    with pytest.raises(ValueError, match="only ready"):
        build_behavior_report("book.report", (), gate_policy=policy)


def test_calibrated_gate_values_use_chapter_p95_scope() -> None:
    values = calculate_chapter_calibrated_gate_values(
        (
            _occurrence(1, chapter="chapter.1", channel="gaze", group="gaze_hold"),
            _occurrence(2, chapter="chapter.1", channel="hands", group="object_handling"),
            _occurrence(3, chapter="chapter.2", channel="gaze", group="gaze_hold"),
            _occurrence(4, chapter="chapter.2", channel="gaze", group="gaze_shift"),
        )
    )

    value, chapter_count = values["MAX_CHARACTER_CHANNEL_SHARE"]
    assert chapter_count == 2
    assert value == 0.975
