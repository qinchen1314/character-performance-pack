import pytest

from character_performance.acceptance import (
    ExtractionBenchmarkCase,
    ExtractionTruth,
    benchmark_extractor,
    percentile,
)
from character_performance.domain.behavior_models import ExtractionRequest, NarrativePosition
from character_performance.domain.behavior_models import (
    ExtractedBehavior,
    ExtractionResult,
    TextSpan,
)
from character_performance.domain.models import CharacterProfile
from character_performance.extraction import RuleBasedBehaviorExtractor


def test_extraction_benchmark_uses_independent_truth_and_exact_spans() -> None:
    text = "他把指甲掐进掌心。"
    request = ExtractionRequest(
        run_id="run.benchmark",
        text=text,
        known_characters=(CharacterProfile(id="char.a"),),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.1",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )
    result = benchmark_extractor(
        RuleBasedBehaviorExtractor(),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    ExtractionTruth(
                        actor_id="char.a",
                        target_ids=(),
                        canonical_action="hand_clench",
                        semantic_group="hand_tension",
                        start=2,
                        end=8,
                    ),
                ),
            ),
        ),
    )

    assert result.true_positives == 1
    assert result.recall == 1
    assert result.precision == 1
    assert result.span_accuracy == 1


class _FixedExtractor:
    def __init__(self, behaviors: tuple[ExtractedBehavior, ...]) -> None:
        self.behaviors = behaviors

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return ExtractionResult(run_id=request.run_id, behaviors=self.behaviors)


class _MappedExtractor:
    def __init__(self, behaviors_by_run: dict[str, tuple[ExtractedBehavior, ...]]) -> None:
        self.behaviors_by_run = behaviors_by_run

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return ExtractionResult(
            run_id=request.run_id, behaviors=self.behaviors_by_run[request.run_id]
        )


def _behavior(
    *,
    actor_id: str = "char.a",
    target_ids: tuple[str, ...] = ("char.b",),
    canonical_action: str = "hand_clench",
    semantic_groups: frozenset[str] = frozenset({"hand_tension"}),
    start: int = 0,
    end: int = 3,
    confidence: float = 0.9,
) -> ExtractedBehavior:
    return ExtractedBehavior(
        actor_id=actor_id,
        target_ids=target_ids,
        text_span=TextSpan(start=start, end=end, text="abcdefghijklmnop"[start:end]),
        canonical_action=canonical_action,
        semantic_groups=semantic_groups,
        channel="hands",
        narrative_functions=frozenset({"anger_leak"}),
        confidence=confidence,
    )


def test_extraction_benchmark_requires_joint_identity_and_minimum_span_iou() -> None:
    request = ExtractionRequest(
        run_id="run.joint",
        text="abcdefgh",
        known_characters=tuple(
            CharacterProfile(id=character_id)
            for character_id in ("char.a", "char.b", "char.c")
        ),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.1",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )
    result = benchmark_extractor(
        _FixedExtractor(
            (
                _behavior(target_ids=("char.c",), start=0, end=4),
                _behavior(canonical_action="look_away", start=0, end=4),
                _behavior(start=4, end=8),
                _behavior(start=0, end=3),
            )
        ),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    ExtractionTruth(
                        actor_id="char.a",
                        target_ids=("char.b",),
                        canonical_action="hand_clench",
                        semantic_group="hand_tension",
                        start=0,
                        end=4,
                    ),
                ),
            ),
        ),
        minimum_iou=0.5,
    )

    assert result.true_positives == 1
    assert result.false_positives == 3
    assert result.false_negatives == 0
    assert result.micro.precision == 0.25
    assert result.mean_span_iou == 0.75
    assert result.span_accuracy == 0


def test_extraction_benchmark_uses_global_one_to_one_optimal_matching() -> None:
    request = ExtractionRequest(
        run_id="run.optimal",
        text="abcdefgh",
        known_characters=(CharacterProfile(id="char.a"), CharacterProfile(id="char.b")),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.1",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )
    result = benchmark_extractor(
        _FixedExtractor((_behavior(start=0, end=4), _behavior(start=1, end=4))),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    ExtractionTruth(
                        actor_id="char.a",
                        target_ids=("char.b",),
                        canonical_action="hand_clench",
                        semantic_group="hand_tension",
                        start=0,
                        end=4,
                    ),
                    ExtractionTruth(
                        actor_id="char.a",
                        target_ids=("char.b",),
                        canonical_action="hand_clench",
                        semantic_group="hand_tension",
                        start=0,
                        end=1,
                    ),
                ),
            ),
        ),
        minimum_iou=0.2,
    )

    assert result.true_positives == 2
    assert result.false_positives == 0
    assert result.false_negatives == 0


def test_extraction_benchmark_reports_micro_and_case_macro_metrics() -> None:
    def request(run_id: str) -> ExtractionRequest:
        return ExtractionRequest(
            run_id=run_id,
            text="abcdefgh",
            known_characters=(CharacterProfile(id="char.a"), CharacterProfile(id="char.b")),
            position=NarrativePosition(
                book_id="book.a",
                chapter_id=run_id,
                scene_id="scene.1",
                paragraph_index=0,
                beat_index=0,
                global_beat_index=1,
            ),
        )

    def truth(start: int, end: int) -> ExtractionTruth:
        return ExtractionTruth(
            actor_id="char.a",
            target_ids=("char.b",),
            canonical_action="hand_clench",
            semantic_group="hand_tension",
            start=start,
            end=end,
        )

    result = benchmark_extractor(
        _MappedExtractor({"run.hit": (_behavior(start=0, end=2),), "run.miss": ()}),
        (
            ExtractionBenchmarkCase(request=request("run.hit"), truths=(truth(0, 2),)),
            ExtractionBenchmarkCase(
                request=request("run.miss"),
                truths=(truth(0, 2), truth(2, 4), truth(4, 6)),
            ),
        ),
    )

    assert result.micro.precision == 1
    assert result.micro.recall == 0.25
    assert result.micro.f1 == 0.4
    assert result.macro.precision == 0.5
    assert result.macro.recall == 0.5
    assert result.macro.f1 == 0.5


def test_extraction_benchmark_attributes_nearby_errors_by_field() -> None:
    request = ExtractionRequest(
        run_id="run.errors",
        text="abcdefghijklmnop",
        known_characters=tuple(
            CharacterProfile(id=character_id)
            for character_id in ("char.a", "char.b", "char.c")
        ),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.errors",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )

    def truth(start: int, end: int) -> ExtractionTruth:
        return ExtractionTruth(
            actor_id="char.a",
            target_ids=("char.b",),
            canonical_action="hand_clench",
            semantic_group="hand_tension",
            start=start,
            end=end,
        )

    result = benchmark_extractor(
        _FixedExtractor(
            (
                _behavior(actor_id="char.c", start=0, end=2),
                _behavior(target_ids=("char.c",), start=2, end=4),
                _behavior(canonical_action="look_away", start=4, end=6),
                _behavior(semantic_groups=frozenset({"gaze_avoidance"}), start=6, end=8),
                _behavior(start=8, end=9),
                _behavior(start=14, end=16),
            )
        ),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    truth(0, 2),
                    truth(2, 4),
                    truth(4, 6),
                    truth(6, 8),
                    truth(8, 12),
                    truth(12, 14),
                ),
            ),
        ),
    )

    assert result.error_counts == {
        "actor_mismatch": 1,
        "target_mismatch": 1,
        "action_mismatch": 1,
        "semantic_group_mismatch": 1,
        "span_mismatch": 1,
        "missed_truth": 1,
        "spurious_prediction": 1,
    }
    assert sum(result.identity_confusion_matrix["__spurious__"].values()) == 1
    assert sum(
        predicted == "__missing__"
        for row in result.identity_confusion_matrix.values()
        for predicted, count in row.items()
        for _ in range(count)
    ) == 1


def test_extraction_benchmark_reports_confidence_calibration_curve() -> None:
    request = ExtractionRequest(
        run_id="run.calibration",
        text="abcdefgh",
        known_characters=(CharacterProfile(id="char.a"), CharacterProfile(id="char.b")),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.calibration",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )
    result = benchmark_extractor(
        _FixedExtractor(
            (
                _behavior(start=0, end=2, confidence=0.9),
                _behavior(start=2, end=4, confidence=0.8),
                _behavior(start=4, end=6, confidence=0.1),
            )
        ),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    ExtractionTruth(
                        actor_id="char.a",
                        target_ids=("char.b",),
                        canonical_action="hand_clench",
                        semantic_group="hand_tension",
                        start=0,
                        end=2,
                    ),
                ),
            ),
        ),
        calibration_bins=2,
    )

    assert [item.count for item in result.calibration.bins] == [1, 2]
    assert result.calibration.bins[0].mean_confidence == 0.1
    assert result.calibration.bins[0].empirical_accuracy == 0
    assert result.calibration.bins[1].mean_confidence == pytest.approx(0.85)
    assert result.calibration.bins[1].empirical_accuracy == 0.5
    assert result.calibration.expected_calibration_error == pytest.approx(0.2666666667)
    assert result.calibration.brier_score == pytest.approx(0.22)


def test_percentile_is_nearest_rank_and_rejects_empty_samples() -> None:
    assert percentile((1, 2, 3, 100), 95) == 100
